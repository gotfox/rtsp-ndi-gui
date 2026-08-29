"""
Runtime management of camera bridges.

CameraManager owns the in-memory list of configured cameras (backed by
config.py) plus one CameraWorker per camera, each of which runs the RTSP -> NDI
bridge in its own daemon thread with automatic reconnect/retry. This is the
shared engine behind both the GUI and the `rtsp-ndi run` CLI/launchd service.
"""

import threading
import time

from . import bridge
from . import config as cfgmod

# Statuses a worker can report. "running" states (used to decide whether a
# rename/edit needs to restart the bridge) are anything past "starting".
RUNNING_STATUSES = {"starting", "connecting", "connected", "streaming", "retrying"}


class CameraWorker:
    """Owns the background thread that keeps one camera's bridge alive."""

    def __init__(self, camera: dict, on_status=None):
        self.camera = camera
        self.on_status = on_status
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.status = "stopped"
        self.detail = ""

    # -- status -------------------------------------------------------------

    def _set_status(self, status: str, detail: str = "") -> None:
        with self._lock:
            self.status = status
            self.detail = detail
        if self.on_status:
            try:
                self.on_status(self.camera["id"], status, detail)
            except Exception:
                pass

    def snapshot(self):
        with self._lock:
            return self.status, self.detail

    @property
    def is_running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    # -- lifecycle ------------------------------------------------------------

    def start(self) -> None:
        if self.is_running:
            return
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self.stop_event.set()
        thread = self.thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._set_status("stopped")

    def restart(self) -> None:
        self.stop()
        self.start()

    # -- worker loop ----------------------------------------------------------

    def _run_loop(self) -> None:
        camera = self.camera
        retries = camera.get("retries", 3)  # 0 = unlimited
        latency = camera.get("latency", "low")
        attempt = 0

        while not self.stop_event.is_set():
            if retries != 0 and attempt >= retries:
                self._set_status("error", f"Max retries ({retries}) reached")
                return

            if attempt > 0:
                wait = min(30, 5 * attempt)
                self._set_status("retrying", f"Retrying in {wait}s (attempt {attempt + 1})")
                if self.stop_event.wait(wait):
                    self._set_status("stopped")
                    return

            attempt += 1
            self._set_status("starting", f"Attempt {attempt}")
            try:
                bridge.run(
                    camera["url"],
                    camera["name"],
                    latency,
                    stop_event=self.stop_event,
                    status_callback=self._set_status,
                )
            except bridge.BridgeError as e:
                self._set_status("error", str(e))
            except Exception as e:
                self._set_status("error", f"Unexpected error: {e}")

        self._set_status("stopped")


class CameraManager:
    """In-memory registry of cameras + their CameraWorkers, backed by config.py."""

    def __init__(self, on_status=None):
        self.on_status = on_status
        self.cameras: list[dict] = cfgmod.load_cameras()
        self._lock = threading.Lock()
        self.workers: dict[str, CameraWorker] = {
            c["id"]: CameraWorker(c, on_status=on_status) for c in self.cameras
        }

    # -- queries ----------------------------------------------------------------

    def list(self) -> list[dict]:
        with self._lock:
            return list(self.cameras)

    def get(self, cam_id: str) -> dict | None:
        with self._lock:
            return next((c for c in self.cameras if c["id"] == cam_id), None)

    def status(self, cam_id: str):
        worker = self.workers.get(cam_id)
        if worker is None:
            return "stopped", ""
        return worker.snapshot()

    def _name_taken(self, name: str, exclude_id: str | None = None) -> bool:
        return any(
            c["name"] == name and c["id"] != exclude_id for c in self.cameras
        )

    # -- mutation -----------------------------------------------------------

    def add(self, name: str, url: str, retries: int = 3, latency: str = "low") -> dict:
        name = name.strip()
        if not name:
            raise ValueError("Name is required")
        if not url.strip():
            raise ValueError("RTSP URL is required")
        with self._lock:
            if self._name_taken(name):
                raise ValueError(f"A feed named '{name}' already exists")
            camera = {
                "id": cfgmod.new_id(),
                "name": name,
                "url": url.strip(),
                "retries": retries,
                "latency": latency,
            }
            self.cameras.append(camera)
            self.workers[camera["id"]] = CameraWorker(camera, on_status=self.on_status)
            cfgmod.save_cameras(self.cameras)
        return camera

    def remove(self, cam_id: str) -> None:
        worker = self.workers.pop(cam_id, None)
        if worker:
            worker.stop()
        with self._lock:
            self.cameras = [c for c in self.cameras if c["id"] != cam_id]
            cfgmod.save_cameras(self.cameras)

    def edit(self, cam_id: str, name: str | None = None, **fields) -> None:
        """Update name/url/retries/latency in one shot.

        Stops the bridge (if running) before applying changes and restarts it
        afterwards — a rename changes the NDI source name, which is fixed at
        sender-creation time, so any live change here needs a restart to take
        effect on the network either way.
        """
        camera = self.get(cam_id)
        if camera is None:
            raise ValueError("Feed not found")

        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError("Name is required")
            with self._lock:
                if self._name_taken(name, exclude_id=cam_id):
                    raise ValueError(f"A feed named '{name}' already exists")

        worker = self.workers.get(cam_id)
        was_running = bool(worker and worker.is_running)
        if was_running:
            worker.stop()

        with self._lock:
            if name is not None:
                camera["name"] = name
            camera.update(fields)
            cfgmod.save_cameras(self.cameras)

        if was_running:
            worker.start()

    def rename(self, cam_id: str, new_name: str) -> None:
        self.edit(cam_id, name=new_name)

    def update(self, cam_id: str, **fields) -> None:
        """Update url/retries/latency; restarts the bridge if it was running."""
        self.edit(cam_id, **fields)

    # -- control ------------------------------------------------------------

    def start(self, cam_id: str) -> None:
        worker = self.workers.get(cam_id)
        if worker:
            worker.start()

    def stop(self, cam_id: str) -> None:
        worker = self.workers.get(cam_id)
        if worker:
            worker.stop()

    def restart(self, cam_id: str) -> None:
        worker = self.workers.get(cam_id)
        if worker:
            worker.restart()

    def start_all(self) -> None:
        for worker in self.workers.values():
            worker.start()

    def stop_all(self) -> None:
        threads = []
        for worker in self.workers.values():
            worker.stop_event.set()
        for worker in self.workers.values():
            t = threading.Thread(target=worker.stop)
            t.start()
            threads.append(t)
        for t in threads:
            t.join(timeout=10)

    def shutdown(self) -> None:
        self.stop_all()
