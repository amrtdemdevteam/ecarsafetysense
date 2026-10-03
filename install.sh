#!/bin/bash
set -Eeuo pipefail

INSTALL_DIR="/opt/safety_sense"
SERVICE_NAME="safety_sense"
LOG_DIR="/var/log/safety_sense"
AUTOSTART_DIR="/etc/xdg/autostart"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

print_config_summary() {
  local config_path="$1"
  "${PYTHON_BIN:-python3}" - "$config_path" <<'PY'
import json
import sys


def format_number(value):
    return f"{value:g}"


def print_row(label, value):
    print(f"{label:<26}: {value}")


with open(sys.argv[1], encoding="utf-8") as config_file:
    config = json.load(config_file)

zones = config["zones"]
buzzer = config["buzzer"]
clear = zones["clear_cm"]
far = zones["far_cm"]
mid = zones["mid_cm"]
near = zones["near_cm"]

print("Zone map (from config.json)")
print_row(f"> {format_number(clear)} cm", "CLEAR")

if clear == far:
    print_row("FAR", f"disabled (clear_cm == far_cm == {format_number(far)})")
else:
    print_row(f"> {format_number(far)} to <= {format_number(clear)} cm", "FAR")

if far == mid:
    print_row("MID", f"disabled (far_cm == mid_cm == {format_number(mid)})")
else:
    print_row(f"> {format_number(mid)} to <= {format_number(far)} cm", "MID")

if mid == near:
    print_row("NEAR", f"disabled (mid_cm == near_cm == {format_number(near)})")
else:
    print_row(f"> {format_number(near)} to <= {format_number(mid)} cm", "NEAR")

print_row(f"<= {format_number(near)} cm", "SOLID")
print()
print("Buzzer settings (from config.json)")
print_row("FAR anchor", f"{format_number(buzzer['freq_far_hz'])} Hz")
print_row("MID anchor", f"{format_number(buzzer['freq_mid_hz'])} Hz")
print_row("NEAR anchor", f"{format_number(buzzer['freq_near_hz'])} Hz")
print_row("Duty cycle", f"{format_number(buzzer['duty_cycle_pct'])}%")
PY
}

if [[ "${1:-}" == "--print-summary" ]]; then
  print_config_summary "${2:-$SCRIPT_DIR/config.json}"
  exit 0
fi

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   E-car Safety Sense — KURURU2  Installer   ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: กรุณารัน installer ด้วย sudo: sudo bash install.sh" >&2
  exit 1
fi

for source_file in safety_sense.py config.json safety_sense.service safety_sense_monitor.desktop; do
  if [[ ! -f "$SCRIPT_DIR/$source_file" ]]; then
    echo "ERROR: ไม่พบไฟล์ $SCRIPT_DIR/$source_file" >&2
    exit 1
  fi
done

UART_MARKER="/var/lib/safety_sense/uart-configured"

uart_ready() {
  [[ -e /dev/serial0 ]] || return 1
  if grep -Eq '(^| )console=(serial0|ttyS0|ttyAMA0)(,| |$)' /proc/cmdline; then
    return 1
  fi
  local uart_name
  uart_name="$(basename "$(readlink -f /dev/serial0)")"
  if systemctl is-active --quiet "serial-getty@${uart_name}.service"; then
    return 1
  fi
  return 0
}

current_boot_id() {
  cat /proc/sys/kernel/random/boot_id 2>/dev/null || echo "unknown"
}

ask_reboot() {
  echo ""
  echo "ต้อง reboot 1 ครั้งเพื่อให้การตั้งค่า UART มีผล"
  echo "หลัง reboot ให้รันคำสั่งเดิมอีกครั้ง:"
  echo "  cd $SCRIPT_DIR && sudo bash install.sh"
  echo ""
  if [[ -t 0 ]]; then
    read -r -p "Reboot ตอนนี้เลยไหม? [y/N] " answer
    if [[ "$answer" =~ ^[Yy]$ ]]; then
      echo "กำลัง reboot..."
      reboot
      exit 0
    fi
  fi
  echo "ยังไม่ได้ reboot — สั่งเองด้วย: sudo reboot"
  exit 0
}

echo "[1/7] ตรวจสอบ UART..."
if ! uart_ready; then
  if [[ -f "$UART_MARKER" ]]; then
    if [[ "$(cat "$UART_MARKER")" == "$(current_boot_id)" ]]; then
      echo "    ตั้งค่า UART ไปแล้ว แต่ยังไม่ได้ reboot"
      ask_reboot
    fi
    echo "ERROR: reboot แล้วแต่ UART ยังไม่พร้อม (/dev/serial0 หรือ serial console)" >&2
    echo "ตรวจด้วยมือ: sudo raspi-config" >&2
    echo "  Interface Options -> Serial Port" >&2
    echo "  Login shell over serial: No" >&2
    echo "  Serial hardware: Yes" >&2
    echo "จากนั้น reboot และรัน installer อีกครั้ง" >&2
    rm -f "$UART_MARKER"
    exit 1
  fi

  if ! command -v raspi-config >/dev/null 2>&1; then
    echo "ERROR: UART ยังไม่พร้อม และไม่พบ raspi-config ให้ตั้งค่าเอง" >&2
    echo "เปิด hardware UART และปิด serial login shell แล้ว reboot" >&2
    exit 1
  fi

  echo "    UART ยังไม่พร้อม — เปิด hardware UART และปิด serial login shell ให้อัตโนมัติ"
  raspi-config nonint do_serial_hw 0
  raspi-config nonint do_serial_cons 1
  mkdir -p "$(dirname "$UART_MARKER")"
  current_boot_id > "$UART_MARKER"
  echo "    ✓ raspi-config: serial hardware = on, serial console = off"
  ask_reboot
fi
rm -f "$UART_MARKER"

PI_MODEL="unknown"
if [[ -r /proc/device-tree/model ]]; then
  PI_MODEL="$(tr -d '\0' < /proc/device-tree/model)"
fi
UART_TARGET="$(readlink -f /dev/serial0)"

if [[ "$PI_MODEL" == *"Raspberry Pi 5"* && "$UART_TARGET" == "/dev/ttyAMA10" ]]; then
  echo "ERROR: /dev/serial0 ชี้ไปที่ Pi 5 debug header ไม่ใช่ GPIO14/15" >&2
  echo "เพิ่ม dtparam=uart0_console=on ใน config.txt ที่ระบบใช้งาน แล้ว reboot" >&2
  for config_file in /boot/firmware/config.txt /boot/config.txt; do
    if [[ -f "$config_file" ]]; then
      echo "  พบ config: $config_file" >&2
    fi
  done
  echo "จากนั้นตรวจ ls -l /dev/serial0 และรัน installer อีกครั้ง" >&2
  exit 1
fi

echo "    ✓ $PI_MODEL"
echo "    ✓ /dev/serial0 -> $UART_TARGET"

echo "[2/7] ติดตั้ง Python packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update
if ! apt-get install -y python3 python3-serial python3-lgpio; then
  echo "แพ็กเกจ OS ไม่พร้อม ใช้ pip fallback..."
  apt-get install -y python3 python3-pip python3-dev
  python3 -m pip install --break-system-packages pyserial lgpio
fi
python3 -c 'import serial, lgpio'
echo "    ✓ pyserial, lgpio"

echo "[3/7] สร้างโฟลเดอร์..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$LOG_DIR"
mkdir -p "$AUTOSTART_DIR"
echo "    ✓ $INSTALL_DIR"
echo "    ✓ $LOG_DIR"
echo "    ✓ $AUTOSTART_DIR"

echo "[4/7] คัดลอกไฟล์..."
cp "$SCRIPT_DIR/safety_sense.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/config.json"     "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/safety_sense.py"
echo "    ✓ safety_sense.py"
echo "    ✓ config.json"

echo "[5/7] ติดตั้ง desktop autostart (VNC monitor)..."
cp "$SCRIPT_DIR/safety_sense_monitor.desktop" "$AUTOSTART_DIR/"
echo "    ✓ safety_sense_monitor.desktop"

echo "[6/7] ลงทะเบียน systemd service..."
cp "$SCRIPT_DIR/safety_sense.service" /etc/systemd/system/
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
print_config_summary "$INSTALL_DIR/config.json"
echo ""
echo "แก้ค่า:  nano /opt/safety_sense/config.json"
echo "          systemctl restart safety_sense"
echo ""
echo "journalctl -u safety_sense -f   # ดู log realtime"
echo "systemctl status safety_sense   # ดูสถานะ"
echo ""
echo "🖥️  เปิด VNC → terminal popup ขึ้นอัตโนมัติตอนบูต"
