#!/bin/bash
# fastboot_trial.sh — trial: stop the boot tone earlier (try on ONE unit before adding to install.sh)
#
#   sudo bash fastboot_trial.sh apply    # make the changes (then: sudo reboot)
#   sudo bash fastboot_trial.sh status   # check after reboot
#   sudo bash fastboot_trial.sh revert   # undo (then: sudo reboot)
#
# What it changes
#   (2) firmware stage : config.txt auto_initramfs=0 (skip loading initramfs from SD)
#                        + initial_turbo=30 (full CPU clock for the first 30 s)
#   (3) kernel stage   : Pi 4 only — dtoverlay=gpio-led on GPIO 23. The kernel LED driver
#                        drives GPIO 23 LOW as soon as it loads (about 1 s into the kernel),
#                        so the tone stops before systemd starts.
#                        safety_sense uses lgpio, which cannot claim a pin the kernel holds,
#                        so a drop-in runs safety-sense-buzzrelease before safety_sense starts
#                        to unbind that LED device and free the pin.
#
# If the unit does not boot after apply: put the SD card in a PC, open the "bootfs" drive and
# copy config.txt.before-fastboot over config.txt (or set auto_initramfs=1 and delete the
# lines between the "safety_sense fastboot" markers).
set -euo pipefail

ACTION="${1:-status}"
PIN=23
LABEL=ssbuzz
CFG=/boot/firmware/config.txt
[ -f "$CFG" ] || CFG=/boot/config.txt
BOOTDIR=$(dirname "$CFG")
STATE=/var/lib/safety_sense
FLAG="$STATE/fastboot_initramfs_changed"
HELPER=/usr/local/sbin/safety-sense-buzzrelease
DROPIN=/etc/systemd/system/safety_sense.service.d/10-buzzrelease.conf
MODEL=$(tr -d '\0' </proc/device-tree/model 2>/dev/null || echo unknown)
BEGIN="# >>> safety_sense fastboot (fastboot_trial.sh)"
END="# <<< safety_sense fastboot"

need_root() { [ "$(id -u)" -eq 0 ] || { echo "ต้องรันด้วย sudo"; exit 1; }; }
is_pi4() { case "$MODEL" in *"Raspberry Pi 4"*|*"Compute Module 4"*|*"Raspberry Pi 400"*) return 0;; esac; return 1; }
strip_block() { sed -i "/^# >>> safety_sense fastboot/,/^# <<< safety_sense fastboot/d" "$CFG"; }

do_apply() {
  need_root
  mkdir -p "$STATE"
  echo "เครื่อง: $MODEL"
  echo "config: $CFG"

  # Backup once (the FAT copy can be restored from a Windows PC if the unit will not boot)
  if [ ! -f "$BOOTDIR/config.txt.before-fastboot" ]; then
    cp -a "$CFG" "$BOOTDIR/config.txt.before-fastboot"
  fi
  cp -a "$CFG" "$STATE/config.txt.before-fastboot-$(date +%Y%m%d-%H%M%S)"
  echo "✓ สำรอง config.txt ไว้ที่ $BOOTDIR/config.txt.before-fastboot"

  # (2a) initramfs off
  if grep -q '^auto_initramfs=1' "$CFG"; then
    sed -i 's/^auto_initramfs=1/auto_initramfs=0/' "$CFG"
    touch "$FLAG"
    echo "✓ auto_initramfs=1 → 0"
  elif grep -q '^auto_initramfs=0' "$CFG"; then
    echo "✓ auto_initramfs=0 อยู่แล้ว"
  else
    echo "  (ไม่มีบรรทัด auto_initramfs ใน config.txt — ข้าม)"
  fi

  # (2b)+(3) block at the end of config.txt
  strip_block
  {
    echo "$BEGIN"
    echo "[all]"
    echo "initial_turbo=30"
    if is_pi4; then
      echo "dtoverlay=gpio-led,gpio=${PIN},label=${LABEL}"
    fi
    echo "$END"
  } >> "$CFG"
  echo "✓ เพิ่ม initial_turbo=30"
  if is_pi4; then
    echo "✓ เพิ่ม dtoverlay=gpio-led บน GPIO ${PIN} (kernel ปิดเสียงเอง)"
  else
    echo "  (ไม่ใช่ Pi 4 — ข้ามข้อ 3: kernel ปิดเสียง ยังไม่ได้ทดสอบบน Pi 5)"
  fi

  # Release helper: free GPIO 23 from the kernel LED driver so lgpio can claim it
  cat > "$HELPER" <<EOF
#!/bin/sh
L=/sys/class/leds/${LABEL}
if [ -e "\$L" ]; then
  echo 0 > "\$L/brightness" 2>/dev/null || true
  DRV=\$(readlink -f "\$L/device/driver")
  DEV=\$(basename "\$(readlink -f "\$L/device")")
  echo "\$DEV" > "\$DRV/unbind" 2>/dev/null || true
  if [ -e "\$L" ]; then
    echo "ERROR: GPIO ${PIN} still held by kernel LED driver (\$DEV)"
    exit 1
  fi
  echo "GPIO ${PIN} released from kernel LED driver (\$DEV) at uptime \$(cut -d' ' -f1 /proc/uptime)s"
fi
command -v pinctrl >/dev/null && pinctrl set ${PIN} op dl || true
exit 0
EOF
  chmod 755 "$HELPER"
  mkdir -p "$(dirname "$DROPIN")"
  cat > "$DROPIN" <<EOF
[Service]
ExecStartPre=$HELPER
EOF
  systemctl daemon-reload
  echo "✓ ติดตั้ง $HELPER + drop-in ให้ safety_sense"
  echo
  echo "ต่อไป: sudo reboot   (ถ้าไม่ ping กลับใน 2 นาที ให้กู้จาก SD ตามหัวไฟล์นี้)"
}

do_revert() {
  need_root
  strip_block
  if [ -f "$FLAG" ]; then
    sed -i 's/^auto_initramfs=0/auto_initramfs=1/' "$CFG"
    rm -f "$FLAG"
    echo "✓ auto_initramfs กลับเป็น 1"
  fi
  rm -f "$DROPIN" "$HELPER"
  rmdir --ignore-fail-on-non-empty "$(dirname "$DROPIN")" 2>/dev/null || true
  systemctl daemon-reload
  echo "✓ ถอดการทดลองแล้ว — ต่อไป: sudo reboot"
}

do_status() {
  echo "== เครื่อง";        hostname; echo "$MODEL"
  echo "== config.txt";     grep -nE '^auto_initramfs|^initial_turbo|gpio-led|^gpio=23' "$CFG" || true
  echo "== initramfs ถูกโหลดไหม (ว่าง = ไม่โหลด)"
  dmesg 2>/dev/null | grep -iE 'Trying to unpack rootfs|initramfs' | head -2 || true
  echo "== kernel LED (ต้องไม่เหลือ ${LABEL} หลัง safety_sense สตาร์ท)"
  ls /sys/class/leds/ | tr '\n' ' '; echo
  echo "== การปล่อยขา 23";  journalctl -b -u safety_sense --no-pager 2>/dev/null | grep -E 'released|still held|GPIO init' | tail -3 || true
  echo "== service";        systemctl is-active safety_sense; systemctl show safety_sense -p NRestarts
  echo "== ready";          journalctl -b -u safety_sense --no-pager 2>/dev/null | grep 'System ready' | tail -1 || true
  echo "== เวลาบูต";        systemd-analyze 2>/dev/null | head -1 || true
}

case "$ACTION" in
  apply)  do_apply ;;
  revert) do_revert ;;
  status) do_status ;;
  *) echo "ใช้: sudo bash $0 apply|status|revert"; exit 1 ;;
esac
