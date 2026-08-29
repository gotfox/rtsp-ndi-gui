#!/usr/bin/env python3
"""
rtsp-ndi desktop GUI.

Lets you scan the local network for RTSP feeds (or add one manually with a
custom host/port), rename the NDI source it publishes as, and start/stop/
restart each feed independently — all backed by the same CameraManager the
CLI/launchd service uses, so feeds added here also show up in `rtsp-ndi list`.
"""

import ipaddress
import queue
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from urllib.parse import quote, urlsplit

from . import scanner
from .manager import CameraManager

STATUS_LABELS = {
    "stopped":    "Stopped",
    "starting":   "Starting…",
    "connecting": "Connecting…",
    "connected":  "Connected",
    "streaming":  "Streaming",
    "retrying":   "Retrying…",
    "error":      "Error",
}


def decompose_url(url: str) -> dict:
    """Best-effort split of an rtsp:// URL into the fields FeedDialog edits."""
    try:
        parts = urlsplit(url)
        return {
            "host": parts.hostname or "",
            "port": parts.port or scanner.DEFAULT_RTSP_PORT,
            "path": parts.path or "",
            "username": parts.username or "",
            "password": parts.password or "",
        }
    except Exception:
        return {}


class FeedDialog(tk.Toplevel):
    """Add or edit a feed: build a URL from host/custom port/path, or paste one."""

    def __init__(self, parent, title, initial=None, on_submit=None):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.on_submit = on_submit
        self.transient(parent)

        initial = initial or {}
        pad = {"padx": 8, "pady": 4}
        row = 0

        ttk.Label(self, text="Name").grid(row=row, column=0, sticky="e", **pad)
        self.name_var = tk.StringVar(value=initial.get("name", ""))
        name_entry = ttk.Entry(self, textvariable=self.name_var, width=34)
        name_entry.grid(row=row, column=1, columnspan=3, sticky="w", **pad)
        row += 1

        ttk.Label(self, text="Host").grid(row=row, column=0, sticky="e", **pad)
        self.host_var = tk.StringVar(value=initial.get("host", ""))
        ttk.Entry(self, textvariable=self.host_var, width=22).grid(row=row, column=1, sticky="w", **pad)
        ttk.Label(self, text="Port").grid(row=row, column=2, sticky="e", **pad)
        self.port_var = tk.StringVar(value=str(initial.get("port", scanner.DEFAULT_RTSP_PORT)))
        ttk.Entry(self, textvariable=self.port_var, width=8).grid(row=row, column=3, sticky="w", **pad)
        row += 1

        ttk.Label(self, text="Path").grid(row=row, column=0, sticky="e", **pad)
        self.path_var = tk.StringVar(value=initial.get("path", ""))
        ttk.Entry(self, textvariable=self.path_var, width=34).grid(row=row, column=1, columnspan=3, sticky="w", **pad)
        row += 1

        ttk.Label(self, text="Username").grid(row=row, column=0, sticky="e", **pad)
        self.user_var = tk.StringVar(value=initial.get("username", ""))
        ttk.Entry(self, textvariable=self.user_var, width=22).grid(row=row, column=1, sticky="w", **pad)
        ttk.Label(self, text="Password").grid(row=row, column=2, sticky="e", **pad)
        self.pass_var = tk.StringVar(value=initial.get("password", ""))
        ttk.Entry(self, textvariable=self.pass_var, width=14, show="*").grid(row=row, column=3, sticky="w", **pad)
        row += 1

        ttk.Label(self, text="RTSP URL").grid(row=row, column=0, sticky="e", **pad)
        self.url_var = tk.StringVar(value=initial.get("url", ""))
        ttk.Entry(self, textvariable=self.url_var, width=46).grid(row=row, column=1, columnspan=3, sticky="w", **pad)
        row += 1
        ttk.Label(
            self,
            text="Built automatically from the fields above — or edit/paste a full URL directly.",
            foreground="#888888",
        ).grid(row=row, column=0, columnspan=4, sticky="w", padx=8)
        row += 1

        ttk.Label(self, text="Latency").grid(row=row, column=0, sticky="e", **pad)
        self.latency_var = tk.StringVar(value=initial.get("latency", "low"))
        ttk.Combobox(
            self, textvariable=self.latency_var, values=["low", "normal"], width=8, state="readonly"
        ).grid(row=row, column=1, sticky="w", **pad)
        ttk.Label(self, text="Retries (0=∞)").grid(row=row, column=2, sticky="e", **pad)
        self.retries_var = tk.StringVar(value=str(initial.get("retries", 3)))
        ttk.Spinbox(self, from_=0, to=999, textvariable=self.retries_var, width=6).grid(
            row=row, column=3, sticky="w", **pad
        )
        row += 1

        btns = ttk.Frame(self)
        btns.grid(row=row, column=0, columnspan=4, pady=(10, 8))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right", padx=6)
        ttk.Button(btns, text="Save", command=self._submit).pack(side="right")

        self._syncing = False
        for var in (self.host_var, self.port_var, self.path_var, self.user_var, self.pass_var):
            var.trace_add("write", self._sync_url)
        if initial.get("host"):
            self._sync_url()

        name_entry.focus_set()
        self.bind("<Return>", lambda e: self._submit())
        self.bind("<Escape>", lambda e: self.destroy())
        self.grab_set()

    def _sync_url(self, *_args):
        if self._syncing:
            return
        self._syncing = True
        try:
            host = self.host_var.get().strip()
            if host:
                port = self.port_var.get().strip() or str(scanner.DEFAULT_RTSP_PORT)
                path = self.path_var.get().strip()
                if path and not path.startswith("/"):
                    path = "/" + path
                auth = ""
                user = self.user_var.get().strip()
                pw = self.pass_var.get()
                if user:
                    auth = quote(user, safe="")
                    if pw:
                        auth += f":{quote(pw, safe='')}"
                    auth += "@"
                self.url_var.set(f"rtsp://{auth}{host}:{port}{path}")
        finally:
            self._syncing = False

    def _submit(self):
        name = self.name_var.get().strip()
        url = self.url_var.get().strip()
        if not name:
            messagebox.showerror("Missing name", "Please enter a name for this feed.", parent=self)
            return
        if not url:
            messagebox.showerror("Missing URL", "Please enter a host, or a full RTSP URL.", parent=self)
            return
        try:
            retries = int(self.retries_var.get())
        except ValueError:
            retries = 3
        latency = self.latency_var.get() or "low"

        values = {"name": name, "url": url, "retries": retries, "latency": latency}
        if self.on_submit:
            try:
                self.on_submit(values)
            except ValueError as e:
                messagebox.showerror("Error", str(e), parent=self)
                return
        self.destroy()


class ScanDialog(tk.Toplevel):
    """Scan a subnet for open RTSP ports and let the user add what's found."""

    def __init__(self, parent, on_add):
        super().__init__(parent)
        self.title("Scan Network for RTSP Feeds")
        self.on_add = on_add
        self.cancel_event = threading.Event()
        self.result_queue: queue.Queue = queue.Queue()
        self.transient(parent)

        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=8)
        ttk.Label(top, text="Subnet (CIDR)").pack(side="left")
        self.subnet_var = tk.StringVar(value=str(scanner.local_network()))
        ttk.Entry(top, textvariable=self.subnet_var, width=18).pack(side="left", padx=(4, 12))
        ttk.Label(top, text="Port").pack(side="left")
        self.port_var = tk.StringVar(value=str(scanner.DEFAULT_RTSP_PORT))
        ttk.Entry(top, textvariable=self.port_var, width=6).pack(side="left", padx=4)
        self.scan_btn = ttk.Button(top, text="Scan", command=self._start_scan)
        self.scan_btn.pack(side="left", padx=(12, 0))

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", padx=10, pady=(0, 8))

        self.status_var = tk.StringVar(value="Enter a subnet and click Scan. Custom ports are supported.")
        ttk.Label(self, textvariable=self.status_var).pack(anchor="w", padx=10)

        cols = ("ip", "port", "rtsp", "server")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=10, selectmode="browse")
        for c, label, w in (
            ("ip", "IP Address", 140), ("port", "Port", 60),
            ("rtsp", "RTSP Confirmed", 110), ("server", "Server", 160),
        ):
            self.tree.heading(c, text=label)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=10, pady=8)
        self.tree.bind("<Double-1>", lambda e: self._add_selected())

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(btns, text="Add Selected…", command=self._add_selected).pack(side="left")
        ttk.Button(btns, text="Close", command=self._close).pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._close)
        self._poll_job = self.after(100, self._poll_results)

    def _start_scan(self):
        try:
            network = ipaddress.ip_network(self.subnet_var.get().strip(), strict=False)
        except ValueError:
            messagebox.showerror(
                "Invalid subnet", "Enter a subnet in CIDR form, e.g. 192.168.1.0/24", parent=self
            )
            return
        try:
            port = int(self.port_var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid port", "Port must be a number.", parent=self)
            return

        if network.num_addresses > 4096 and not messagebox.askyesno(
            "Large subnet",
            f"{network} has {network.num_addresses} addresses — this may take a while. Continue?",
            parent=self,
        ):
            return

        for item in self.tree.get_children():
            self.tree.delete(item)
        self.cancel_event = threading.Event()
        self.scan_btn.config(text="Cancel", command=self._cancel_scan)
        self.progress.config(value=0, maximum=max(network.num_addresses - 2, 1))
        self.status_var.set(f"Scanning {network} on port {port}…")

        cancel_event = self.cancel_event

        def progress_cb(done, total):
            self.result_queue.put(("progress", done, total))

        def worker():
            results = scanner.scan(
                network=network, port=port, progress_callback=progress_cb, cancel_event=cancel_event,
            )
            self.result_queue.put(("done", results))

        threading.Thread(target=worker, daemon=True).start()

    def _cancel_scan(self):
        self.cancel_event.set()
        self.status_var.set("Cancelling…")

    def _poll_results(self):
        try:
            while True:
                kind, *payload = self.result_queue.get_nowait()
                if kind == "progress":
                    done, total = payload
                    self.progress.config(value=done, maximum=max(total, 1))
                    self.status_var.set(f"Scanned {done}/{total}…")
                elif kind == "done":
                    (results,) = payload
                    self.scan_btn.config(text="Scan", command=self._start_scan)
                    self.status_var.set(f"Found {len(results)} open host(s).")
                    for r in results:
                        confirmed = "Yes" if r["rtsp_confirmed"] else "maybe"
                        self.tree.insert(
                            "", "end", iid=f"{r['ip']}:{r['port']}",
                            values=(r["ip"], r["port"], confirmed, r.get("server", "")),
                        )
        except queue.Empty:
            pass
        if self.winfo_exists():
            self._poll_job = self.after(150, self._poll_results)

    def _add_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("No selection", "Select a discovered host first.", parent=self)
            return
        ip, port = self.tree.item(sel[0], "values")[0:2]
        self.on_add(ip, int(port))

    def _close(self):
        self.cancel_event.set()
        if self._poll_job:
            try:
                self.after_cancel(self._poll_job)
            except Exception:
                pass
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RTSP → NDI")
        self.geometry("900x430")
        self.minsize(700, 320)

        self.status_queue: queue.Queue = queue.Queue()
        self.manager = CameraManager(on_status=self._on_worker_status)

        self._build_ui()
        self._refresh_list()
        self.after(200, self._poll_status_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # -- layout ---------------------------------------------------------------

    def _build_ui(self):
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=8, pady=6)
        ttk.Button(toolbar, text="Add Feed…", command=self._open_add_dialog).pack(side="left")
        ttk.Button(toolbar, text="Scan Network…", command=self._open_scan_dialog).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Start All", command=self._start_all).pack(side="left", padx=(20, 6))
        ttk.Button(toolbar, text="Stop All", command=self._stop_all).pack(side="left")

        cols = ("name", "status", "detail", "url", "latency", "retries")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", selectmode="browse")
        headers = {
            "name": ("NDI Name", 160), "status": ("Status", 100), "detail": ("Detail", 230),
            "url": ("RTSP URL", 230), "latency": ("Latency", 70), "retries": ("Retries", 60),
        }
        for c, (label, w) in headers.items():
            self.tree.heading(c, text=label)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=8, pady=(0, 6))
        self.tree.tag_configure("error", foreground="#c62828")
        self.tree.tag_configure("ok", foreground="#2e7d32")
        self.tree.tag_configure("busy", foreground="#c98a00")
        self.tree.tag_configure("idle", foreground="#888888")
        self.tree.bind("<Double-1>", lambda e: self._open_edit_dialog())

        actions = ttk.Frame(self)
        actions.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(actions, text="Start", command=self._start_selected).pack(side="left")
        ttk.Button(actions, text="Stop", command=self._stop_selected).pack(side="left", padx=6)
        ttk.Button(actions, text="Restart", command=self._restart_selected).pack(side="left")
        ttk.Button(actions, text="Rename…", command=self._rename_selected).pack(side="left", padx=6)
        ttk.Button(actions, text="Edit…", command=self._open_edit_dialog).pack(side="left")
        ttk.Button(actions, text="Remove", command=self._remove_selected).pack(side="left", padx=6)

        self.status_bar = ttk.Label(self, anchor="w", relief="sunken")
        self.status_bar.pack(fill="x", side="bottom")

    # -- status plumbing --------------------------------------------------------

    def _on_worker_status(self, cam_id, status, detail):
        # Called from a background bridge thread — hand off to the GUI thread.
        self.status_queue.put((cam_id, status, detail))

    def _poll_status_queue(self):
        updated = False
        try:
            while True:
                cam_id, status, detail = self.status_queue.get_nowait()
                self._apply_status(cam_id, status, detail)
                updated = True
        except queue.Empty:
            pass
        if updated:
            self._update_status_bar()
        self.after(200, self._poll_status_queue)

    def _apply_status(self, cam_id, status, detail):
        if not self.tree.exists(cam_id):
            return
        self.tree.set(cam_id, "status", STATUS_LABELS.get(status, status))
        self.tree.set(cam_id, "detail", detail)
        if status == "error":
            tag = "error"
        elif status in ("connected", "streaming"):
            tag = "ok"
        elif status in ("starting", "connecting", "retrying"):
            tag = "busy"
        else:
            tag = "idle"
        self.tree.item(cam_id, tags=(tag,))

    def _update_status_bar(self):
        total = len(self.manager.list())
        running = sum(1 for w in self.manager.workers.values() if w.is_running)
        self.status_bar.config(text=f"{total} feed(s) configured — {running} running")

    def _refresh_list(self):
        selected = self.tree.selection()
        for item in self.tree.get_children():
            self.tree.delete(item)
        for cam in self.manager.list():
            status, detail = self.manager.status(cam["id"])
            retries = "∞" if cam.get("retries", 3) == 0 else str(cam.get("retries", 3))
            self.tree.insert(
                "", "end", iid=cam["id"],
                values=(cam["name"], STATUS_LABELS.get(status, status), detail,
                        cam["url"], cam.get("latency", "low"), retries),
            )
            self._apply_status(cam["id"], status, detail)
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected[0])
        self._update_status_bar()

    def _selected_id(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _require_selection(self):
        cam_id = self._selected_id()
        if not cam_id:
            messagebox.showinfo("No feed selected", "Select a feed first.", parent=self)
        return cam_id

    # -- toolbar actions ---------------------------------------------------

    def _open_add_dialog(self, initial=None):
        def on_submit(values):
            self.manager.add(values["name"], values["url"], values["retries"], values["latency"])
            self._refresh_list()

        FeedDialog(self, "Add Feed", initial=initial, on_submit=on_submit)

    def _open_scan_dialog(self):
        def on_add(ip, port):
            self._open_add_dialog(initial={
                "name": f"Camera {ip}",
                "host": ip, "port": port, "path": "",
                "username": "", "password": "",
                "latency": "low", "retries": 3,
            })

        ScanDialog(self, on_add=on_add)

    def _start_all(self):
        self.manager.start_all()
        self._refresh_list()

    def _stop_all(self):
        self.manager.stop_all()
        self._refresh_list()

    # -- row actions ---------------------------------------------------------

    def _start_selected(self):
        cam_id = self._require_selection()
        if cam_id:
            self.manager.start(cam_id)

    def _stop_selected(self):
        cam_id = self._require_selection()
        if cam_id:
            self.manager.stop(cam_id)

    def _restart_selected(self):
        cam_id = self._require_selection()
        if cam_id:
            self.manager.restart(cam_id)

    def _rename_selected(self):
        cam_id = self._require_selection()
        if not cam_id:
            return
        cam = self.manager.get(cam_id)
        new_name = simpledialog.askstring(
            "Rename Feed", "New NDI feed name:", initialvalue=cam["name"], parent=self
        )
        if not new_name or new_name == cam["name"]:
            return
        try:
            self.manager.rename(cam_id, new_name)
        except ValueError as e:
            messagebox.showerror("Rename failed", str(e), parent=self)
            return
        self._refresh_list()

    def _open_edit_dialog(self):
        cam_id = self._require_selection()
        if not cam_id:
            return
        cam = self.manager.get(cam_id)
        initial = {
            "name": cam["name"], "url": cam["url"],
            "latency": cam.get("latency", "low"), "retries": cam.get("retries", 3),
        }
        initial.update(decompose_url(cam["url"]))

        def on_submit(values):
            self.manager.edit(
                cam_id, name=values["name"], url=values["url"],
                retries=values["retries"], latency=values["latency"],
            )
            self._refresh_list()

        FeedDialog(self, "Edit Feed", initial=initial, on_submit=on_submit)

    def _remove_selected(self):
        cam_id = self._require_selection()
        if not cam_id:
            return
        cam = self.manager.get(cam_id)
        if not messagebox.askyesno(
            "Remove feed", f"Remove '{cam['name']}'? This stops it and deletes it from the config.", parent=self
        ):
            return
        self.manager.remove(cam_id)
        self._refresh_list()

    def _on_close(self):
        self.manager.shutdown()
        self.destroy()


def main():
    try:
        app = App()
    except tk.TclError as e:
        print(f"ERROR: Could not start the GUI (no display / Tk not available): {e}")
        raise SystemExit(1)
    app.mainloop()


if __name__ == "__main__":
    main()
