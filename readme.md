# E-car Safety Sense — KURURU2

ระบบแจ้งเตือนระยะใกล้สำหรับรถลากไฟฟ้า KURURU2 ในโกดัง  
ตรวจจับสิ่งกีดขวางด้านหน้าด้วย ToF LiDAR และแจ้งเตือนผู้ขับด้วย buzzer แบบรถยนต์ถอยจอด

---

## Hardware

| ชิ้นส่วน | รุ่น |
|---|---|
| Controller | Raspberry Pi 4 Model B (คัน 001 เท่านั้นที่เป็น Raspberry Pi 5) |
| Sensor | Benewake TFmini Plus or TF-NOVA (UART, standard 9-byte frame) |
| Buzzer | TEND TS2BCL7 24V (มีไฟ LED, 90 dB ขึ้นไป) ขับผ่าน MOSFET |
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
| STARTUP | ดังยาวตั้งแต่บิดกุญแจ แล้วหยุดเอง (Pi 4 ที่ตั้งค่าบูตเร็วครบ: ดังวินาทีที่ 2 หยุดวินาทีที่ 7) | ไฟเข้าและ buzzer ใช้งานได้ ระบบยังไม่พร้อม |
| READY | ปี๊บสั้น 1 ครั้ง | ระบบพร้อม (ได้ค่าจาก sensor ครั้งแรก) ออกรถได้ |

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
- copy ไฟล์ไปที่ `/opt/safety_sense/` (ถ้า `config.json` เดิมในเครื่องต่างจากใน repo จะสำรองไว้เป็น `config.json.bak-วันเวลา` ก่อนเขียนทับ)
- เสียงตอนเปิดเครื่อง (`startup.boot_tone_mode = from_power`): เพิ่ม `gpio=23=op,dh` ใน config.txt ให้ดังทันทีที่ไฟเข้า แล้ว `safety_sense_boottone.service` ปิดเสียงเร็วที่สุดที่ Linux ทำได้ (วัดจริงหลังตั้ง EEPROM: Pi 4 ดังวินาทีที่ 2 หยุดวินาทีที่ 11, Pi 5 คัน 001 ดังวินาทีที่ 4 หยุดวินาทีที่ 9) หรือเลือก `fixed` ให้ดังนาน `boot_tone_sec` พอดีแต่เริ่มดังช้ากว่าไฟเข้า มีผลหลัง reboot (ต้องมีคำสั่ง `pinctrl` จากแพ็กเกจ `raspi-utils`)
- ตั้ง EEPROM ให้บูตเร็ว (`NET_INSTALL_AT_POWER_ON=0`, `DISABLE_HDMI=1`, `BOOT_UART=0`) ถ้ายังไม่ได้ตั้ง และสำรองค่าเดิมไว้ที่ `/var/lib/safety_sense/` ปิดได้ด้วย `startup.fast_boot_eeprom = false` บน Pi 4 จะเขียน EEPROM ตอน reboot ครั้งถัดไป ห้ามตัดไฟระหว่าง reboot นั้น (คัน 001 Pi 5: เสียงเริ่มจากวินาทีที่ 9 เหลือ 4, คัน 003 Pi 4: จากวินาทีที่ 8 เหลือ 2)
- ลง systemd service (autostart + restart on crash)
- ลง VNC terminal monitor (popup log อัตโนมัติตอนบูต)

### บูตเร็วขึ้นอีก (ทดลอง, Pi 4 เท่านั้น)

`fastboot_trial.sh` ทำให้เสียงตอนเปิดเครื่องหยุดเร็วขึ้นอีก ยังไม่อยู่ใน `install.sh` ทดสอบแล้วบนคัน 003 วันที่ 2026-10-16: เสียงดังวินาทีที่ 2 หยุดวินาทีที่ 7 ปี๊บพร้อมวินาทีที่ 13 (ก่อนหน้า 2 / 11 / 15) และเสียงตามโซนยังทำงานปกติ

```bash
sudo bash fastboot_trial.sh apply    # แล้ว sudo reboot
sudo bash fastboot_trial.sh status   # หลัง reboot ต้องเห็น released และ GPIO init OK (lgpio)
sudo bash fastboot_trial.sh revert   # ถอดออก แล้ว sudo reboot
```

สิ่งที่สคริปต์ทำ:
- `auto_initramfs=0` ไม่โหลด initramfs จาก SD
- `initial_turbo=30` CPU ความเร็วสูงสุด 30 วินาทีแรก
- `dtoverlay=gpio-led,gpio=23,label=ssbuzz` ให้ kernel ปิดขา 23 เองเร็วกว่ารอ systemd (เฉพาะ Pi 4)
- `safety-sense-buzzrelease` (ExecStartPre ของ safety_sense) คืนขา 23 จาก kernel ให้ lgpio ก่อนโปรแกรมเริ่ม

สำรอง config.txt ไว้ที่ `/boot/firmware/config.txt.before-fastboot` ถ้าบูตไม่ขึ้น ให้เอา SD ไปเสียบคอม แล้วก๊อปไฟล์นี้ทับ `config.txt` ในไดรฟ์ bootfs

---

## ไฟล์ในโปรเจกต์

```
ecarsafetysense/
├── safety_sense.py              # โค้ดหลัก
├── config.json                  # ตั้งค่าทั้งหมด (แก้ที่นี่)
├── install.sh                   # ติดตั้งครั้งเดียวจบ
├── setup_wifi_time.sh           # Wi-Fi Auto_ECar + ซิงก์เวลา
├── fastboot_trial.sh            # ทดลองบูตเร็ว (Pi 4)
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
    "freq_mid_hz":  6.0
}
```

หลังแก้ค่า restart service:

```bash
sudo systemctl restart safety_sense
```

ถ้าแก้ค่าใน `/opt/safety_sense/config.json` ของคันใดคันหนึ่ง ค่านั้นจะถูกเขียนทับเมื่อรัน `install.sh` ครั้งถัดไป installer จะสำรองไฟล์เดิมไว้ให้ แต่ค่าที่ต้องการใช้ทุกคันควรแก้ใน `config.json` ของ repo

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

## ชื่อเครื่อง (hostname)

ทุกคันใช้รูปแบบชื่อเดียวกัน คือ `ecarsafetysense-NNN` โดย NNN เป็นหมายเลขคัน 3 หลัก ตั้งแต่ `001` ถึง `143`

| คัน | hostname |
|---|---|
| 1 | `ecarsafetysense-001` |
| 2 | `ecarsafetysense-002` |
| 3 | `ecarsafetysense-003` |
| ... | ... |
| 143 | `ecarsafetysense-143` |

ตั้งชื่อเครื่องบน Pi (รันครั้งเดียวต่อคัน แทน NNN ด้วยหมายเลขของคันนั้น):

```bash
sudo hostnamectl set-hostname ecarsafetysense-NNN
sudo sed -i 's/^127\.0\.1\.1.*/127.0.1.1\tecarsafetysense-NNN/' /etc/hosts
sudo reboot
```

หลัง reboot ตรวจด้วย `hostname` ต้องได้ชื่อใหม่ ถ้า `ecarsafetysense-NNN.local` ใช้ไม่ได้บน LAN ตรง ให้ใช้ IP ของเครื่องแทน

ชื่อผู้ใช้สำหรับ login ใช้รูปแบบเดียวกับ hostname คือ `ecarsafetysense-NNN` เช่น `ssh ecarsafetysense-002@192.168.0.12` รหัสผ่านไม่ต้องเปลี่ยน

IP ของ `eth0` บน LAN ตรงใช้รูปแบบ `192.168.0.(10+NNN)` คือ คัน 1 เป็น `192.168.0.11` คัน 2 เป็น `192.168.0.12` และคัน 3 เป็น `192.168.0.13`

การเปลี่ยนชื่อผู้ใช้บน Pi ที่ติดตั้งแล้วต้องทำแยกจากการตั้ง hostname ต้องเปลี่ยนไฟล์ sudo (`/etc/sudoers.d/`), autologin (`lightdm.conf` และ `getty@tty1`), `subuid`/`subgid` และย้ายโฟลเดอร์ home ไปพร้อมกัน

---

## Wi-Fi และเวลาเครื่อง

Raspberry Pi 4 ไม่มีนาฬิกาที่มีแบตเตอรี่ ถ้าตัดไฟ เวลาจะย้อนไปเป็นเวลาล่าสุดที่บันทึกไว้ ทำให้เวลาใน log ผิด ให้ตั้ง Wi-Fi `Auto_ECar` ไว้ทุกคัน เพื่อให้ Pi เชื่อมต่อเองและซิงก์เวลาจากอินเทอร์เน็ตทุกครั้งที่อยู่ในระยะ

```bash
cd ~/ecarsafetysense
sudo bash setup_wifi_time.sh
```

สคริปต์จะ
- ตั้งประเทศ Wi-Fi เป็น TH และเปิด Wi-Fi
- บันทึกโปรไฟล์ `Auto_ECar` แบบเชื่อมต่ออัตโนมัติ (รหัสผ่านอยู่ในสคริปต์)
- ติดตั้งตัวสแกน Wi-Fi ทุก 15 วินาทีขณะที่ยังไม่ได้เชื่อมต่อ
- เปิด NTP และสั่งซิงก์เวลาทันทีที่เชื่อม Wi-Fi ได้ (ข้าม eth0 และปลดเพดานการ restart ของ timesyncd ไม่ให้ค้างสถานะ failed ตอนบูต)

ทดสอบด้วย hotspot มือถือชื่อเดียวกัน: ใช้เวลาประมาณ 10 วินาทีตั้งแต่ Wi-Fi เข้าระยะจนเวลาเครื่องถูกต้อง ถ้าเปิดเครื่องนอกระยะ Wi-Fi เวลาจะยังผิดจนกว่าจะได้เชื่อมต่อ

รันซ้ำได้ ใช้กับ Wi-Fi อื่น: `sudo WIFI_PSK='รหัส' bash setup_wifi_time.sh ชื่อWiFi`

ตรวจสถานะ:

```bash
timedatectl | grep -E "Local time|synchronized"
iwgetid -r
```

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

ถ้า Pi ไม่มีอินเทอร์เน็ต (ต่อแค่สาย LAN) ให้คัดลอกโค้ดจากคอมแทน `git pull` แล้วรัน installer:

```bash
# บน Pi — เก็บโฟลเดอร์เดิมไว้ก่อน
mv ~/ecarsafetysense ~/ecarsafetysense-old
```

```cmd
:: บน Windows — NNN คือเลขคัน
scp -r C:\TPCAP_SAFETYSENSE\01_CODE\ecarsafetysense ecarsafetysense-NNN@192.168.0.(10+NNN):/home/ecarsafetysense-NNN/
```

```bash
# บน Pi
cd ~/ecarsafetysense && git log --oneline -1 && sudo bash install.sh
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
