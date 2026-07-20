#!/usr/bin/env python3
"""
E-car Safety Sense — KURURU2
Hardware : Raspberry Pi 5
Sensor   : TFmini Plus  UART TX→GPIO15 (RPi RX), RX→GPIO14 (RPi TX)
Buzzer   : Active piezo via MOSFET → GPIO23

Features:
  1. Frame rate 10Hz  — ลด TFmini Plus จาก 100Hz → 10Hz
  2. Hysteresis       — zone ต้องคงที่ N frames ติดกันถึงจะ commit
  3. Min hold time    — zone ต้องอยู่นาน X วิ ถึงจะ log และเปลี่ยน buzzer
"""

import json
import logging
import signal
import sys
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path

import serial
import lgpio

# ─────────────────────────────────────────────────────────────────────────────
# Config loader
# ─────────────────────────────────────────────────────────────────────────────
CONFIG_PATH = Path("/opt/safety_sense/config.json")

def load_config() -> dict:
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception as e:
        print(f"[FATAL] Cannot load {CONFIG_PATH}: {e}", file=sys.stderr)
        sys.exit(1)

CFG = load_config()

UART_PORT  = CFG["uart"]["port"]
UART_BAUD  = CFG["uart"]["baud"]
PIN_BUZZER = CFG["pins"]["buzzer"]

ZONE_CLEAR = CFG["zones"]["clear_cm"]
ZONE_FAR   = CFG["zones"]["far_cm"]
ZONE_MID   = CFG["zones"]["mid_cm"]
ZONE_NEAR  = CFG["zones"]["near_cm"]

FREQ_FAR   = CFG["buzzer"]["freq_far_hz"]
FREQ_MID   = CFG["buzzer"]["freq_mid_hz"]
FREQ_NEAR  = CFG["buzzer"]["freq_near_hz"]
DUTY       = CFG["buzzer"]["duty_cycle_pct"]

MEDIAN_WINDOW    = CFG["sensor"]["median_window"]
MIN_DIST_CM      = CFG["sensor"]["min_dist_cm"]
MAX_DIST_CM      = CFG["sensor"]["max_dist_cm"]
MIN_STRENGTH     = CFG["sensor"]["min_strength"]
FRAME_RATE_HZ    = CFG["sensor"].get("frame_rate_hz", 10)

WATCHDOG_TIMEOUT    = CFG["watchdog"]["timeout_sec"]
HEALTH_FAIL_THRESH  = CFG["health"]["fail_count_threshold"]

HYSTERESIS_FRAMES   = CFG.get("filter", {}).get("hysteresis_frames", 3)
MIN_HOLD_SEC        = CFG.get("filter", {}).get("min_hold_sec", 0.3)

LOG_DIR         = Path(CFG["log"]["dir"])
LOG_MAX_MB      = CFG["log"]["max_mb"]
LOG_RETAIN_DAYS = CFG["log"]["retain_days"]
LOG_CHECK_EVERY = CFG["log"]["check_every_sec"]

# ─────────────────────────────────────────────────────────────────────────────
# Logger
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("safety_sense")

# ─────────────────────────────────────────────────────────────────────────────
# GPIO handle (lgpio)
# ─────────────────────────────────────────────────────────────────────────────
_gpio_handle = None

def gpio_init():
    global _gpio_handle
    _gpio_handle = lgpio.gpiochip_open(0)
    lgpio.gpio_claim_output(_gpio_handle, PIN_BUZZER, 0)
    log.info(f"GPIO init OK — buzzer pin {PIN_BUZZER} (lgpio)")

def gpio_write(val: int):
    lgpio.gpio_write(_gpio_handle, PIN_BUZZER, val)

def gpio_cleanup():
    if _gpio_handle is not None:
        lgpio.gpio_write(_gpio_handle, PIN_BUZZER, 0)
        lgpio.gpiochip_close(_gpio_handle)

# ─────────────────────────────────────────────────────────────────────────────
# Frequency interpolator
# ─────────────────────────────────────────────────────────────────────────────
def interpolate_freq(dist_cm: int):
    """Returns Hz (float) or None = solid buzz."""
    if dist_cm > ZONE_CLEAR:
        return 0.0
    if dist_cm <= ZONE_NEAR:
        return None
    if dist_cm > ZONE_FAR:
        t = (ZONE_CLEAR - dist_cm) / max(ZONE_CLEAR - ZONE_FAR, 1)
        return FREQ_FAR * (1 + 0.3 * t)
    if dist_cm > ZONE_MID:
        t = (ZONE_FAR - dist_cm) / max(ZONE_FAR - ZONE_MID, 1)
        return FREQ_FAR + (FREQ_MID - FREQ_FAR) * t
    t = (ZONE_MID - dist_cm) / max(ZONE_MID - ZONE_NEAR, 1)
    return FREQ_MID + (FREQ_NEAR - FREQ_MID) * t


def zone_label(dist_cm: int) -> str:
    if dist_cm > ZONE_CLEAR: return "CLEAR"
    if dist_cm > ZONE_FAR:   return "FAR"
    if dist_cm > ZONE_MID:   return "MID"
    if dist_cm > ZONE_NEAR:  return "NEAR"
    return "SOLID"

# ─────────────────────────────────────────────────────────────────────────────
# Zone filter — Hysteresis + Min hold time
# ─────────────────────────────────────────────────────────────────────────────
class ZoneFilter:
    """
    Zone จะถูก commit ก็ต่อเมื่อ:
      1. zone เดิมปรากฏ hysteresis_frames ติดกัน (ป้องกัน noise)
      2. zone อยู่นาน min_hold_sec วิ (ป้องกัน transient)

    ผล: SOLID → CLEAR จะไม่มี FAR/MID แทรกกลาง
    """

    def __init__(self, hysteresis: int, min_hold: float):
        self.hysteresis  = hysteresis
        self.min_hold    = min_hold

        self._candidate       = None   # zone ที่กำลังสะสม frames
        self._candidate_count = 0      # จำนวน frames ติดกัน
        self._committed       = None   # zone ที่ confirmed แล้ว
        self._committed_since = 0.0    # เวลาที่ commit

    def update(self, raw_zone: str) -> str | None:
        """
        ส่ง raw_zone เข้ามาทุก frame
        คืน zone ที่ confirmed (ถ้ายังไม่ confirmed คืน None)
        """
        now = time.monotonic()

        # สะสม hysteresis
        if raw_zone == self._candidate:
            self._candidate_count += 1
        else:
            self._candidate       = raw_zone
            self._candidate_count = 1

        # ยังไม่ครบ hysteresis
        if self._candidate_count < self.hysteresis:
            return None

        # zone candidate ครบ hysteresis แล้ว
        # ตรวจ min_hold: ถ้า committed เดิมอยู่ไม่ถึง min_hold ยังไม่เปลี่ยน
        if raw_zone != self._committed:
            if self._committed is not None:
                held = now - self._committed_since
                if held < self.min_hold:
                    return None   # รอให้ zone เดิมอยู่ครบก่อน

            # commit zone ใหม่
            self._committed       = raw_zone
            self._committed_since = now
            return raw_zone

        return None   # zone เดิม ไม่มีการเปลี่ยน

    @property
    def committed_zone(self) -> str | None:
        return self._committed

# ─────────────────────────────────────────────────────────────────────────────
# Log manager
# ─────────────────────────────────────────────────────────────────────────────
class LogManager:
    def __init__(self):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._last_check = 0.0

    def _path(self) -> Path:
        return LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log"

    def write(self, record: dict):
        record["ts"] = datetime.now().isoformat(timespec="milliseconds")
        with open(self._path(), "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        now = time.monotonic()
        if now - self._last_check >= LOG_CHECK_EVERY:
            self._last_check = now
            self._purge()

    def _purge(self):
        files = sorted(LOG_DIR.glob("*.log"))
        cutoff = datetime.now() - timedelta(days=LOG_RETAIN_DAYS)
        for f in files[:]:
            try:
                if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                    f.unlink(); files.remove(f)
                    log.info(f"[Log] Deleted old: {f.name}")
            except Exception as e:
                log.warning(f"[Log] Remove failed {f.name}: {e}")
        while files:
            total_mb = sum(f.stat().st_size for f in files if f.exists()) / 1_048_576
            if total_mb <= LOG_MAX_MB:
                break
            oldest = files.pop(0)
            try:
                oldest.unlink()
                log.info(f"[Log] Deleted for size ({total_mb:.1f} MB): {oldest.name}")
            except Exception as e:
                log.warning(f"[Log] Remove failed {oldest.name}: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# TFmini Plus driver
# ─────────────────────────────────────────────────────────────────────────────
class TFminiPlus:
    HEADER = 0x59

    # Frame rate command: 0x5A 0x06 0x03 <rate_L> <rate_H> <checksum>
    FRAMERATE_CMD = {
        10:  bytes([0x5A, 0x06, 0x03, 0x0A, 0x00, 0x6D]),
        20:  bytes([0x5A, 0x06, 0x03, 0x14, 0x00, 0x77]),
        50:  bytes([0x5A, 0x06, 0x03, 0x32, 0x00, 0x95]),
        100: bytes([0x5A, 0x06, 0x03, 0x64, 0x00, 0xC7]),
    }

    def __init__(self):
        self.ser = serial.Serial(UART_PORT, UART_BAUD, timeout=0.1)
        log.info(f"TFmini Plus on {UART_PORT} @ {UART_BAUD}")
        self._set_framerate(FRAME_RATE_HZ)

    def _set_framerate(self, hz: int):
        cmd = self.FRAMERATE_CMD.get(hz)
        if cmd:
            self.ser.write(cmd)
            time.sleep(0.1)
            self.ser.flushInput()
            log.info(f"TFmini Plus frame rate set to {hz} Hz")
        else:
            log.warning(f"Frame rate {hz}Hz not supported, using default 100Hz")

    def read(self):
        """Returns (dist_cm, strength) or (None, None)."""
        while True:
            b = self.ser.read(1)
            if not b:
                return None, None
            if b[0] == self.HEADER:
                b2 = self.ser.read(1)
                if b2 and b2[0] == self.HEADER:
                    break

        rest = self.ser.read(7)
        if len(rest) < 7:
            return None, None

        dist_l, dist_h, str_l, str_h, res_l, res_h, checksum = rest
        dist     = (dist_h << 8) | dist_l
        strength = (str_h  << 8) | str_l

        raw = [self.HEADER, self.HEADER, dist_l, dist_h,
               str_l, str_h, res_l, res_h]
        if (sum(raw) & 0xFF) != checksum:
            return None, None

        if not (MIN_DIST_CM <= dist <= MAX_DIST_CM):
            if dist > MAX_DIST_CM:
                return MAX_DIST_CM + 1, strength
            return None, None

        return dist, strength

    def close(self):
        self.ser.close()

# ─────────────────────────────────────────────────────────────────────────────
# Sensor health
# ─────────────────────────────────────────────────────────────────────────────
class SensorHealth:
    def __init__(self):
        self.bad_count  = 0
        self.is_warning = False

    def update(self, dist, strength) -> str:
        if dist is None or strength is None or strength < MIN_STRENGTH:
            self.bad_count += 1
        else:
            if self.is_warning:
                log.info("[Health] Sensor recovered")
            self.bad_count  = 0
            self.is_warning = False
            return "OK"

        if self.bad_count >= HEALTH_FAIL_THRESH:
            if not self.is_warning:
                log.warning(f"[Health] SENSOR_WARN — {self.bad_count} bad frames")
            self.is_warning = True
            return "SENSOR_WARN"
        return "OK"

# ─────────────────────────────────────────────────────────────────────────────
# Watchdog
# ─────────────────────────────────────────────────────────────────────────────
class Watchdog:
    def __init__(self, timeout: float):
        self.timeout    = timeout
        self._last_fed  = time.monotonic()
        self._lock      = threading.Lock()
        self._triggered = False
        threading.Thread(target=self._run, daemon=True).start()
        log.info(f"Watchdog started (timeout={timeout}s)")

    def feed(self):
        with self._lock:
            self._last_fed = time.monotonic()
            if self._triggered:
                log.info("[Watchdog] Sensor recovered")
                self._logged = False
            self._triggered = False

    def is_triggered(self) -> bool:
        with self._lock:
            return self._triggered

    def _run(self):
        while True:
            time.sleep(0.5)
            with self._lock:
                elapsed = time.monotonic() - self._last_fed
                if elapsed >= self.timeout and not self._triggered:
                    self._triggered = True
                    log.error(f"[Watchdog] SENSOR_FAIL — no frame for {elapsed:.1f}s")

# ─────────────────────────────────────────────────────────────────────────────
# Buzzer controller
# ─────────────────────────────────────────────────────────────────────────────
class BuzzerController:
    _SILENT   =  0.0
    _SOLID    = -1.0
    _WARN_PAT = -2.0
    _FAIL_PAT = -3.0

    def __init__(self):
        self._target_freq = self._SILENT
        self._lock        = threading.Lock()
        threading.Thread(target=self._run, daemon=True).start()
        self._startup_beep()

    def update(self, dist_cm: int):
        freq = interpolate_freq(dist_cm)
        target = self._SOLID if freq is None else freq
        with self._lock:
            self._target_freq = target

    def set_alert(self, kind: str):
        target = self._WARN_PAT if kind == "SENSOR_WARN" else self._FAIL_PAT
        with self._lock:
            self._target_freq = target

    def set_silent(self):
        with self._lock:
            self._target_freq = self._SILENT

    def cleanup(self):
        with self._lock:
            self._target_freq = self._SILENT
        time.sleep(0.1)
        gpio_write(0)
        gpio_cleanup()

    def _run(self):
        while True:
            with self._lock:
                freq = self._target_freq

            if freq == self._SILENT:
                gpio_write(0)
                time.sleep(0.05)
            elif freq == self._SOLID:
                gpio_write(1)
                time.sleep(0.05)
            elif freq == self._WARN_PAT:
                self._pulse(0.08)
                self._pulse(0.08)
                self._sleep_check(0.80)
            elif freq == self._FAIL_PAT:
                self._pulse(0.07)
                self._pulse(0.07)
                self._pulse(0.07)
                self._sleep_check(0.60)
            else:
                half = 1.0 / (2.0 * max(freq, 0.1))
                gpio_write(1)
                self._sleep_check(half)
                gpio_write(0)
                self._sleep_check(half)

    def _pulse(self, dur: float):
        gpio_write(1)
        time.sleep(dur)
        gpio_write(0)
        time.sleep(dur)

    def _sleep_check(self, duration: float):
        end = time.monotonic() + duration
        while time.monotonic() < end:
            time.sleep(0.02)

    def _startup_beep(self):
        time.sleep(0.3)
        gpio_write(1)
        time.sleep(0.15)
        gpio_write(0)
        log.info("Startup beep ✓")

# ─────────────────────────────────────────────────────────────────────────────
# Rolling median
# ─────────────────────────────────────────────────────────────────────────────
def rolling_median(buf: list) -> int:
    s = sorted(buf)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) // 2

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    gpio_init()
    sensor   = TFminiPlus()
    buzzer   = BuzzerController()
    watchdog = Watchdog(WATCHDOG_TIMEOUT)
    health   = SensorHealth()
    logmgr   = LogManager()
    zfilter  = ZoneFilter(HYSTERESIS_FRAMES, MIN_HOLD_SEC)
    samples  = []

    def shutdown(sig, frame):
        log.info("Shutdown — cleaning up")
        buzzer.cleanup()
        sensor.close()
        sys.exit(0)

    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    log.info("=== Safety Sense started ===")
    log.info(
        f"Zones (cm): CLEAR>{ZONE_CLEAR}  FAR>{ZONE_FAR}  "
        f"MID>{ZONE_MID}  NEAR>{ZONE_NEAR}  SOLID≤{ZONE_NEAR}"
    )
    log.info(f"Freq anchors: FAR={FREQ_FAR}Hz  MID={FREQ_MID}Hz  NEAR={FREQ_NEAR}Hz")
    log.info(f"Filter: hysteresis={HYSTERESIS_FRAMES} frames  min_hold={MIN_HOLD_SEC}s  frame_rate={FRAME_RATE_HZ}Hz")

    while True:
        dist, strength = sensor.read()

        health_status = health.update(dist, strength)

        if dist is not None:
            watchdog.feed()

        if watchdog.is_triggered():
            buzzer.set_alert("SENSOR_FAIL")
            if not getattr(watchdog, '_logged', False):
                logmgr.write({"event": "SENSOR_FAIL"})
                watchdog._logged = True
            continue

        if health_status == "SENSOR_WARN":
            buzzer.set_alert("SENSOR_WARN")
            if not health.is_warning or health.bad_count == HEALTH_FAIL_THRESH:
                logmgr.write({"event": "SENSOR_WARN",
                              "bad_count": health.bad_count,
                              "strength": strength})
            continue

        if dist is None:
            continue

        # Rolling median filter
        samples.append(dist)
        if len(samples) > MEDIAN_WINDOW:
            samples.pop(0)
        filtered = rolling_median(samples)

        raw_zone = zone_label(filtered)

        # Update buzzer immediately (ไม่รอ filter — buzzer ต้องตอบสนองทันที)
        buzzer.update(filtered)

        # Zone filter: hysteresis + min hold
        confirmed_zone = zfilter.update(raw_zone)

        if confirmed_zone is not None:
            freq = interpolate_freq(filtered)
            logmgr.write({
                "dist":     filtered,
                "zone":     confirmed_zone,
                "freq_hz":  round(freq, 2) if freq is not None else "SOLID",
                "strength": strength,
            })
            log.info(
                f"{filtered:4d} cm  str={strength:5d}  [{confirmed_zone}]  "
                f"freq={'SOLID' if freq is None else f'{freq:.1f}Hz'}"
            )


if __name__ == "__main__":
    main()
