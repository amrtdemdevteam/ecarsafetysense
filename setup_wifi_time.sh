#!/bin/bash
# Join a Wi-Fi network automatically and sync the clock from the internet whenever it is in range.
# Pi 4 has no battery clock, so without this the time goes back after every power cut.
#
# Usage:  sudo bash setup_wifi_time.sh
# Default network is Auto_ECar with its password below. Another network:
#   sudo WIFI_PSK='password' bash setup_wifi_time.sh OtherSSID
set -euo pipefail

SSID="${1:-Auto_ECar}"
DEFAULT_PSK='1234@abcdE'
if [[ "$SSID" == "Auto_ECar" ]]; then
  PSK="${WIFI_PSK:-$DEFAULT_PSK}"
else
  PSK="${WIFI_PSK:-}"
fi
COUNTRY="${WIFI_COUNTRY:-TH}"

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: run with sudo" >&2
  exit 1
fi

echo "[1/6] Wi-Fi country ${COUNTRY}, radio on"
raspi-config nonint do_wifi_country "$COUNTRY" >/dev/null 2>&1 || true
rfkill unblock wifi || true
nmcli radio wifi on

echo "[2/6] Wi-Fi profile ${SSID}"
if [[ -z "$PSK" ]]; then
  read -r -s -p "    Wi-Fi password for ${SSID}: " PSK
  echo
fi
if nmcli -t -f NAME con show | grep -Fxq "$SSID"; then
  echo "    profile already saved, updating password"
  nmcli con mod "$SSID" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PSK"
else
  nmcli con add type wifi ifname wlan0 con-name "$SSID" ssid "$SSID" \
    wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PSK" \
    ipv4.method auto ipv6.method auto >/dev/null
fi
unset PSK
# Reconnect forever when in range. Higher metric than eth0 so the direct LAN stays as it is.
nmcli con mod "$SSID" connection.autoconnect yes connection.autoconnect-retries 0 ipv4.route-metric 600

echo "[3/6] Scan for ${SSID} every 15 s while not connected"
cat > /usr/local/sbin/safety-sense-wifi-scan <<EOF
#!/bin/sh
# Installed by setup_wifi_time.sh. Only acts while wlan0 is not connected.
SSID="${SSID}"
EOF
cat >> /usr/local/sbin/safety-sense-wifi-scan <<'EOF'
STATE=$(nmcli -t -f DEVICE,STATE dev | awk -F: '$1=="wlan0"{print $2}')
# Leave it alone while connected or while NetworkManager is already connecting.
case "$STATE" in connected*|connecting*|deactivating*) exit 0 ;; esac
nmcli dev wifi rescan ifname wlan0 >/dev/null 2>&1 || true
sleep 4
# The rescan often lets NetworkManager connect on its own. Check again before forcing it.
STATE=$(nmcli -t -f DEVICE,STATE dev | awk -F: '$1=="wlan0"{print $2}')
case "$STATE" in connected*|connecting*|deactivating*) exit 0 ;; esac
if nmcli -t -f SSID dev wifi list ifname wlan0 --rescan no 2>/dev/null | grep -Fxq "$SSID"; then
  nmcli --wait 20 con up "$SSID" >/dev/null 2>&1 || true
fi
exit 0
EOF
chmod 755 /usr/local/sbin/safety-sense-wifi-scan
cat > /etc/systemd/system/safety-sense-wifi-scan.service <<'EOF'
[Unit]
Description=SafetySense Wi-Fi scan while disconnected
After=NetworkManager.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/safety-sense-wifi-scan
EOF
cat > /etc/systemd/system/safety-sense-wifi-scan.timer <<'EOF'
[Unit]
Description=SafetySense Wi-Fi scan every 15 s while disconnected

[Timer]
OnBootSec=20
OnUnitActiveSec=15
AccuracySec=1s

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now safety-sense-wifi-scan.timer >/dev/null

echo "[4/6] Time sync on"
mkdir -p /etc/systemd/timesyncd.conf.d
cat > /etc/systemd/timesyncd.conf.d/safety_sense.conf <<'EOF'
[Time]
NTP=time.google.com th.pool.ntp.org
FallbackNTP=pool.ntp.org time.cloudflare.com
EOF
# Sync right away each time a network comes up, instead of waiting for the next poll.
cat > /etc/NetworkManager/dispatcher.d/90-safety-sense-timesync <<'EOF'
#!/bin/sh
case "$2" in
  up|connectivity-change) systemctl restart systemd-timesyncd ;;
esac
EOF
chmod 755 /etc/NetworkManager/dispatcher.d/90-safety-sense-timesync
timedatectl set-timezone Asia/Bangkok
timedatectl set-ntp true
systemctl restart systemd-timesyncd

echo "[5/6] Connect now"
if nmcli con up "$SSID" >/dev/null 2>&1; then
  echo "    connected to ${SSID}"
else
  echo "    ${SSID} not in range now; it will connect automatically later"
fi

echo "[6/6] Status (waiting 15 s for time sync)"
sleep 15
ip -br addr show wlan0 || true
timedatectl | grep -E "Local time|synchronized|NTP service"
