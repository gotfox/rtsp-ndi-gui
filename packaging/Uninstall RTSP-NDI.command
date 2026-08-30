#!/usr/bin/env bash
# Double-click launcher for uninstall.sh — see "Install RTSP-NDI.command"
# for why macOS will warn about this the first time.
set -e
echo "Uninstalling rtsp-ndi..."
curl -fsSL https://raw.githubusercontent.com/gotfox/rtsp-ndi/main/uninstall.sh | bash
echo ""
read -n 1 -s -r -p "Press any key to close this window..."
