#!/bin/bash
set -e

INSTALL_DIR="/opt/safety_sense"
SERVICE_NAME="safety_sense"
LOG_DIR="/var/log/safety_sense"
AUTOSTART_DIR="/etc/xdg/autostart"

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   E-car Safety Sense — KURURU2  Installer   ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

echo "[1/7] ตรวจสอบ UART..."
if ! ls /dev/ttyAMA0 &>/dev/null; then
  echo "⚠️  ไม่พบ /dev/ttyAMA0"
  echo "    → sudo raspi-config"
  echo "       Interface Options → Serial Port"
  echo "       Login shell: No  |  Hardware enabled: Yes  → Reboot"
  exit 1
fi
echo "    ✓ /dev/ttyAMA0 พร้อม"

echo "[2/7] ติดตั้ง Python packages..."
pip install pyserial lgpio --break-system-packages --quiet
echo "    ✓ pyserial, lgpio"

echo "[3/7] สร้างโฟลเดอร์..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$LOG_DIR"
mkdir -p "$AUTOSTART_DIR"
echo "    ✓ $INSTALL_DIR"
echo "    ✓ $LOG_DIR"
echo "    ✓ $AUTOSTART_DIR"

echo "[4/7] คัดลอกไฟล์..."
cp safety_sense.py "$INSTALL_DIR/"
cp config.json     "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/safety_sense.py"
echo "    ✓ safety_sense.py"
echo "    ✓ config.json"

echo "[5/7] ติดตั้ง desktop autostart (VNC monitor)..."
cp safety_sense_monitor.desktop "$AUTOSTART_DIR/"
echo "    ✓ safety_sense_monitor.desktop"

echo "[6/7] ลงทะเบียน systemd service..."
cp safety_sense.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
echo "    ✓ service enabled + started"

echo "[7/7] ตรวจสอบสถานะ..."
sleep 2
systemctl status "$SERVICE_NAME" --no-pager -l

echo ""
echo "✅ ติดตั้งเสร็จแล้ว"
echo ""
echo "┌──────────────────────────────────────────────────────────┐"
echo "│  Zone map (default)                                      │"
echo "│  > 200 cm  : CLEAR  — เงียบ                              │"
echo "│  150–200   : FAR    — beep เบา (1 Hz)                    │"
echo "│  100–150   : MID    — beep กลาง (→ 3 Hz)                 │"
echo "│   50–100   : NEAR   — beep ถี่ (→ 8 Hz)                  │"
echo "│  < 50 cm   : SOLID  — buzz ต่อเนื่อง                      │"
echo "│                                                          │"
echo "│  แก้ค่า:  nano /opt/safety_sense/config.json             │"
echo "│           systemctl restart safety_sense                 │"
echo "│                                                          │"
echo "│  journalctl -u safety_sense -f   # ดู log realtime       │"
echo "│  systemctl status safety_sense   # ดูสถานะ               │"
echo "│                                                          │"
echo "│  🖥️  เปิด VNC → terminal popup ขึ้นอัตโนมัติตอนบูต        │"
echo "└──────────────────────────────────────────────────────────┘"
