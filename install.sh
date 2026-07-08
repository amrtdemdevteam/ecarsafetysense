#!/bin/bash
set -e

INSTALL_DIR="/opt/safety_sense"
SERVICE_NAME="safety_sense"
LOG_DIR="/var/log/safety_sense"

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   E-car Safety Sense — KURURU2  Installer   ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

echo "[1/6] ตรวจสอบ UART..."
if ! ls /dev/ttyAMA0 &>/dev/null; then
  echo "⚠️  ไม่พบ /dev/ttyAMA0"
  exit 1
fi
echo "    ✓ /dev/ttyAMA0 พร้อม"

echo "[2/6] ติดตั้ง Python packages..."
pip install pyserial lgpio --break-system-packages --quiet
echo "    ✓ pyserial, lgpio"

echo "[3/6] สร้างโฟลเดอร์..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$LOG_DIR"
echo "    ✓ $INSTALL_DIR"
echo "    ✓ $LOG_DIR"

echo "[4/6] คัดลอกไฟล์..."
cp safety_sense.py "$INSTALL_DIR/"
cp config.json     "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/safety_sense.py"
echo "    ✓ safety_sense.py"
echo "    ✓ config.json"

echo "[5/6] ลงทะเบียน systemd service..."
cp safety_sense.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
echo "    ✓ service enabled + started"

echo "[6/6] ตรวจสอบสถานะ..."
sleep 2
systemctl status "$SERVICE_NAME" --no-pager -l

echo ""
echo "✅ ติดตั้งเสร็จแล้ว"
echo ""
echo "  journalctl -u safety_sense -f   # ดู log realtime"
echo "  systemctl status safety_sense   # ดูสถานะ"
