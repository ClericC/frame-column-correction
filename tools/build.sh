#!/bin/sh
# Copyright (c) 2026 ClericC - MIT License - https://github.com/ClericC/frame-column-correction
# Build the release archive frame-column-correction.tar.gz from the files in this repository.
#   tools/build.sh            (run from anywhere; output in dist/)
# The glyph files are pre-rendered with tools/make_assets.py (needs Python + Pillow + DejaVu fonts).
set -eu
cd "$(dirname "$0")/.."
name=frame-column-correction
rm -rf dist && mkdir -p "dist/$name"
cp frame_vcom.py vcomd.sh install.sh uninstall.sh glyphs.bin glyphs.json icon.png icon256.png \
   README.md CHANGELOG.md VERSION LICENSE LICENSE.openvr FONT-LICENSE.txt "dist/$name/"
tar -C dist -czf "dist/$name.tar.gz" "$name"
(cd dist && sha256sum "$name.tar.gz" > "$name.tar.gz.sha256")
echo "dist/$name.tar.gz ($(cat VERSION))"
