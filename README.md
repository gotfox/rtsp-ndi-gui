# rtsp-ndi

Bridge RTSP camera streams to NDI sources on your local network — with a
desktop GUI, network scanning to find cameras, and a background service to
keep feeds running.

This was built mostly using Claude. Use at your own risk

## Install

### macOS (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/gotfox/rtsp-ndi/main/install.sh | bash
```

Requires [Homebrew](https://brew.sh). The script handles FFmpeg, Tcl/Tk (for
the GUI), Python, and the package automatically (installing straight from
this repo's `main` branch), and creates a **RTSP-NDI** app in `~/Applications`.

Prefer not to use Terminal directly? Download
[`packaging/Install RTSP-NDI.command`](packaging/Install%20RTSP-NDI.command)
and double-click it in Finder — it just runs the same installer. macOS will
warn it's from an unidentified developer the first time since it isn't
code-signed; right-click it and choose **Open** to get past that once (and
if it won't run at all, `chmod +x` it — permissions can be lost when
downloading a single file rather than cloning the repo).

### Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/gotfox/rtsp-ndi/main/uninstall.sh | bash
```

Removes the launchd service, the pipx install, and the RTSP-NDI.app bundle.
Homebrew/pyenv/FFmpeg/Tcl-Tk are left alone since other things may depend on
them, and your camera config/logs are kept by default — add
`RTSP_NDI_PURGE=1` before `bash` to remove those too. Or double-click
[`packaging/Uninstall RTSP-NDI.command`](packaging/Uninstall%20RTSP-NDI.command).

### Other platforms

```bash
pip install "git+https://github.com/gotfox/rtsp-ndi@main"
```

(the `rtsp-ndi` name on PyPI is an older, separately-maintained release
without the GUI — installing from this repo gets you the current code)

Also requires:
- **FFmpeg** on your `PATH` — Windows: https://ffmpeg.org/download.html, Linux: `sudo apt install ffmpeg`
- **Tkinter** for the GUI — usually bundled with Python; on Debian/Ubuntu: `sudo apt install python3-tk`

## GUI

```bash
rtsp-ndi-gui
```

(or launch the **RTSP-NDI** app from `~/Applications` / Spotlight on macOS)

From the GUI you can:
- **Scan Network…** — sweep a subnet for open RTSP ports (554 by default, or
  any custom port) and add what it finds.
- **Add Feed…** — add a camera manually by host, with a custom port and path
  if needed, or paste a full `rtsp://` URL directly.
- **Rename** a feed's NDI source name at any time — it restarts the bridge
  automatically so the new name shows up on the network.
- **Start / Stop / Restart** each feed individually, or **Start All / Stop
  All**.
- **Details…** — see the full status/error message for the selected feed
  (the table's Detail column can get cut off; this shows the whole thing).
- **View Log…** — open the log file at `~/Library/Logs/rtsp-ndi/rtsp-ndi.log`,
  which records every status change (and full tracebacks for unexpected
  errors) — useful since a GUI app launched from Finder has no terminal for
  its output to go to otherwise.

Feeds added or edited in the GUI are saved to the same config the CLI and
background service use, so `rtsp-ndi list` will show them too.

## CLI / background service

```bash
rtsp-ndi add --url 'rtsp://user:password@camera-ip/stream' --name 'Camera 1'
rtsp-ndi start
```

The source will appear in any NDI-aware application (OBS, vMix, NDI Monitor)
on your local network.

### Commands

```
rtsp-ndi add --url <url> --name <name> [--retries <n>] [--latency low|normal]
rtsp-ndi remove <name>
rtsp-ndi list
rtsp-ndi start      # start the background service, enabled at login
rtsp-ndi stop
rtsp-ndi restart
rtsp-ndi status
rtsp-ndi gui         # launch the desktop GUI
rtsp-ndi --version
```

The version is also shown in the GUI's title bar and status bar, and in
`rtsp-ndi status` — handy for confirming a reinstall from `main` actually
picked up new code, since it isn't published to PyPI as separate releases.

### One-off bridge (no service, no config file)

```bash
rtsp-to-ndi --url rtsp://YOUR_CAMERA_IP/stream --name "Camera 1"
```

```
--url      RTSP source URL (required)
--name     NDI source name shown on the network (default: "RTSP Source")
--latency  low or normal (default: low)
```

## Notes

- The NDI runtime is bundled automatically via the `ndi-python` dependency — no manual SDK download needed.
- To use a custom NDI SDK install, set `NDI_SDK_LIB=/path/to/libndi`.
- Network scanning only probes for an open RTSP port and confirms the RTSP
  protocol handshake — it never guesses credentials or stream paths.
