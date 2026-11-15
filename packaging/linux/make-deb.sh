#!/usr/bin/env bash
# Build dist/synclayer-<version>-linux-<arch>.deb from dist/synclayer-gui (run after scripts/build.py).
set -euo pipefail
cd "$(dirname "$0")/../.."
VER=$(grep -oP '__version__\s*=\s*"\K[^"]+' synclayer/_version.py)
ARCH=$(dpkg --print-architecture)
PKG=build/deb/synclayer_${VER}_${ARCH}
rm -rf "$PKG" && mkdir -p "$PKG/DEBIAN" "$PKG/opt/synclayer" "$PKG/usr/bin" "$PKG/usr/share/applications" "$PKG/usr/share/icons/hicolor/256x256/apps"
install -m 755 dist/synclayer-gui "$PKG/opt/synclayer/synclayer-gui"
[ -f dist/synclayer ] && install -m 755 dist/synclayer "$PKG/opt/synclayer/synclayer"
ln -s /opt/synclayer/synclayer-gui "$PKG/usr/bin/synclayer-gui"
[ -f dist/synclayer ] && ln -s /opt/synclayer/synclayer "$PKG/usr/bin/synclayer"
QT_QPA_PLATFORM=offscreen python - <<PY
import sys
from PySide6.QtGui import QGuiApplication
app = QGuiApplication(sys.argv[:1])
from synclayer.gui import icon
open("$PKG/usr/share/icons/hicolor/256x256/apps/synclayer.png", "wb").write(icon.png_bytes(256))
PY
cat > "$PKG/usr/share/applications/synclayer.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Synclayer
Comment=Your personal cloud drive, synced with your devices
Exec=/opt/synclayer/synclayer-gui
Icon=synclayer
Categories=Network;FileTransfer;
StartupWMClass=synclayer
Terminal=false
DESK
cat > "$PKG/DEBIAN/control" <<CTL
Package: synclayer
Version: $VER
Section: net
Priority: optional
Architecture: $ARCH
Maintainer: Synclayer <noreply@example.com>
Description: Synclayer desktop app
 Sync folders with your own Synclayer server, or a friend's. Point it at any server on first launch.
CTL
dpkg-deb --root-owner-group --build "$PKG" "dist/synclayer-${VER}-linux-$(uname -m | sed 's/x86_64/x64/;s/aarch64/arm64/').deb"
