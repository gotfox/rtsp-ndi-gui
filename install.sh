#!/usr/bin/env bash
set -e

# ── rtsp-ndi installer ────────────────────────────────────────────────────────
# Installs rtsp-ndi and all dependencies, working around the broken
# Homebrew Python on macOS 26 (Tahoe) by using pyenv when necessary.

PYTHON_VERSION="3.12.10"
PACKAGE="rtsp-ndi"

# The "rtsp-ndi" name on PyPI is a separate, manually-published artifact
# this fork doesn't control, so by default we install straight from this
# repo's main branch — that's the only way "run install.sh" reliably gets
# what's actually in this repo. Override RTSP_NDI_SOURCE to point at a
# different branch/commit, a local checkout, or PyPI explicitly, e.g.:
#   RTSP_NDI_SOURCE="git+https://github.com/gotfox/rtsp-ndi@my-branch" bash install.sh
#   RTSP_NDI_SOURCE="/path/to/local/checkout" bash install.sh
#   RTSP_NDI_SOURCE="rtsp-ndi" bash install.sh   # explicitly use PyPI
DEFAULT_SOURCE="git+https://github.com/gotfox/rtsp-ndi@main"
SOURCE="${RTSP_NDI_SOURCE:-$DEFAULT_SOURCE}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()    { echo -e "${GREEN}==>${NC} $1"; }
warn()    { echo -e "${YELLOW}Warning:${NC} $1"; }
die()     { echo -e "${RED}Error:${NC} $1"; exit 1; }

# ── check for Homebrew ────────────────────────────────────────────────────────
if ! command -v brew &>/dev/null; then
    info "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

    # Add Homebrew to PATH for the rest of this script
    if [[ -x "/opt/homebrew/bin/brew" ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -x "/usr/local/bin/brew" ]]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi

    # Persist Homebrew in shell config
    SHELL_RC=""
    if [[ "$SHELL" == */zsh ]]; then SHELL_RC="$HOME/.zshrc"
    elif [[ "$SHELL" == */bash ]]; then SHELL_RC="$HOME/.bashrc"; fi
    if [[ -n "$SHELL_RC" ]] && ! grep -q "brew shellenv" "$SHELL_RC" 2>/dev/null; then
        echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> "$SHELL_RC"
    fi
else
    info "Homebrew already installed."
fi

# ── check for FFmpeg ──────────────────────────────────────────────────────────
if ! command -v ffmpeg &>/dev/null; then
    info "Installing FFmpeg..."
    brew install ffmpeg
else
    info "FFmpeg already installed."
fi

# ── check for Tcl/Tk (needed by the GUI's tkinter module) ────────────────────
if ! brew list tcl-tk &>/dev/null; then
    info "Installing Tcl/Tk (required for the GUI)..."
    brew install tcl-tk
else
    info "Tcl/Tk already installed."
fi
TCLTK_PREFIX="$(brew --prefix tcl-tk 2>/dev/null || true)"

# ── find a working Python 3.12 (with tkinter for the GUI) ────────────────────
find_working_python() {
    for py in \
        "$HOME/.pyenv/versions/$PYTHON_VERSION/bin/python3.12" \
        "$(brew --prefix python@3.12 2>/dev/null)/bin/python3.12" \
        "$(command -v python3.12 2>/dev/null)"; do
        if [[ -x "$py" ]] && "$py" -c "import xml.parsers.expat" &>/dev/null; then
            echo "$py"
            return 0
        fi
    done
    return 1
}

PYTHON=$(find_working_python || true)
PYENV_PYTHON="$HOME/.pyenv/versions/$PYTHON_VERSION/bin/python3.12"

if [[ -z "$PYTHON" ]]; then
    warn "Homebrew Python 3.12 is incompatible with this macOS version. Installing via pyenv..."

    if ! command -v pyenv &>/dev/null; then
        info "Installing pyenv..."
        brew install pyenv
    fi

    if [[ ! -d "$HOME/.pyenv/versions/$PYTHON_VERSION" ]]; then
        info "Installing Python $PYTHON_VERSION via pyenv (with tkinter support)..."
        if [[ -n "$TCLTK_PREFIX" ]]; then
            export PYTHON_CONFIGURE_OPTS="--with-tcltk-includes='-I$TCLTK_PREFIX/include' --with-tcltk-libs='-L$TCLTK_PREFIX/lib -ltcl8.6 -ltk8.6'"
        fi
        pyenv install "$PYTHON_VERSION"
    else
        info "Python $PYTHON_VERSION already installed via pyenv."
    fi

    PYTHON="$PYENV_PYTHON"
elif [[ "$PYTHON" == "$PYENV_PYTHON" ]] && ! "$PYTHON" -c "import tkinter" &>/dev/null; then
    # A pyenv build already exists (e.g. from before Tcl/Tk was installed, or
    # an older run of this script) but wasn't compiled with tkinter support.
    # Rebuild it rather than silently keeping a GUI-less Python around.
    warn "Existing pyenv Python $PYTHON_VERSION lacks tkinter support. Rebuilding with Tcl/Tk..."

    if ! command -v pyenv &>/dev/null; then
        info "Installing pyenv..."
        brew install pyenv
    fi

    if [[ -n "$TCLTK_PREFIX" ]]; then
        export PYTHON_CONFIGURE_OPTS="--with-tcltk-includes='-I$TCLTK_PREFIX/include' --with-tcltk-libs='-L$TCLTK_PREFIX/lib -ltcl8.6 -ltk8.6'"
    fi
    pyenv uninstall -f "$PYTHON_VERSION"
    pyenv install "$PYTHON_VERSION"

    PYTHON="$PYENV_PYTHON"
elif [[ "$PYTHON" == "$(brew --prefix python@3.12 2>/dev/null)/bin/python3.12" ]]; then
    # Homebrew's Python ships tkinter as a separate formula.
    if ! "$PYTHON" -c "import tkinter" &>/dev/null; then
        info "Installing python-tk (tkinter support for Homebrew Python)..."
        brew install python-tk@3.12 || true
    fi
fi

info "Using Python: $PYTHON ($($PYTHON --version))"

if ! "$PYTHON" -c "import tkinter" &>/dev/null; then
    warn "tkinter isn't available for this Python — the GUI (rtsp-ndi-gui) won't run, but the CLI/service will work fine."
fi

# ── install pipx via the working Python ──────────────────────────────────────
PIPX="$($PYTHON -c 'import sys; print(sys.prefix)')/bin/pipx"

if [[ ! -x "$PIPX" ]]; then
    info "Installing pipx..."
    "$PYTHON" -m pip install --quiet pipx
fi

# ── install or upgrade rtsp-ndi ───────────────────────────────────────────────
# --force reinstalls even if pipx thinks it's already installed, which for a
# git source also means re-fetching the branch's latest commit each run.
# pipx can exit nonzero here for reasons unrelated to the install actually
# working (e.g. its shared-library refresh step, or a shadowed-executable
# note), so don't let `set -e` treat that as fatal — the executable checks
# right after this are what actually verify success.
if "$PIPX" list 2>/dev/null | grep -q "$PACKAGE"; then
    info "Reinstalling $PACKAGE from $SOURCE..."
    "$PYTHON" -m pipx install --force "$SOURCE" || true
else
    info "Installing $PACKAGE from $SOURCE..."
    "$PYTHON" -m pipx install "$SOURCE" || true
fi

# ── ensure ~/.local/bin is on PATH ────────────────────────────────────────────
LOCAL_BIN="$HOME/.local/bin"
SHELL_RC=""

if [[ "$SHELL" == */zsh ]]; then
    SHELL_RC="$HOME/.zshrc"
elif [[ "$SHELL" == */bash ]]; then
    SHELL_RC="$HOME/.bashrc"
fi

if [[ -n "$SHELL_RC" ]] && ! grep -q "$LOCAL_BIN" "$SHELL_RC" 2>/dev/null; then
    echo "export PATH=\"$LOCAL_BIN:\$PATH\"" >> "$SHELL_RC"
    info "Added $LOCAL_BIN to PATH in $SHELL_RC"
fi

export PATH="$LOCAL_BIN:$PATH"

# ── verify the install actually produced the expected executables ────────────
if [[ ! -x "$LOCAL_BIN/rtsp-ndi" ]]; then
    die "pipx install finished but $LOCAL_BIN/rtsp-ndi is missing. Check the pipx output above for errors."
fi

APP_DIR="$HOME/Applications/RTSP-NDI.app"
GUI_EXECUTABLE="$LOCAL_BIN/rtsp-ndi-gui"

if [[ ! -x "$GUI_EXECUTABLE" ]]; then
    warn "Installed from $SOURCE but rtsp-ndi-gui is still missing — check the pipx output above for errors, or try:"
    warn "  pipx install --force '$SOURCE'"
fi

# ── build a .icns app icon from the icon bundled inside the package ──────────
build_icns() {
    local src="$1" out_icns="$2" iconset_parent iconset sz sz2
    command -v sips &>/dev/null && command -v iconutil &>/dev/null || return 1
    iconset_parent="$(mktemp -d)"
    iconset="$iconset_parent/AppIcon.iconset"
    mkdir -p "$iconset"
    for sz in 16 32 128 256 512; do
        sz2=$((sz * 2))
        sips -z "$sz" "$sz" "$src" --out "$iconset/icon_${sz}x${sz}.png" &>/dev/null || { rm -rf "$iconset_parent"; return 1; }
        sips -z "$sz2" "$sz2" "$src" --out "$iconset/icon_${sz}x${sz}@2x.png" &>/dev/null || { rm -rf "$iconset_parent"; return 1; }
    done
    iconutil -c icns "$iconset" -o "$out_icns" &>/dev/null
    local ok=$?
    rm -rf "$iconset_parent"
    return $ok
}

# The icon ships inside the installed package (src/rtsp_ndi/assets/icon.png).
# Don't guess pipx's venv directory layout — it differs by platform and has
# changed across pipx versions (e.g. ~/.local/pipx vs the newer platform data
# dir, which on macOS is ~/Library/Application Support/pipx). Instead, read
# the venv's python straight off the shebang of the script pipx just
# installed — pip/setuptools always points console-script shebangs at their
# own venv's interpreter, regardless of where that venv lives.
PIPX_VENV_PYTHON="$(head -n1 "$LOCAL_BIN/rtsp-ndi" 2>/dev/null | sed 's/^#!//')"
ICON_SOURCE=""
if [[ -x "$PIPX_VENV_PYTHON" ]]; then
    ICON_SOURCE="$("$PIPX_VENV_PYTHON" -c "
import pathlib
try:
    import rtsp_ndi
    p = pathlib.Path(rtsp_ndi.__file__).parent / 'assets' / 'icon.png'
    print(p if p.exists() else '')
except Exception:
    print('')
" 2>/dev/null)"
fi

# ── create a double-clickable macOS app for the GUI ───────────────────────────
if [[ -x "$GUI_EXECUTABLE" ]]; then
    info "Creating RTSP-NDI.app in ~/Applications..."
    mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"
    cat > "$APP_DIR/Contents/MacOS/RTSP-NDI" <<APP_EOF
#!/usr/bin/env bash
export PATH="$LOCAL_BIN:\$PATH"
exec "$GUI_EXECUTABLE"
APP_EOF
    chmod +x "$APP_DIR/Contents/MacOS/RTSP-NDI"

    ICON_PLIST_KEY=""
    if [[ -n "$ICON_SOURCE" ]] && build_icns "$ICON_SOURCE" "$APP_DIR/Contents/Resources/AppIcon.icns"; then
        ICON_PLIST_KEY="    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
"
        info "App icon generated."
    else
        warn "Could not generate the app icon (sips/iconutil unavailable, or the icon asset is missing) — RTSP-NDI.app will use the default icon."
    fi

    cat > "$APP_DIR/Contents/Info.plist" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>RTSP-NDI</string>
    <key>CFBundleExecutable</key>
    <string>RTSP-NDI</string>
    <key>CFBundleIdentifier</key>
    <string>com.rtsp-ndi.gui</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
${ICON_PLIST_KEY}    <key>LSUIElement</key>
    <false/>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
PLIST_EOF
    touch "$APP_DIR"
    info "RTSP-NDI.app created — find it in ~/Applications or Spotlight."
fi

# ── register launchd service ──────────────────────────────────────────────────
PLIST="$HOME/Library/LaunchAgents/com.rtsp-ndi.plist"
EXECUTABLE="$LOCAL_BIN/rtsp-ndi"

if [[ -x "$EXECUTABLE" ]]; then
    info "Registering launchd service..."
    LOG_DIR="$HOME/Library/Logs/rtsp-ndi"
    mkdir -p "$LOG_DIR"
    cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.rtsp-ndi</string>
    <key>ProgramArguments</key>
    <array>
        <string>$EXECUTABLE</string>
        <string>run</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/rtsp-ndi.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/rtsp-ndi.error.log</string>
</dict>
</plist>
PLIST_EOF
    info "Launchd plist written to $PLIST"
fi

# ── done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}✓ Installation complete!${NC}"
echo ""
echo "Open the GUI to scan your network for cameras, add feeds, and manage them:"
echo "  open '$APP_DIR'      (or launch RTSP-NDI from Spotlight/Applications)"
echo "  rtsp-ndi-gui           (same thing, from the terminal)"
echo ""
echo "Or use the CLI:"
echo "  rtsp-ndi add --url 'rtsp://user:password@camera-ip/stream' --name 'Camera 1'"
echo "  rtsp-ndi start"
echo ""
echo "Other commands: rtsp-ndi list | stop | restart | status | remove <name>"
echo ""
echo "If rtsp-ndi is not found, restart your terminal or run:"
echo "  export PATH=\"$LOCAL_BIN:\$PATH\""
