"""
Minimal ctypes bindings for the NDI SDK.

The NDI runtime dylib is sourced from the `ndi-python` PyPI package,
which bundles it for macOS, Windows, and Linux — no manual SDK download needed.
"""

import ctypes
import os
import sys
import threading
from ctypes import (
    POINTER, Structure,
    c_bool, c_char_p, c_float, c_int, c_int64, c_uint32, c_void_p,
)
from pathlib import Path


# ── locate the dylib ──────────────────────────────────────────────────────────

def _find_dylib() -> str:
    # 1. Explicit override
    env = os.environ.get("NDI_SDK_LIB")
    if env:
        return env

    # 2. Bundled inside the ndi-python wheel (preferred — no SDK install needed)
    # Use find_spec to locate the package directory without importing the
    # C extension, which crashes on macOS due to a GIL issue in ndi-python.
    # The bundled runtime's filename is platform-specific (libndi.dylib on
    # macOS, libndi.so on Linux, a .dll on Windows).
    try:
        import importlib.util
        spec = importlib.util.find_spec("NDIlib")
        if spec and spec.origin:
            pkg_dir = Path(spec.origin).parent
            if sys.platform == "darwin":
                bundled_names = ["libndi.dylib"]
            elif sys.platform == "win32":
                bundled_names = ["Processing.NDI.Lib.x64.dll", "ndi.dll"]
            else:
                bundled_names = ["libndi.so"]
            for name in bundled_names:
                bundled = pkg_dir / name
                if bundled.exists():
                    return str(bundled)
            # Fall back to any versioned shared object (e.g. libndi.so.6).
            for pattern in ("libndi.so*", "libndi*.dylib", "*ndi*.dll"):
                for match in pkg_dir.glob(pattern):
                    return str(match)
    except Exception:
        pass

    # 3. Manually installed NDI SDK fallback
    if sys.platform == "darwin":
        candidates = ["/Library/NDI SDK for Apple/lib/macOS/libndi.dylib"]
    elif sys.platform == "win32":
        pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        candidates = [
            os.path.join(pf, "NDI", "NDI 6 SDK", "Bin", "x64", "Processing.NDI.Lib.x64.dll"),
        ]
    else:
        candidates = [
            "/usr/lib/libndi.so",
            "/usr/local/lib/libndi.so",
        ]

    for path in candidates:
        if os.path.exists(path):
            return path

    raise OSError(
        "NDI runtime library not found.\n"
        "  Run: pip install ndi-python   (bundles the runtime automatically)\n"
        "  Or set NDI_SDK_LIB=/path/to/libndi to point at it directly."
    )


_lib = ctypes.CDLL(_find_dylib())


# ── constants ─────────────────────────────────────────────────────────────────

FOURCC_UYVY = 0x59565955  # packed UYVY
FOURCC_RGBA = 0x41424752  # RGBA — universal fallback, supported by all PyAV sources
FRAME_FORMAT_PROGRESSIVE = 1
TIMECODE_SYNTHESIZE = 0x8000000000000000


# ── structures ────────────────────────────────────────────────────────────────

class _SendCreate(Structure):
    _fields_ = [
        ("p_ndi_name",  c_char_p),
        ("p_groups",    c_char_p),
        ("clock_video", c_bool),
        ("clock_audio", c_bool),
    ]


class VideoFrameV2(Structure):
    _fields_ = [
        ("xres",                 c_int),
        ("yres",                 c_int),
        ("FourCC",               c_uint32),
        ("frame_rate_N",         c_int),
        ("frame_rate_D",         c_int),
        ("picture_aspect_ratio", c_float),
        ("frame_format_type",    c_int),
        ("timecode",             c_int64),
        ("p_data",               c_void_p),
        ("line_stride_or_size",  c_int),
        ("p_metadata",           c_char_p),
        ("timestamp",            c_int64),
    ]


# ── function prototypes ───────────────────────────────────────────────────────

_lib.NDIlib_initialize.restype  = c_bool
_lib.NDIlib_initialize.argtypes = []

_lib.NDIlib_destroy.restype  = None
_lib.NDIlib_destroy.argtypes = []

_lib.NDIlib_send_create.restype  = c_void_p
_lib.NDIlib_send_create.argtypes = [POINTER(_SendCreate)]

_lib.NDIlib_send_destroy.restype  = None
_lib.NDIlib_send_destroy.argtypes = [c_void_p]

_lib.NDIlib_send_send_video_v2.restype  = None
_lib.NDIlib_send_send_video_v2.argtypes = [c_void_p, POINTER(VideoFrameV2)]


# ── public API ────────────────────────────────────────────────────────────────
#
# initialize()/destroy() are reference-counted: the underlying NDIlib runtime
# is only actually brought up on the first call and torn down once every
# caller has released it. This makes it safe to call from multiple concurrent
# camera bridge threads (as the GUI and service manager do) without one
# bridge's shutdown tearing down NDI out from under another still-running one.

_init_lock = threading.Lock()
_init_count = 0

def initialize() -> bool:
    global _init_count
    with _init_lock:
        if _init_count == 0:
            if not _lib.NDIlib_initialize():
                return False
        _init_count += 1
        return True

def destroy() -> None:
    global _init_count
    with _init_lock:
        if _init_count <= 0:
            return
        _init_count -= 1
        if _init_count == 0:
            _lib.NDIlib_destroy()

def send_create(name: str, clock_video: bool = False) -> c_void_p:
    cfg = _SendCreate(
        p_ndi_name  = name.encode(),
        p_groups    = None,
        clock_video = clock_video,
        clock_audio = False,
    )
    handle = _lib.NDIlib_send_create(ctypes.byref(cfg))
    if not handle:
        raise RuntimeError("NDIlib_send_create returned NULL")
    return handle

def send_destroy(handle: c_void_p) -> None:
    _lib.NDIlib_send_destroy(handle)

def send_video_v2(handle: c_void_p, frame: VideoFrameV2) -> None:
    _lib.NDIlib_send_send_video_v2(handle, ctypes.byref(frame))
