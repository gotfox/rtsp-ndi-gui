# rtsp-ndi

Bridge RTSP camera streams to NDI sources on your local network — with a
desktop GUI, network scanning to find cameras, and a background service to
keep feeds running.

This was built mostly using Claude. Use at your own risk

## Install

### macOS (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/matthewmeekins/rtsp-ndi/main/install.sh | bash
```

Requires [Homebrew](https://brew.sh). The script handles FFmpeg, Tcl/Tk (for
the GUI), Python, and the package automatically, and creates a **RTSP-NDI**
app in `~/Applications`.

### Other platforms

```bash
pip install rtsp-ndi
```

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
```

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
