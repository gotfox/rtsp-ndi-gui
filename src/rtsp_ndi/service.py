#!/usr/bin/env python3
"""
rtsp-ndi service manager.

Commands:
    rtsp-ndi add    --url <url> --name <name> [--retries <n>]
    rtsp-ndi remove <name>
    rtsp-ndi list
    rtsp-ndi start
    rtsp-ndi stop
    rtsp-ndi status
    rtsp-ndi gui     (launch the desktop GUI)
    rtsp-ndi run     (internal — called by launchd)
"""

import argparse
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from rtsp_ndi import __version__
from rtsp_ndi.config import CONFIG_DIR, CONFIG_FILE, load_cameras, new_id, save_cameras as _save_cameras

# ── paths ─────────────────────────────────────────────────────────────────────

LOG_DIR     = Path.home() / "Library" / "Logs" / "rtsp-ndi"
PLIST_DIR   = Path.home() / "Library" / "LaunchAgents"
PLIST_PATH  = PLIST_DIR / "com.rtsp-ndi.plist"
PLIST_LABEL = "com.rtsp-ndi"


# ── config helpers ────────────────────────────────────────────────────────────

def save_cameras(cameras):
    _save_cameras(cameras)
    print(f"Config saved to {CONFIG_FILE}")


# ── launchd plist ─────────────────────────────────────────────────────────────

def plist_contents():
    executable = Path(sys.executable).parent / "rtsp-ndi"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{executable}</string>
        <string>run</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{LOG_DIR}/rtsp-ndi.log</string>
    <key>StandardErrorPath</key>
    <string>{LOG_DIR}/rtsp-ndi.error.log</string>
</dict>
</plist>
"""

def install_plist():
    PLIST_DIR.mkdir(parents=True, exist_ok=True)
    with open(PLIST_PATH, "w") as f:
        f.write(plist_contents())

def launchctl(*args):
    result = subprocess.run(["launchctl", *args], capture_output=True, text=True)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_add(args):
    cameras = load_cameras()
    if any(c["name"] == args.name for c in cameras):
        print(f"Error: a camera named '{args.name}' already exists. Remove it first.")
        sys.exit(1)
    cameras.append({
        "id":      new_id(),
        "name":    args.name,
        "url":     args.url,
        "retries": args.retries,
        "latency": args.latency,
    })
    save_cameras(cameras)
    print(f"Added '{args.name}'. Run 'rtsp-ndi start' (or restart if already running) to apply.")


def cmd_remove(args):
    cameras = load_cameras()
    before = len(cameras)
    cameras = [c for c in cameras if c["name"] != args.name]
    if len(cameras) == before:
        print(f"Error: no camera named '{args.name}' found.")
        sys.exit(1)
    save_cameras(cameras)
    print(f"Removed '{args.name}'. Run 'rtsp-ndi restart' to apply.")


def cmd_list(args):
    cameras = load_cameras()
    if not cameras:
        print("No cameras configured. Use 'rtsp-ndi add' to add one.")
        return
    print(f"{'NAME':<24} {'RETRIES':<10} {'LATENCY':<10} URL")
    print("-" * 80)
    for c in cameras:
        retries = "unlimited" if c.get("retries") == 0 else str(c.get("retries", 3))
        print(f"{c['name']:<24} {retries:<10} {c.get('latency','low'):<10} {c['url']}")


def cmd_start(args):
    cameras = load_cameras()
    if not cameras:
        print("No cameras configured. Use 'rtsp-ndi add' first.")
        sys.exit(1)
    install_plist()
    code, _, err = launchctl("load", "-w", str(PLIST_PATH))
    if code == 0:
        print("rtsp-ndi service started and enabled at login.")
    else:
        # Already loaded — just kick it
        launchctl("start", PLIST_LABEL)
        print("rtsp-ndi service started.")


def cmd_stop(args):
    code, _, _ = launchctl("unload", "-w", str(PLIST_PATH))
    if code == 0:
        print("rtsp-ndi service stopped and disabled at login.")
    else:
        launchctl("stop", PLIST_LABEL)
        print("rtsp-ndi service stopped.")


def cmd_restart(args):
    cmd_stop(args)
    time.sleep(1)
    cmd_start(args)


def cmd_status(args):
    print(f"rtsp-ndi {__version__}")
    code, out, _ = launchctl("list", PLIST_LABEL)
    if code != 0:
        print("rtsp-ndi service is not running.")
        return
    print("rtsp-ndi service is running.")
    cameras = load_cameras()
    if cameras:
        print(f"\nConfigured cameras ({len(cameras)}):")
        for c in cameras:
            retries = "unlimited" if c.get("retries") == 0 else str(c.get("retries", 3))
            print(f"  • {c['name']}  (retries: {retries}, latency: {c.get('latency','low')})")
    log = LOG_DIR / "rtsp-ndi.log"
    if log.exists():
        print(f"\nLog: {log}")


def cmd_gui(args):
    from rtsp_ndi.gui import main as gui_main
    gui_main()


# ── run (called by launchd) ───────────────────────────────────────────────────

def run_camera(camera, stop_event):
    """Run a single camera bridge with retry logic in its own thread."""
    from rtsp_ndi.bridge import BridgeError
    from rtsp_ndi.bridge import run as bridge_run

    name    = camera["name"]
    url     = camera["url"]
    retries = camera.get("retries", 3)   # 0 = unlimited
    latency = camera.get("latency", "low")

    attempt = 0
    while not stop_event.is_set():
        if retries != 0 and attempt >= retries:
            print(f"[{name}] Max retries ({retries}) reached. Giving up.", flush=True)
            return

        if attempt > 0:
            wait = min(30, 5 * attempt)
            print(f"[{name}] Retrying in {wait}s (attempt {attempt + 1})...", flush=True)
            stop_event.wait(wait)
            if stop_event.is_set():
                return

        attempt += 1
        print(f"[{name}] Starting bridge (attempt {attempt})...", flush=True)
        try:
            # Pass our stop_event through so bridge.run() doesn't try to
            # install signal handlers from this worker thread.
            bridge_run(url, name, latency, stop_event=stop_event)
        except BridgeError as e:
            print(f"[{name}] Error: {e}", flush=True)
        except Exception as e:
            print(f"[{name}] Unexpected error: {e}", flush=True)

    print(f"[{name}] Stopped.", flush=True)


def cmd_run(args):
    cameras = load_cameras()
    if not cameras:
        print("No cameras configured. Exiting.")
        sys.exit(0)

    print(f"Starting rtsp-ndi with {len(cameras)} camera(s)...", flush=True)

    stop_event = threading.Event()
    threads = []

    for camera in cameras:
        t = threading.Thread(target=run_camera, args=(camera, stop_event), daemon=True)
        t.start()
        threads.append(t)

    def shutdown(sig, frame):
        print("Shutting down...", flush=True)
        stop_event.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    for t in threads:
        t.join()


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="rtsp-ndi",
        description="Manage RTSP to NDI bridges."
    )
    parser.add_argument("--version", action="version", version=f"rtsp-ndi {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    # add
    p_add = sub.add_parser("add", help="Add a camera")
    p_add.add_argument("--url",     required=True, help="RTSP URL")
    p_add.add_argument("--name",    required=True, help="NDI source name")
    p_add.add_argument("--retries", type=int, default=3,
                       help="Max reconnect attempts (0 = unlimited, default: 3)")
    p_add.add_argument("--latency", choices=["low", "normal"], default="low")

    # remove
    p_rm = sub.add_parser("remove", help="Remove a camera by name")
    p_rm.add_argument("name", help="NDI source name to remove")

    # list
    sub.add_parser("list", help="List configured cameras")

    # start / stop / restart / status
    sub.add_parser("start",   help="Start the service and enable at login")
    sub.add_parser("stop",    help="Stop the service and disable at login")
    sub.add_parser("restart", help="Restart the service")
    sub.add_parser("status",  help="Show service status")

    # gui
    sub.add_parser("gui", help="Launch the desktop GUI")

    # run (internal, called by launchd)
    sub.add_parser("run", help=argparse.SUPPRESS)

    args = parser.parse_args()
    {
        "add":     cmd_add,
        "remove":  cmd_remove,
        "list":    cmd_list,
        "start":   cmd_start,
        "stop":    cmd_stop,
        "restart": cmd_restart,
        "status":  cmd_status,
        "gui":     cmd_gui,
        "run":     cmd_run,
    }[args.command](args)


if __name__ == "__main__":
    main()
