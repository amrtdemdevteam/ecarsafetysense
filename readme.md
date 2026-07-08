# E-car Safety Sense — KURURU2

ระบบแจ้งเตือนระยะใกล้สำหรับรถลากไฟฟ้า KURURU2 ในโกดัง  
ตรวจจับสิ่งกีดขวางด้านหน้าด้วย ToF LiDAR และแจ้งเตือนผู้ขับด้วย buzzer แบบรถยนต์ถอยจอด

---

## Hardware

| ชิ้นส่วน | รุ่น |
|---|---|
| Controller | Raspberry Pi 5 |
| Sensor | TFmini Plus (IP65, UART) |
| Buzzer | Active piezo 95dB 3–24V via MOSFET |
| GPIO library | lgpio (รองรับ RPi5) |

### การต่อขา

```
TFmini Plus TX  →  GPIO15 (RPi RX)
TFmini Plus RX  →  GPIO14 (RPi TX)
TFmini Plus VCC →  5V
TFmini Plus GND →  GND

MOSFET Gate     →  GPIO23
Buzzer (+)      →  24V (ผ่าน MOSFET)
Buzzer (-)      →  GND
```

---

## Zone Map

```
ระยะ (cm)     Zone     Buzzer
> 200         CLEAR    เงียบ
150 – 200     FAR      beep ช้า ~1 Hz
100 – 150     MID      beep กลาง → 3 Hz
 50 – 100     NEAR     beep ถี่ → 8 Hz
< 50          SOLID    buzz ต่อเนื่อง
```

ความถี่ภายในแต่ละ zone จะ interpolate แบบ smooth ตามระยะ ไม่กระโดดทันที

### Alert พิเศษ

| สถานะ | Pattern | ความหมาย |
|---|---|---|
| SENSOR_WARN | beep-beep ... หยุด | เลนส์สกปรก / สัญญาณอ่อน |
| SENSOR_FAIL | beep-beep-beep ... หยุด | sensor ไม่ส่งข้อมูล (ขาด / พัง) |

---

## ติดตั้ง

### ข้อกำหนดเบื้องต้น

เปิด UART บน RPi5 ก่อน (ครั้งแรกครั้งเดียว):

```bash
sudo raspi-config
# Interface Options → Serial Port
# Login shell: No  |  Hardware enabled: Yes
# → Reboot
```

### ติดตั้งระบบ

```bash
git clone https://github.com/amrtdemdevteam/ecarsafetysense.git
cd ecarsafetysense
sudo bash install.sh
```

`install.sh` จะทำทุกอย่างให้อัตโนมัติ:
- ติดตั้ง Python packages (pyserial, lgpio)
- copy ไฟล์ไปที่ `/opt/safety_sense/`
- ลง systemd service (autostart + restart on crash)
- ลง VNC terminal monitor (popup log อัตโนมัติตอนบูต)

---

## ไฟล์ในโปรเจกต์

```
ecarsafetysense/
├── safety_sense.py              # โค้ดหลัก
├── config.json                  # ตั้งค่าทั้งหมด (แก้ที่นี่)
├── install.sh                   # ติดตั้งครั้งเดียวจบ
├── safety_sense.service         # systemd unit file
├── safety_sense_monitor.desktop # VNC terminal popup autostart
└── readme.md                    # ไฟล์นี้
```

---

## ตั้งค่า

แก้ค่าได้ที่ `/opt/safety_sense/config.json` โดยไม่ต้องแตะโค้ด

```json
"zones": {
    "clear_cm": 200,   ← เริ่ม beep ที่ระยะนี้
    "far_cm":   150,   ← เปลี่ยน zone FAR → MID
    "mid_cm":   100,   ← เปลี่ยน zone MID → NEAR
    "near_cm":   50    ← เปลี่ยน zone NEAR → SOLID
},
"buzzer": {
    "freq_far_hz":  1.0,   ← Hz ที่ขอบ FAR
    "freq_mid_hz":  3.0,   ← Hz ที่ขอบ MID
    "freq_near_hz": 8.0    ← Hz ที่ขอบ NEAR
}
```

หลังแก้ค่า restart service:

```bash
sudo systemctl restart safety_sense
```

---

## คำสั่งที่ใช้บ่อย

```bash
# ดู log realtime
journalctl -u safety_sense -f

# ดูสถานะ
systemctl status safety_sense

# restart
sudo systemctl restart safety_sense

# หยุด
sudo systemctl stop safety_sense

# ดูไฟล์ log
ls -lh /var/log/safety_sense/
```

---

## Log

บันทึกเป็น JSON Lines แยกรายวันที่ `/var/log/safety_sense/YYYY-MM-DD.log`

```json
{"dist": 87, "zone": "NEAR", "freq_hz": 6.4, "strength": 1250, "ts": "2026-07-08T10:22:34.412"}
{"event": "SENSOR_WARN", "bad_count": 5, "strength": 45, "ts": "2026-07-08T10:25:01.001"}
```

ระบบลบ log อัตโนมัติ:
- ไฟล์อายุเกิน **30 วัน** → ลบทิ้ง
- โฟลเดอร์ใหญ่เกิน **200 MB** → ลบไฟล์เก่าสุดก่อน

---

## อัปเดตโค้ด (ทำหลายคันได้เลย)

```bash
# บน Windows — push โค้ดใหม่
git push origin master

# บน Pi แต่ละคัน
cd ~/ecarsafetysense
git pull
sudo bash install.sh
```

---

## Features

- ✅ Car-style proximity beep — ถี่ขึ้น smooth ตามระยะ
- ✅ Watchdog timer — ตรวจจับ sensor หาย/ตาย
- ✅ Sensor health check — ตรวจ signal strength ทุก frame
- ✅ Config file — แก้ค่าได้โดยไม่แตะโค้ด
- ✅ JSON-Lines log — 30 วัน + size cap อัตโนมัติ
- ✅ Systemd autostart — บูตขึ้นมาทำงานเอง
- ✅ VNC terminal popup — เห็น log ทันทีตอนเปิด VNC
- ✅ GPIO lgpio — รองรับ Raspberry Pi 5

---

*AMRT DEM DEV TEAM — KURURU2 Pilot Unit*
