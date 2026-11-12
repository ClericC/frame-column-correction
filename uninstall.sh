#!/bin/bash
# Copyright (c) 2026 ClericC - MIT License - https://github.com/ClericC/frame-column-correction
# Removes the Frame VCOM dashboard panel. The vcom-fix correction service keeps running;
# to remove it too:  sudo systemctl disable --now vcom-fix && sudo rm -r /etc/vcom-fix /etc/systemd/system/vcom-fix.service
systemctl --user stop frame-vcom 2>/dev/null || true
rm -f "$HOME/.local/share/applications/frame-vcom.desktop" "$HOME/.local/share/icons/hicolor/256x256/apps/frame-vcom.png"
rm -rf "$HOME/.local/lib/frame-vcom" "$HOME/.config/frame-vcom"
update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
echo "Column Correction panel removed (your settings in ~/vcom-fix/vcom.conf are kept)."
