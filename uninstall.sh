#!/usr/bin/env bash
set -e

# ── rtsp-ndi uninstaller ──────────────────────────────────────────────────────
# Reverses everything install.sh sets up: the launchd service, the pipx
# install (CLI + GUI + one-off bridge), the RTSP-NDI.app bundle, and the
# ~/.local/bin PATH line it added to your shell rc.
#
# Homebrew, pyenv, and the Python/FFmpeg/Tcl-Tk packages they installed are
# left alone on purpose — other things on your system may depend on them.
#
# Your camera config and logs are kept by default. To remove those too:
#   RTSP_NDI_PURGE=1 bash uninstall.sh

PACKAGE="rtsp-ndi"
PURGE="${RTSP_NDI_PURGE:-}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() { echo -e "${GREEN}==>${NC} $1"; }
warn() { echo -e "${YELLOW}Warning:${NC} $1"; }

# ── stop and remove the launchd service ───────────────────────────────────────
PLIST="$HOME/Library/LaunchAgents/com.rtsp-ndi.plist"
if [[ -f "$PLIST" ]]; then
    info "Stopping and removing the launchd service..."
    launchctl unload -w "$PLIST" &>/dev/null || launchctl stop com.rtsp-ndi &>/dev/null || true
    rm -f "$PLIST"
else
    info "No launchd service found."
fi

# ── remove the RTSP-NDI.app bundle ────────────────────────────────────────────
APP_DIR="$HOME/Applications/RTSP-NDI.app"
if [[ -d "$APP_DIR" ]]; then
    info "Removing $APP_DIR..."
    rm -rf "$APP_DIR"
else
    info "No RTSP-NDI.app found in ~/Applications."
fi

# ── uninstall the pipx package ────────────────────────────────────────────────
# Find whichever pipx installed rtsp-ndi — try the pyenv Python install.sh
# uses first, then whatever pipx/python3 is already on PATH.
find_pipx() {
    for py in \
        "$HOME/.pyenv/versions/3.12.10/bin/python3.12" \
        "$(command -v python3 2>/dev/null)"; do
        if [[ -x "$py" ]] && "$py" -m pipx --version &>/dev/null; then
            echo "$py -m pipx"
            return 0
        fi
    done
    if command -v pipx &>/dev/null; then
        echo "pipx"
        return 0
    fi
    return 1
}

if PIPX_CMD=$(find_pipx); then
    if $PIPX_CMD list 2>/dev/null | grep -q "$PACKAGE"; then
        info "Uninstalling $PACKAGE via pipx..."
        $PIPX_CMD uninstall "$PACKAGE" || warn "pipx uninstall reported an error — it may already be gone."
    else
        info "$PACKAGE is not installed via pipx."
    fi
else
    warn "Could not find pipx — skipping package uninstall. If 'rtsp-ndi'/'rtsp-ndi-gui' commands still work, remove them manually from ~/.local/bin."
fi

# ── remove the PATH line install.sh added ─────────────────────────────────────
LOCAL_BIN="$HOME/.local/bin"
for rc in "$HOME/.zshrc" "$HOME/.bashrc"; do
    if [[ -f "$rc" ]] && grep -qF "export PATH=\"$LOCAL_BIN:\$PATH\"" "$rc"; then
        info "Removing the PATH line install.sh added to $rc..."
        # Portable in-place edit for both BSD (macOS) and GNU sed.
        sed -i.bak "\#export PATH=\"$LOCAL_BIN:\$PATH\"#d" "$rc" && rm -f "$rc.bak"
    fi
done

# ── optionally purge config and logs ──────────────────────────────────────────
CONFIG_DIR="$HOME/.config/rtsp-ndi"
LOG_DIR="$HOME/Library/Logs/rtsp-ndi"
if [[ -n "$PURGE" ]]; then
    info "Removing config and logs (RTSP_NDI_PURGE was set)..."
    rm -rf "$CONFIG_DIR" "$LOG_DIR"
else
    if [[ -d "$CONFIG_DIR" || -d "$LOG_DIR" ]]; then
        info "Keeping your camera config and logs:"
        [[ -d "$CONFIG_DIR" ]] && echo "    $CONFIG_DIR"
        [[ -d "$LOG_DIR" ]] && echo "    $LOG_DIR"
        echo "  Re-run with RTSP_NDI_PURGE=1 bash uninstall.sh to remove those too."
    fi
fi

# ── done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}✓ rtsp-ndi uninstalled.${NC}"
echo ""
echo "Left untouched (shared with other apps, so not removed automatically):"
echo "  Homebrew, pyenv, the pyenv-installed Python, FFmpeg, Tcl/Tk"
echo ""
echo "Restart your terminal (or open a new tab) to pick up the PATH change."
