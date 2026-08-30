#!/usr/bin/env bash
# Double-click launcher for install.sh — lets you install rtsp-ndi from
# Finder without opening Terminal and typing a command yourself.
#
# macOS will likely warn that this is from an unidentified developer the
# first time (it's not code-signed/notarized) — right-click this file and
# choose "Open" instead of double-clicking to get past that once.
#
# This just runs the real installer from the repo, so it always installs
# whatever is currently on `main` — it doesn't duplicate install.sh's logic.
set -e
echo "Installing rtsp-ndi..."
curl -fsSL https://raw.githubusercontent.com/gotfox/rtsp-ndi/main/install.sh | bash
echo ""
read -n 1 -s -r -p "Press any key to close this window..."
