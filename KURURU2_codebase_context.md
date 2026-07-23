# E-car Safety Sense — KURURU2
## Codebase Context for GitHub Copilot

> **วันที่อัปเดต:** 18 กรกฎาคม 2026  
> **Repository:** https://github.com/amrtdemdevteam/ecarsafetysense  
> **Status:** Pilot — ติดตั้งบนรถคันแรก ทดสอบในโรงงานจริงแล้ว  

---

## 1. ภาพรวมโปรเจกต์

ระบบ **Forward Proximity Alert** สำหรับรถลากไฟฟ้า (Electric Towing Tractor) รุ่น KURURU2 ในโกดัง

**หลักการ:** Sensor วัดระยะสิ่งกีดขวางด้านหน้า → Raspberry Pi 5 ประมวลผล → Buzzer เตือนผู้ขับด้วยความถี่ที่ถี่ขึ้นตามระยะที่ใกล้ขึ้น (เหมือนเซนเซอร์ถอยจอดรถยนต์)

**ขอบเขตสำคัญ:**
- เป็นระบบ **operator alert เท่านั้น** — ไม่ใช่ safety-rated auto-stop
- ไม่ได้ certified ตาม ISO 13849 / IEC 61508
- เป็นตัวช่วยเสริม ไม่ใช่ตัวทดแทนความระมัดระวังของผู้ขับ

---

## 2. Hardware

### Compute
| ชิ้นส่วน | Pilot (ปัจจุบัน) | Production (แผน) |
|---|---|---|
| Controller | Raspberry Pi 5 (1GB) | CM5 2GB 16GB eMMC (no wireless) |
| IO Board | GPIO Screw Terminal 40P | Cytron CM5 IO Board |
| Storage | SD Card | eMMC built-in |
| WiFi | USB Dongle TL-WN823N (RTL8188EUS) | USB Dongle |

### Sensor
- **TFmini Plus** — ToF LiDAR, UART, 5V, IP65, range 0.1–12m, FOV 3.6°
- ⚠️ **หมดตลาด** — Alternative: **TF-NOVA** (IP67, FOV 14°×1°, range 7m, frame format เหมือนกัน)

### Buzzer
- **XB5KS2B4** Schneider Harmony — 90dB @ 1m, IP66/67/69, 24V AC/DC, มี LED แดง
- ต่อผ่าน **MOSFET RX1L08BGNC10** (N-ch, 60V, VGS(th) 1-2.5V) + **flyback diode 1N4007**
- ⚠️ **ต้องมี 1N4007 ขนาน buzzer เสมอ** ไม่งั้น MOSFET พัง (เจอมาแล้ว 2 ครั้ง)

### Power Chain
```
E-car 26V ACC
  → Fuse 5A
  → TVS SZ1.5SMC30AT3G (input spike protection)
  → Mornsun URB2424LD-30WR3 (isolated DC-DC, 24V→24V, 1500V isolation)
  → LM2596 step-down (24V→5V) → TFmini Plus
  → PD Module 65W (24V→USB-C 5V/3A) → RPi5
  → MOSFET → Buzzer (24V)
```

**GND Topology:** Mornsun แยก GND สองฝั่ง (isolation 1500V)
- `GND_DRI` = ฝั่งรถ (ก่อน Mornsun) — ห้ามต่อข้ามฝั่ง
- `GND_CON` = ฝั่งวงจร (หลัง Mornsun) — ทุก device ต้องใช้จุดนี้ร่วมกัน

### GPIO Pinout (RPi5)
```
Pin 2  (5V)      → TFmini Plus VCC (สายแดง)
Pin 6  (GND)     → GND_CON
Pin 8  (GPIO14)  → TFmini Plus RX (สายขาว) [UART TXD]
Pin 10 (GPIO15)  → TFmini Plus TX (สายเขียว) [UART RXD]
Pin 16 (GPIO23)  → R100Ω → MOSFET Gate → Buzzer
```

---

## 3. Software Architecture

### ไฟล์ในโปรเจกต์
```
ecarsafetysense/
├── safety_sense.py               ← โปรแกรมหลัก (Python 3, 526 บรรทัด)
├── config.json                   ← ตั้งค่าทั้งหมด (แก้ที่นี่ ไม่ต้องแตะโค้ด)
├── install.sh                    ← ติดตั้งครั้งเดียวจบ
├── safety_sense.service          ← systemd unit
├── safety_sense_monitor.desktop  ← VNC autostart terminal
└── readme.md
```

### Dependencies
```bash
pip install pyserial lgpio --break-system-packages
```
- `pyserial` — อ่าน UART จาก TFmini Plus
- `lgpio` — GPIO สำหรับ RPi5 (RPi.GPIO ใช้ไม่ได้กับ RP1 chip ของ RPi5)

---

## 4. config.json — ค่าปัจจุบันที่ใช้จริง

```json
{
  "uart": {
    "port": "/dev/ttyAMA0",
    "baud": 115200
  },
  "pins": {
    "buzzer": 23
  },
  "zones": {
    "clear_cm": 200,
    "far_cm":   150,
    "mid_cm":   100,
    "near_cm":  100
  },
  "buzzer": {
    "freq_far_hz":  3.0,
    "freq_mid_hz":  6.0,
    "freq_near_hz": 6.0,
    "duty_cycle_pct": 50
  },
  "sensor": {
    "median_window":  3,
    "min_dist_cm":    10,
    "max_dist_cm":    200,
    "min_strength":   0,
    "frame_rate_hz":  10
  },
  "filter": {
    "hysteresis_frames": 5,
    "min_hold_sec": 1.0
  },
  "watchdog": {
    "timeout_sec": 10.0
  },
  "health": {
    "fail_count_threshold": 999999
  },
  "log": {
    "dir": "/var/log/safety_sense",
    "max_mb": 200,
    "retain_days": 30,
    "check_every_sec": 300
  }
}
```

---

## 5. Zone Map — 3 Zone System

```
ระยะ (cm)    Zone    Buzzer                  ความหมาย
─────────────────────────────────────────────────────────
> 200        CLEAR   เงียบ                    ไม่มีของในระยะ
150 – 200    FAR     beep 3 Hz               มีของ แต่ยังไกล
100 – 150    MID     beep 3 → 6 Hz (smooth)  ระวัง
< 100        SOLID   buzz ต่อเนื่อง           หยุดทันที!
```

**หมายเหตุ:** ระบบเดิมออกแบบเป็น 4-zone (มี NEAR 50-100cm) แต่ปรับเป็น 3-zone หลังทดสอบจริง โดยตั้ง `near_cm = mid_cm = 100` ทำให้ NEAR zone หายไป และ < 100cm เป็น SOLID เลย

### Alert Patterns พิเศษ
| State | Pattern | เหตุ |
|---|---|---|
| SENSOR_WARN | beep-beep … หยุด (repeat) | strength ต่ำ / สัญญาณอ่อน |
| SENSOR_FAIL | beep-beep-beep … หยุด (repeat) | ไม่มี UART frame เกิน 10 วิ |

---

## 6. โครงสร้างโค้ด safety_sense.py

### 6.1 Config Loader
```python
CONFIG_PATH = Path("/opt/safety_sense/config.json")
CFG = load_config()
# โหลดทุก parameter จาก config.json เป็น global constants
```

### 6.2 GPIO (lgpio)
```python
_gpio_handle = lgpio.gpiochip_open(0)
lgpio.gpio_claim_output(_gpio_handle, PIN_BUZZER, 0)  # GPIO23, initial LOW
lgpio.gpio_write(_gpio_handle, PIN_BUZZER, 1)          # HIGH = buzzer ON
```
⚠️ **ต้องใช้ lgpio เท่านั้น** — RPi.GPIO ทำงานไม่ได้บน RPi5 (RP1 chip)

### 6.3 interpolate_freq(dist_cm) → float | None
```python
def interpolate_freq(dist_cm: int):
    """Returns Hz (float) or None = solid buzz."""
    if dist_cm > ZONE_CLEAR:    return 0.0    # เงียบ
    if dist_cm <= ZONE_NEAR:    return None   # SOLID
    if dist_cm > ZONE_FAR:      # FAR zone: ramp จาก FREQ_FAR
        t = (ZONE_CLEAR - dist_cm) / max(ZONE_CLEAR - ZONE_FAR, 1)
        return FREQ_FAR * (1 + 0.3 * t)
    if dist_cm > ZONE_MID:      # MID zone: interpolate FREQ_FAR → FREQ_MID
        t = (ZONE_FAR - dist_cm) / max(ZONE_FAR - ZONE_MID, 1)
        return FREQ_FAR + (FREQ_MID - FREQ_FAR) * t
    # NEAR zone: interpolate FREQ_MID → FREQ_NEAR
    t = (ZONE_MID - dist_cm) / max(ZONE_MID - ZONE_NEAR, 1)
    return FREQ_MID + (FREQ_NEAR - FREQ_MID) * t
```

### 6.4 class ZoneFilter
ป้องกัน zone กระโดดไปมาที่ขอบเขต 150cm และ 100cm
```python
class ZoneFilter:
    # hysteresis: zone ต้องปรากฏ N frames ติดกันถึงจะ commit (ปัจจุบัน = 5)
    # min_hold: zone ต้องอยู่นาน X วิ ก่อนเปลี่ยนได้ (ปัจจุบัน = 1.0 วิ)
    
    def update(self, raw_zone: str) -> str | None:
        # คืน zone ที่ confirmed แล้ว หรือ None ถ้ายังไม่ confirmed
```
**สำคัญ:** ZoneFilter ใช้สำหรับ **log เท่านั้น** — buzzer update ทันทีจาก raw dist โดยไม่รอ filter เพื่อให้ตอบสนองเร็ว

### 6.5 class TFminiPlus
อ่าน 9-byte frame จาก UART:
```
Byte: [0]   [1]   [2]    [3]    [4]   [5]   [6]   [7]   [8]
      0x59  0x59  distL  distH  strL  strH  resL  resH  checksum
```
Checksum = (sum of byte 0-7) & 0xFF

**Logic พิเศษที่แก้แล้ว (critical bug fix):**
```python
if not (MIN_DIST_CM <= dist <= MAX_DIST_CM):
    if dist > MAX_DIST_CM:
        return MAX_DIST_CM + 1, strength  # ไกลเกิน = CLEAR, feed watchdog
    if dist == 0:
        return MAX_DIST_CM + 1, strength  # ไม่มีเป้า = CLEAR, feed watchdog
    return None, None  # ระยะต่ำกว่า min_dist = invalid
```
> **เหตุผล:** TFmini Plus คืน `dist=0` เมื่อไม่มีเป้าในระยะ (เช่น ลานโล่ง 50 เมตร) ถ้า return None จะทำให้ watchdog ไม่ได้รับ frame → SENSOR_FAIL หลัง 10 วิ (false alarm) — แก้ไขแล้ว 17 Jul 2026

### 6.6 class SensorHealth
ตรวจ signal strength ทุก frame
- `bad_count >= HEALTH_FAIL_THRESH` → SENSOR_WARN
- ปัจจุบัน `HEALTH_FAIL_THRESH = 999999` → SENSOR_WARN ปิดถาวร (false alarm มาก)
- `min_strength = 0` → ไม่กรอง strength เลย

### 6.7 class Watchdog
Thread แยก ตรวจว่า `feed()` ถูกเรียกภายใน `timeout_sec`
- `feed()` เรียกทุกครั้งที่ได้ valid frame (รวมถึง dist=0 และ dist>MAX)
- timeout = 10 วิ → trigger SENSOR_FAIL
- สายขาด/sensor พัง = ไม่มี UART data เลย → watchdog ไม่ได้ feed → trigger

### 6.8 class BuzzerController
Background thread ขับ GPIO23 ด้วย software PWM
```python
_SILENT   =  0.0   # เงียบ
_SOLID    = -1.0   # buzz ต่อเนื่อง
_WARN_PAT = -2.0   # double-beep (SENSOR_WARN)
_FAIL_PAT = -3.0   # triple-beep (SENSOR_FAIL)
```
Buzzer update ทันทีจาก `buzzer.update(filtered)` — ไม่ผ่าน ZoneFilter

### 6.9 class LogManager
JSON Lines format แยกไฟล์รายวัน:
```jsonl
{"dist": 87, "zone": "SOLID", "freq_hz": "SOLID", "strength": 1250, "ts": "2026-07-17T10:22:34.412"}
{"event": "SENSOR_FAIL", "ts": "2026-07-17T10:08:52.123"}
```
- Log เฉพาะตอน zone เปลี่ยน (ผ่าน ZoneFilter confirmed)
- Auto-purge: ไฟล์อายุ > 30 วัน หรือโฟลเดอร์ > 200MB

### 6.10 Main Loop
```python
while True:
    dist, strength = sensor.read()          # อ่าน frame
    health.update(dist, strength)           # ตรวจ strength
    if dist is not None: watchdog.feed()    # บอก watchdog ว่ายังอยู่
    
    # Handle alerts
    if watchdog.is_triggered(): → buzzer SENSOR_FAIL, continue
    if health == SENSOR_WARN:   → buzzer SENSOR_WARN, continue
    if dist is None:            → continue (invalid frame)
    
    # Filter
    samples → rolling_median → filtered
    buzzer.update(filtered)                 # ← ทันที, ไม่รอ filter
    confirmed_zone = zfilter.update(zone)   # ← สำหรับ log
    if confirmed_zone: logmgr.write(...)
```

---

## 7. RPi5 UART Setup (สำคัญมาก)

RPi5 ใช้ chip **RP1** ซึ่งต่างจาก RPi4 อย่างสิ้นเชิง

### `/boot/firmware/config.txt`
```ini
enable_uart=1
dtoverlay=uart0-pi5
# ⛔ ห้ามมี: dtparam=uart0=on หรือ dtoverlay=uart0
```

### ปิด Serial Login Shell
```bash
sudo raspi-config
# Interface Options → Serial Port
# Login shell: No | Hardware: Yes
```

### ตรวจสอบ
```bash
ls -la /dev/serial*
# ต้องได้: /dev/serial0 -> ttyAMA0  ✅
# ถ้าได้:  /dev/serial0 -> ttyAMA10 ❌ (ยังไม่ได้ตั้ง overlay)
```

---

## 8. Deploy & Remote Access

### ติดตั้งครั้งแรก
```bash
git clone https://github.com/amrtdemdevteam/ecarsafetysense.git
cd ecarsafetysense
sudo bash install.sh
sudo reboot
```

### Workflow ปกติ
```powershell
# Windows — push
cd D:\KURURU_ecarsafetysense
git add .
git commit -m "message"
git push origin master
```

```bash
# Pi — pull + deploy
cd ~/ecarsafetysense && git pull && \
sudo cp safety_sense.py /opt/safety_sense/ && \
sudo cp config.json /opt/safety_sense/ && \
sudo systemctl restart safety_sense && \
journalctl -u safety_sense -f
```

### Remote เมื่อไม่มี WiFi (LAN ตรง)
```bash
# หา IP
ping raspberrypi.local

# SSH ผ่าน IPv6 link-local
ssh ecarsafetysense@fe80::88fe:4df:ffb4:1555%15

# SCP ส่งไฟล์
scp file.py "ecarsafetysense@[fe80::88fe:4df:ffb4:1555%15]:/home/ecarsafetysense/ecarsafetysense/file.py"
```

### SSH Info
- **IP:** 192.168.50.50 (WiFi) หรือ fe80::88fe:4df:ffb4:1555 (LAN direct)
- **User:** ecarsafetysense
- **Password:** 123456789

### systemd Commands
```bash
journalctl -u safety_sense -f          # log realtime
systemctl status safety_sense           # สถานะ
sudo systemctl restart safety_sense     # restart
sudo systemctl stop/start safety_sense  # หยุด/เริ่ม
```

---

## 9. ปัญหาที่เจอและแก้แล้ว

| # | ปัญหา | สาเหตุ | วิธีแก้ |
|---|---|---|---|
| 1 | MOSFET พัง 2 ครั้ง | ขาด flyback diode 1N4007 ขนาน buzzer | เพิ่ม 1N4007, เปลี่ยน MOSFET เป็น RX1L08BGNC10 (60V) |
| 2 | Cap 220µF/10V พัง | LM2596 ยังไม่ปรับ → output 20V | เปลี่ยนเป็น 220µF/50V |
| 3 | RPi.GPIO crash | RPi5 ใช้ RP1 chip ไม่รองรับ | เปลี่ยนเป็น lgpio |
| 4 | UART อ่านไม่ได้ | serial console ครอง UART / port map ผิด | raspi-config ปิด login shell + dtoverlay=uart0-pi5 |
| 5 | GND ไม่ร่วม → buzzer ไม่ดัง | ทดสอบด้วย power bank แยก | ต่อ RPi Pin6 → GND_CON |
| 6 | Voltage drop 26V→16V | จั๊มไฟจากสายสัญญาณ (กระแสน้อย) | เปลี่ยนจุดจั๊ม + connector XT30 |
| 7 | SENSOR_WARN บ่อย (false) | min_strength=100 แต่ค่าจริงแกว่ง / แดด IR | min_strength=0, fail_count_threshold=999999 |
| 8 | SENSOR_FAIL ในลานโล่ง (false) | dist=0 → return None → watchdog ไม่ feed | dist=0 และ dist>MAX → return MAX+1 (CLEAR) |
| 9 | Zone กระโดดที่ขอบ | ค่าแกว่ง ±2cm รอบขอบเขต | median_window=3, hysteresis=5, min_hold=1.0 |
| 10 | Connector OL จากรถ | pin ไม่ล็อค / crimp หลุด | เปลี่ยน connector คุณภาพสูง |

---

## 10. สิ่งที่ยังต้องทำ (TODO)

### Priority 1 — ก่อน deploy เพิ่ม
- [ ] เปลี่ยน buzzer เป็น XB5KS2B4 Schneider ใส่ใน enclosure
- [ ] ต่อ flyback diode 1N4007 ให้ครบ
- [ ] ใส่ IP65 enclosure พร้อม cable gland
- [ ] ซื้อ MOSFET RX1L08BGNC10 ทดแทน RS1G150MNTB เดิม

### Priority 2 — Phase 2
- [ ] เพิ่ม WiFi log sync ตอนรถจอดชาร์จ
- [ ] DIP Switch reader (ซื้อมาแล้วยังไม่ได้ใช้)
- [ ] UPS Supercap module (graceful shutdown)
- [ ] Custom PCB แทน perfboard (JLCPCB)

### Priority 3 — Phase 3 (Fleet)
- [ ] Fleet rollout 100 คัน
- [ ] Standard OS image
- [ ] Central log dashboard
- [ ] Remote update via cron

---

## 11. Test Scenarios

ทดสอบ 4 configuration:
1. **ท้าย Kururu** — sensor ติดหน้า Kururu ตรงๆ ไม่มี Dolly
2. **ท้าย E-car** — sensor ติดหน้า E-car ตรงๆ ไม่มี Dolly
3. **Dolly + Kururu** — Kururu ลาก Dolly, sensor ติดหน้า Dolly
4. **Dolly + E-car** — E-car ลาก Dolly, sensor ติดหน้า Dolly

แต่ละ config ทดสอบ 2 ขั้น:
- **Section 1:** Mock-up featureboard (ระยะ 200, 190, 150, 120, 100, 80, 50 cm + sensor fail)
- **Section 2:** Real environment in warehouse

**ผลทดสอบ 17 Jul 2026 (ท้าย Kururu):**
- Mock-up: PASS ทุกกรณี
- วิ่งในโกดัง: PASS หลัง fix dist=0 bug
- ออกตัวเร็ว: PASS (ไม่มี false alarm)
- ลานโล่ง: PASS (ไม่มี false SENSOR_FAIL)
- แดดจัด: SENSOR_FAIL หลัง 10 วิ (accepted)

---

## 12. Sensor Position

- **ความสูง:** 26 cm จากพื้น (ติดใต้ bumper)
- **มุม:** ก้ม 0.9° (เพื่อให้ beam center ที่ 23 cm ที่ระยะ 200 cm)
- **เหตุผล:** Target height = 20-26 cm → กึ่งกลาง = 23 cm
- FOV cone: 3.6° → ที่ 200 cm ครอบคลุมวงกลม ~12.6 cm

**ข้อจำกัด TFmini Plus:**
- Range สูงสุด 12 m → ลานโล่ง > 12 m ไม่มีเป้าสะท้อน → dist=0 (แก้แล้วด้วย watchdog feed)
- ถ้า sensor สูง > 34 cm จากพื้น → ตรวจไม่ได้ใน range ใกล้ (beam ยังไม่ลงมาถึง target)
- แดด IR รุนแรง → frame checksum fail → watchdog ไม่ feed → SENSOR_FAIL (acceptable)

---

## 13. Git History (สำคัญ)

| Commit | ความหมาย | สถานะ buzzer |
|---|---|---|
| ce76d2f | Fix: dist=0 and dist>MAX feed watchdog (latest) | ✅ ดัง |
| b180ae8 | Tune: FAR=3Hz, median_window=3, max_dist_cm=200 | ✅ ดัง |
| a5970b1 | Change: 3-zone config | ✅ ดัง |
| 8d08cdf | Fix: disable SENSOR_WARN | ✅ ดัง |
| 6013960 | Fix: SENSOR_WARN log once per event | ✅ Safe checkpoint |

---

*AMRT DEM DEV TEAM | KURURU2 Pilot Unit*  
*Last updated: 18 July 2026*
