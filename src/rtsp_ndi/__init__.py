"""rtsp-ndi: bridge RTSP camera streams to NDI sources."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("rtsp-ndi")
except PackageNotFoundError:
    # Running from a source checkout that was never pip/pipx-installed.
    __version__ = "unknown"
