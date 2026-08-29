"""
Camera configuration store shared by the CLI service and the GUI.

Cameras are persisted as a JSON list of dicts:
    {"id": "<uuid hex>", "name": "Camera 1", "url": "rtsp://...",
     "retries": 3, "latency": "low"}

`id` is a stable internal identifier so a camera can be renamed (its NDI
source name changed) without losing its identity or config history — `name`
is purely the human-facing / NDI-visible label.
"""

import json
import uuid
from pathlib import Path

CONFIG_DIR  = Path.home() / ".config" / "rtsp-ndi"
CONFIG_FILE = CONFIG_DIR / "cameras.json"


def load_cameras() -> list[dict]:
    if not CONFIG_FILE.exists():
        return []
    with open(CONFIG_FILE) as f:
        cameras = json.load(f)

    changed = False
    for camera in cameras:
        if "id" not in camera:
            camera["id"] = uuid.uuid4().hex
            changed = True
    if changed:
        save_cameras(cameras)

    return cameras


def save_cameras(cameras: list[dict]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cameras, f, indent=2)


def new_id() -> str:
    return uuid.uuid4().hex
