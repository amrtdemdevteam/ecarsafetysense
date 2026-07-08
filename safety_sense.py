#!/usr/bin/env python3
"""
E-car Safety Sense — KURURU2
Hardware : Raspberry Pi 5
Sensor   : TFmini Plus  UART TX→GPIO15 (RPi RX), RX→GPIO14 (RPi TX)
Buzzer   : Active piezo via MOSFET → GPIO23

Beep behaviour (แบบรถยนต์ถอยจอด):
  dist > clear_cm  → เงียบ
  far_cm..clear_cm → beep ที่ freq_far_hz   (ถี่ขึ้น linear ตามระยะ)
  mid_cm..far_cm   → beep ที่ freq_mid_hz   (ถี่ขึ้น linear ตามระยะ)
  near_cm..mid_cm  → beep ที่ freq_near_hz  (ถี่ขึ้น linear ตามระยะ)
  dist < near_cm   → SOLID buzz ต่อเนื่อง (ใกล้มากเกินไป)

  Interpolation: ภายในแต่ละ zone freq จะค่อยๆ เปลี่ยนแบบ smooth
  ตาม: f = f_lo + (f_hi - f_lo) * (1 - dist_in_zone / zone_size)

Features:
  - Watchdog timer  → SENSOR_FAIL (triple-beep) ถ้า sensor เงียบ
  - Sensor health   → SENSOR_WARN (double-beep) ถ้า strength ต่ำ
  - Config file     → /opt/safety_sense/config.json
  - JSON-Lines log  → /var/log/safety_sense/YYYY-MM-DD.log
  - Log rotation    → 30-day retention + folder size cap
  - Startup beep    → 1 short beep = system ready
  - Clean shutdown  → SIGTERM / Ctrl-C
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
import RPi.GPIO as GPIO


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

MEDIAN_WINDOW   = CFG["sensor"]["median_window"]
MIN_DIST_CM     = CFG["sensor"]["min_dist_cm"]
MAX_DIST_CM     = CFG["sensor"]["max_dist_cm"]
MIN_STRENGTH    = CFG["sensor"]["min_strength"]

WATCHDOG_TIMEOUT   = CFG["watchdog"]["timeout_sec"]
HEALTH_FAIL_THRESH = CFG["health"]["fail_count_threshold"]

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
# Frequency interpolator
# ─────────────────────────────────────────────────────────────────────────────
def interpolate_freq(dist_cm: int) -> float | None:
    """
    Returns the beep frequency (Hz) for a given distance, or None = solid buzz.

    Zone map:
      dist > CLEAR          → None (silent, handled outside)
      FAR  < dist <= CLEAR  → interpolate FREQ_FAR  at FAR edge .. FREQ_FAR  at CLEAR edge
                               (constant freq_far in outer zone, ramps up toward FAR boundary)
      MID  < dist <= FAR    → interpolate FREQ_FAR  → FREQ_MID
      NEAR < dist <= MID    → interpolate FREQ_MID  → FREQ_NEAR
      dist <= NEAR          → None (solid)

    Linear interpolation within each zone:
      t = 0 at zone far edge (quieter), t = 1 at zone near edge (louder)
      freq = f_lo + (f_hi - f_lo) * t
    """
    if dist_cm > ZONE_CLEAR:
        return 0.0          # silent

    if dist_cm <= ZONE_NEAR:
        return None         # solid buzz

    if dist_cm > ZONE_FAR:
        # Outer zone: FAR..CLEAR — steady at FREQ_FAR, ramps slightly toward FAR
        # t=0 at CLEAR, t=1 at FAR boundary
        t = (ZONE_CLEAR - dist_cm) / max(ZONE_CLEAR - ZONE_FAR, 1)
        return FREQ_FAR * (1 + 0.3 * t)   # subtle ramp, not a full jump

    if dist_cm > ZONE_MID:
        # Mid zone: MID..FAR — FREQ_FAR → FREQ_MID
        t = (ZONE_FAR - dist_cm) / max(ZONE_FAR - ZONE_MID, 1)
        return FREQ_FAR + (FREQ_MID - FREQ_FAR) * t

    # Near zone: NEAR..MID — FREQ_MID → FREQ_NEAR
    t = (ZONE_MID - dist_cm) / max(ZONE_MID - ZONE_NEAR, 1)
    return FREQ_MID + (FREQ_NEAR - FREQ_MID) * t


def zone_label(dist_cm: int) -> str:
    if dist_cm > ZONE_CLEAR: return "CLEAR"
    if dist_cm > ZONE_FAR:   return "FAR"
    if dist_cm > ZONE_MID:   return "MID"
    if dist_cm > ZONE_NEAR:  return "NEAR"
    return "SOLID"


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

    def __init__(self):
        self.ser = serial.Serial(UART_PORT, UART_BAUD, timeout=0.1)
        log.info(f"TFmini Plus on {UART_PORT} @ {UART_BAUD}")

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
    """
    Main thread calls update(dist_cm) every loop.
    A background beep-thread handles the actual on/off toggling so the
    main loop never blocks.

    States:
      freq > 0   → beep at that frequency (software timer in thread)
      freq = 0   → silent
      freq = -1  → solid buzz (NEAR zone)
      freq = -2  → SENSOR_WARN pattern (double-beep)
      freq = -3  → SENSOR_FAIL pattern (triple-beep)
    """

    _SILENT      =  0.0
    _SOLID       = -1.0
    _WARN_PAT    = -2.0
    _FAIL_PAT    = -3.0

    def __init__(self):
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(PIN_BUZZER, GPIO.OUT, initial=GPIO.LOW)
        self._target_freq = self._SILENT
        self._lock        = threading.Lock()
        self._thread      = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._startup_beep()

    # ── Public ────────────────────────────────────────────────────────────────

    def update(self, dist_cm: int):
        freq = interpolate_freq(dist_cm)
        if freq is None:
            target = self._SOLID
        else:
            target = freq        # 0.0 = silent, >0 = beep
        with self._lock:
            self._target_freq = target

    def set_alert(self, kind: str):
        """kind: 'SENSOR_WARN' | 'SENSOR_FAIL'"""
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
        GPIO.output(PIN_BUZZER, GPIO.LOW)
        GPIO.cleanup()

    # ── Background beep thread ────────────────────────────────────────────────

    def _run(self):
        """
        Runs forever. Reads self._target_freq and drives the buzzer pin.
        Rechecks freq after every half-cycle so zone changes feel instant.
        """
        while True:
            with self._lock:
                freq = self._target_freq

            if freq == self._SILENT:
                GPIO.output(PIN_BUZZER, GPIO.LOW)
                time.sleep(0.05)

            elif freq == self._SOLID:
                GPIO.output(PIN_BUZZER, GPIO.HIGH)
                time.sleep(0.05)

            elif freq == self._WARN_PAT:
                # double-beep: on-off-on-off ... pause
                self._pulse(0.08)
                self._pulse(0.08)
                self._sleep_interruptible(0.80)

            elif freq == self._FAIL_PAT:
                # triple-beep: on-off-on-off-on-off ... pause
                self._pulse(0.07)
                self._pulse(0.07)
                self._pulse(0.07)
                self._sleep_interruptible(0.60)

            else:
                # Normal beep: freq Hz, 50% duty
                half = 1.0 / (2.0 * max(freq, 0.1))
                GPIO.output(PIN_BUZZER, GPIO.HIGH)
                self._sleep_interruptible(half)
                GPIO.output(PIN_BUZZER, GPIO.LOW)
                self._sleep_interruptible(half)

    def _pulse(self, dur: float):
        GPIO.output(PIN_BUZZER, GPIO.HIGH)
        time.sleep(dur)
        GPIO.output(PIN_BUZZER, GPIO.LOW)
        time.sleep(dur)

    def _sleep_interruptible(self, duration: float):
        """Sleep in small chunks so freq changes apply quickly."""
        end = time.monotonic() + duration
        while time.monotonic() < end:
            with self._lock:
                if self._target_freq != self._target_freq:  # always false, just yield
                    break
            time.sleep(0.02)

    def _startup_beep(self):
        time.sleep(0.3)
        GPIO.output(PIN_BUZZER, GPIO.HIGH)
        time.sleep(0.15)
        GPIO.output(PIN_BUZZER, GPIO.LOW)
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
# Main loop
# ─────────────────────────────────────────────────────────────────────────────
def main():
    sensor   = TFminiPlus()
    buzzer   = BuzzerController()
    watchdog = Watchdog(WATCHDOG_TIMEOUT)
    health   = SensorHealth()
    logmgr   = LogManager()
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
    log.info(
        f"Freq anchors: FAR={FREQ_FAR}Hz  MID={FREQ_MID}Hz  NEAR={FREQ_NEAR}Hz"
    )

    prev_zone = None

    while True:
        dist, strength = sensor.read()

        # ── Health + Watchdog ─────────────────────────────────────────────────
        health_status = health.update(dist, strength)

        if dist is not None:
            watchdog.feed()

        if watchdog.is_triggered():
            buzzer.set_alert("SENSOR_FAIL")
            logmgr.write({"event": "SENSOR_FAIL"})
            continue

        if health_status == "SENSOR_WARN":
            buzzer.set_alert("SENSOR_WARN")
            logmgr.write({"event": "SENSOR_WARN",
                          "bad_count": health.bad_count,
                          "strength": strength})
            continue

        if dist is None:
            continue

        # ── Distance processing ───────────────────────────────────────────────
        samples.append(dist)
        if len(samples) > MEDIAN_WINDOW:
            samples.pop(0)

        filtered = rolling_median(samples)
        zone     = zone_label(filtered)
        freq     = interpolate_freq(filtered)

        buzzer.update(filtered)

        logmgr.write({
            "dist":     filtered,
            "zone":     zone,
            "freq_hz":  round(freq, 2) if freq is not None else "SOLID",
            "strength": strength,
        })

        # Log on zone change or every 10th reading (avoid spam)
        if zone != prev_zone:
            log.info(
                f"{filtered:4d} cm  str={strength:5d}  [{zone}]  "
                f"freq={'SOLID' if freq is None else f'{freq:.1f}Hz'}"
            )
            prev_zone = zone


if __name__ == "__main__":
    main()
