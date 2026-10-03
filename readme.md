# E-car Safety Sense — KURURU2

ระบบแจ้งเตือนระยะใกล้สำหรับรถลากไฟฟ้า KURURU2 ในโกดัง  
ตรวจจับสิ่งกีดขวางด้านหน้าด้วย ToF LiDAR และแจ้งเตือนผู้ขับด้วย buzzer แบบรถยนต์ถอยจอด

---

## Hardware

| ชิ้นส่วน | รุ่น |
|---|---|
| Controller | Raspberry Pi 4 หรือ Raspberry Pi 5 |
| Sensor | Benewake TFmini Plus or TF-NOVA (UART, standard 9-byte frame) |
| Buzzer | Active piezo 95dB 3–24V via MOSFET |
| GPIO library | lgpio (รองรับ Raspberry Pi 4 และ Raspberry Pi 5) |

### การต่อขา

```
Benewake sensor TX  →  GPIO15 (RPi RX)
Benewake sensor RX  →  GPIO14 (RPi TX)
Benewake sensor VCC →  5V
Benewake sensor GND →  GND

The runtime supports `sensor.profile=auto` for the common Benewake 9-byte UART
protocol. TFmini Plus and TF-NOVA are not distinguished by guessing from a
distance value; the service requests standard 9-byte/cm output at startup so a
previous 9-byte/mm setting does not silently turn a close target into CLEAR.
The connector pinout and physical wiring must still be verified for the sensor
installed on the vehicle.

MOSFET Gate     →  GPIO23
Buzzer (+)      →  24V (ผ่าน MOSFET)
Buzzer (-)      →  GND
```

---

## Zone Map

```
ระยะ (cm)     Zone     Buzzer
> 200         CLEAR    เงียบ
155 – 200     FAR      beep 2 Hz
105 – 155     MID      beep 6 Hz
NEAR          disabled (mid_cm == near_cm == 105)
≤ 105         SOLID    buzz ต่อเนื่อง
```

ค่า zone และความถี่อ่านจาก `config.json`; ตารางนี้ตรงกับค่า default ปัจจุบัน

### Alert พิเศษ

| สถานะ | Pattern | ความหมาย |
|---|---|---|
| SENSOR_WARN | beep-beep ... หยุด | เลนส์สกปรก / สัญญาณอ่อน |
| SENSOR_FAIL | beep-beep-beep ... หยุด | sensor ไม่ส่งข้อมูล (ขาด / พัง) |

---

## ติดตั้ง

### ติดตั้งระบบ

รองรับ Raspberry Pi 4 และ Raspberry Pi 5 ด้วย codebase เดียว บน Pi ใหม่ใช้คำสั่งเดียว:

```bash
git clone https://github.com/amrtdemdevteam/ecarsafetysense.git
cd ecarsafetysense
sudo bash install.sh
```

ถ้า UART ยังไม่พร้อม installer จะเปิด hardware UART และปิด serial login shell ให้เอง (`raspi-config nonint`) แล้วขอให้ reboot 1 ครั้ง หลัง reboot ให้รันคำสั่งเดิมอีกครั้ง:

```bash
cd ecarsafetysense
sudo bash install.sh
```

รันซ้ำได้ทุกเมื่อ (เช่น ตอนอัปเดตโค้ด) installer จะข้ามขั้นที่เสร็จแล้วและติดตั้งไฟล์ล่าสุดทับ

บน Raspberry Pi 5 บาง configuration, `serial0` อาจชี้ไปที่ dedicated debug header หาก installer ตรวจพบกรณีนี้ มันจะหยุดก่อนติดตั้งและแสดง config path ที่มีอยู่ ให้เพิ่ม `dtparam=uart0_console=on` ในไฟล์นั้นแล้ว reboot เพื่อ map `serial0` มาที่ GPIO14/15

เมื่อ UART พร้อมแล้ว `install.sh` จะ:
- ติดตั้ง Python packages (`python3-serial`, `python3-lgpio`)
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
"uart": {
    "port": "/dev/serial0",
    "baud": 115200
},
"pins": {
    "buzzer": 23
}
```

```json
"zones": {
    "clear_cm": 200,   ← เริ่ม beep ที่ระยะนี้
    "far_cm":   155,   ← เปลี่ยน zone FAR → MID
    "mid_cm":   105,
    "near_cm":  105    ← ต่ำกว่าค่านี้เป็น SOLID
},
"buzzer": {
    "freq_far_hz":  2.0,
    "freq_mid_hz":  6.0,
    "freq_near_hz": 6.0,
    "duty_cycle_pct": 50
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

ตอนเริ่มทำงาน journal จะแสดง Raspberry Pi model, configured UART path, resolved UART target และ buzzer GPIO

### Troubleshooting: ไม่พบ `/dev/serial0`

```bash
ls -l /dev/serial0
sudo raspi-config
sudo journalctl -u safety_sense -b --no-pager
```

ตั้ง `Login shell over serial: No` และ `Serial hardware: Yes` แล้ว reboot ตรวจสาย TFmini Plus TX → GPIO15, RX → GPIO14 และ GND ร่วมกัน บน Pi 5 ให้ทำตามข้อความของ installer หาก `serial0` ยังชี้ไปที่ debug header และอย่าใช้ overlay แบบเก่าที่ผูกกับ Pi 5 รุ่นเดียว

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

- ✅ Car-style proximity beep — ความถี่คงที่ตาม zone ที่กำหนดใน config
- ✅ Watchdog timer — ตรวจจับ sensor หาย/ตาย
- ✅ Sensor health check — ตรวจ signal strength ทุก frame
- ✅ Config file — แก้ค่าได้โดยไม่แตะโค้ด
- ✅ JSON-Lines log — 30 วัน + size cap อัตโนมัติ
- ✅ Systemd autostart — บูตขึ้นมาทำงานเอง
- ✅ VNC terminal popup — เห็น log ทันทีตอนเปิด VNC
- ✅ GPIO lgpio — รองรับ Raspberry Pi 4 และ Raspberry Pi 5

---

*AMRT DEM DEV TEAM — KURURU2 Pilot Unit*
