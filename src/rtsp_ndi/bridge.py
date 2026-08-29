#!/usr/bin/env python3
"""
RTSP to NDI bridge.
Decodes an RTSP stream via FFmpeg (PyAV) and re-sends it as an NDI source.

Usage:
    python rtsp_to_ndi.py --url rtsp://192.168.1.100/stream --name "Camera 1"
"""

import argparse
import ctypes
import signal
import sys
import threading
import time

import av
import numpy as np

from rtsp_ndi import ndi_ctypes as ndi


class BridgeError(RuntimeError):
    """Raised when the RTSP-to-NDI bridge cannot start or fails fatally."""


def run(
    rtsp_url: str,
    ndi_name: str,
    latency: str = "low",
    stop_event: threading.Event | None = None,
    status_callback=None,
) -> None:
    """Bridge a single RTSP stream to an NDI source until stopped.

    Raises BridgeError on unrecoverable startup failures. Safe to call from
    a background thread when an external `stop_event` is supplied — signal
    handlers are only installed when running on the main thread with no
    caller-supplied stop_event (i.e. the CLI use case).
    """

    def emit(status: str, detail: str = "") -> None:
        if status_callback:
            try:
                status_callback(status, detail)
            except Exception:
                pass

    owns_stop_event = stop_event is None
    if stop_event is None:
        stop_event = threading.Event()

    if not ndi.initialize():
        emit("error", "Could not initialize NDI")
        raise BridgeError("Could not initialize NDI")

    sender = ndi.send_create(ndi_name, clock_video=False)
    print(f"NDI source '{ndi_name}' created.")

    options = {
        "rtsp_transport": "tcp",
        "fflags": "nobuffer",
        "flags": "low_delay",
        "max_delay": "0",
    }
    if latency == "low":
        options["analyzeduration"] = "0"
        options["probesize"] = "32"

    print(f"Opening RTSP stream: {rtsp_url}")
    emit("connecting", f"Opening {rtsp_url}")
    try:
        container = av.open(rtsp_url, options=options, timeout=10.0)
    except Exception as e:
        print(f"ERROR: Could not open RTSP stream: {e}")
        ndi.send_destroy(sender)
        ndi.destroy()
        emit("error", f"Could not open RTSP stream: {e}")
        raise BridgeError(f"Could not open RTSP stream: {e}") from e

    video_stream = next((s for s in container.streams if s.type == "video"), None)
    if not video_stream:
        print("ERROR: No video stream found.")
        container.close()
        ndi.send_destroy(sender)
        ndi.destroy()
        emit("error", "No video stream found")
        raise BridgeError("No video stream found")

    frame_rate = float(video_stream.average_rate or 30)
    print(f"Stream: {video_stream.width}x{video_stream.height} @ {frame_rate:.2f} fps")
    emit("connected", f"{video_stream.width}x{video_stream.height} @ {frame_rate:.2f} fps")

    # Only take over signal handling when we own the stop_event (plain CLI
    # invocation) and we're on the main thread — signal.signal() raises when
    # called from a worker thread, which is how the GUI/service manager runs
    # multiple bridges concurrently.
    if owns_stop_event and threading.current_thread() is threading.main_thread():
        def shutdown(sig, frame):
            print("\nShutting down...")
            stop_event.set()

        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)

    frame_count = 0
    start_time = time.monotonic()

    try:
        for packet in container.demux(video_stream):
            if stop_event.is_set():
                break
            for av_frame in packet.decode():
                if stop_event.is_set():
                    break

                # Convert to RGBA — universally supported by PyAV regardless of source format
                raw = av_frame.to_ndarray(format="rgba")
                if not raw.flags["C_CONTIGUOUS"]:
                    raw = np.ascontiguousarray(raw)

                ndi_frame = ndi.VideoFrameV2()
                ndi_frame.xres                 = av_frame.width
                ndi_frame.yres                 = av_frame.height
                ndi_frame.FourCC               = ndi.FOURCC_RGBA
                ndi_frame.frame_rate_N         = int(frame_rate * 1000)
                ndi_frame.frame_rate_D         = 1000
                ndi_frame.picture_aspect_ratio = av_frame.width / av_frame.height
                ndi_frame.frame_format_type    = ndi.FRAME_FORMAT_PROGRESSIVE
                ndi_frame.timecode             = 0x8000000000000000  # NDI_SEND_TIMECODE_SYNTHESIZE
                ndi_frame.p_data               = raw.ctypes.data_as(ctypes.c_void_p)
                ndi_frame.line_stride_or_size  = av_frame.width * 4  # RGBA = 4 bytes/pixel

                ndi.send_video_v2(sender, ndi_frame)
                frame_count += 1

                if frame_count % 300 == 0:
                    elapsed = time.monotonic() - start_time
                    fps_avg = frame_count / elapsed if elapsed > 0 else 0.0
                    print(f"  {frame_count} frames sent ({fps_avg:.1f} fps avg)")
                    emit("streaming", f"{frame_count} frames sent ({fps_avg:.1f} fps avg)")

    except Exception as e:
        print(f"Stream error: {e}")
        emit("error", f"Stream error: {e}")
    finally:
        container.close()
        ndi.send_destroy(sender)
        ndi.destroy()
        print(f"Done. {frame_count} frames sent.")
        emit("stopped", f"{frame_count} frames sent")


def main():
    parser = argparse.ArgumentParser(description="Bridge an RTSP stream to NDI.")
    parser.add_argument("--url",  required=True, help="RTSP source URL")
    parser.add_argument("--name", default="RTSP Source", help="NDI source name")
    parser.add_argument("--latency", choices=["low", "normal"], default="low")
    args = parser.parse_args()
    try:
        run(args.url, args.name, args.latency)
    except BridgeError as e:
        print(f"ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
