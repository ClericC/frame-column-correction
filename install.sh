#!/bin/bash
# Copyright (c) 2026 ClericC - MIT License - https://github.com/ClericC/frame-column-correction
# Frame VCOM installer: the vcom-fix correction service (root) + the SteamVR dashboard app (user).
#   tar -xzf frame-column-correction.tar.gz && sudo bash frame-column-correction/install.sh
# Settings already in /home/steamos/vcom-fix/vcom.conf are kept.
set -euo pipefail
R="${VCOM_TEST_ROOT:-}"                     # only for testing in a fake root
SRC="$(cd "$(dirname "$0")" && pwd)"
U=steamos
HOMED="$R/home/$U"
[ -n "$R" ] || [ "$(id -u)" = 0 ] || { echo "Run with sudo: sudo bash $0"; exit 1; }
[ -n "$R" ] || [ "$(uname -m)" = aarch64 ] || { echo "This is for the Steam Frame only"; exit 1; }
[ -n "$R" ] || command -v python3 >/dev/null || { echo "python3 not found"; exit 1; }

# 1. correction service: script in /etc (root only), settings in the user's home
mkdir -p "$R/etc/vcom-fix" "$HOMED/vcom-fix"
install -m 0755 "$SRC/vcomd.sh" "$R/etc/vcom-fix/vcomd.sh"
CONF="$HOMED/vcom-fix/vcom.conf"
NEW_CONF=0
if [ ! -f "$CONF" ]; then   # new install: neutral values, correction off until calibrated for this headset
  printf '%s\n' "# Column Correction settings (edited by the dashboard app). Offsets are steps above each display's factory VCOM." \
    COLD_TEMP=34 COLD_LEFT=0 COLD_RIGHT=0 HOT_TEMP=52 HOT_LEFT=0 HOT_RIGHT=0 LAG_MIN=22 LEFT_TRIM=0 RIGHT_TRIM=0 ENABLED=0 > "$CONF"
  NEW_CONF=1
fi
for k in LEFT_TRIM RIGHT_TRIM; do grep -q "^$k=" "$CONF" || echo "$k=0" >> "$CONF"; done
[ -f "$HOMED/vcom-fix/vcomd.sh" ] && mv -f "$HOMED/vcom-fix/vcomd.sh" "$HOMED/vcom-fix/vcomd.sh.old"
cat > "$R/etc/systemd/system/vcom-fix.service" <<'UNIT'
[Unit]
Description=Steam Frame display VCOM correction
After=multi-user.target
[Service]
ExecStart=/bin/bash /etc/vcom-fix/vcomd.sh
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT

# 2. dashboard app, for the user only
LIB="$HOMED/.local/lib/frame-vcom"
APPS="$HOMED/.local/share/applications"
ICONS="$HOMED/.local/share/icons/hicolor"
rm -rf "$LIB.new" && mkdir -p "$LIB.new" "$APPS" "$ICONS/256x256/apps"
for f in frame_vcom.py glyphs.bin glyphs.json icon.png LICENSE FONT-LICENSE.txt LICENSE.openvr uninstall.sh README.md CHANGELOG.md VERSION; do
  cp "$SRC/$f" "$LIB.new/"
done
rm -rf "$LIB" && mv "$LIB.new" "$LIB"
cp "$SRC/icon256.png" "$ICONS/256x256/apps/frame-vcom.png"
touch "$ICONS"
cat > "$APPS/frame-vcom.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Column Correction
Name[ru]=Коррекция столбцов
Comment=Column correction for the Steam Frame displays (VCOM)
Comment[ru]=Коррекция столбцов дисплеев Steam Frame (VCOM)
Comment[de]=Spaltenkorrektur für die Displays des Steam Frame (VCOM)
Exec=/usr/bin/systemd-run --user --collect --quiet --unit=frame-vcom /usr/bin/python3 -I /home/$U/.local/lib/frame-vcom/frame_vcom.py
Icon=frame-vcom
Terminal=false
Categories=Utility;
OnlyShowIn=gamescope;
DESKTOP
chown -R "$U:$U" "$HOMED/vcom-fix" "$LIB" "$APPS/frame-vcom.desktop" "$ICONS/256x256/apps/frame-vcom.png" 2>/dev/null || [ -n "$R" ]

if [ -z "$R" ]; then
  sudo -u "$U" update-desktop-database "$APPS" >/dev/null 2>&1 || true
  systemctl daemon-reload
  systemctl enable vcom-fix >/dev/null 2>&1
  systemctl restart vcom-fix
  sleep 3
  echo "vcom-fix: $(systemctl is-active vcom-fix)"
  cat /run/vcom-fix.state 2>/dev/null | tr '\n' ' '; echo
fi
echo
echo "Column Correction $(cat "$SRC/VERSION") installed."
echo "Open it from the SteamVR dashboard: + > Column Correction / Коррекция столбцов (a renamed entry can need a headset restart)."
echo "Remove the app: bash ~/.local/lib/frame-vcom/uninstall.sh"
if [ $NEW_CONF = 1 ]; then
  echo
  echo "The correction is OFF until you calibrate it for this headset: see README.md (cold point, then hot point)."
  echo "Коррекция выключена, пока вы не откалибруете её под свой шлем: см. README.md (холодная, затем горячая точка)."
  echo "Die Korrektur ist AUS, bis Sie sie für dieses Headset kalibrieren: siehe README.md (Kaltpunkt, dann Warmpunkt)."
fi
