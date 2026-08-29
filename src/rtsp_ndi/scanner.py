"""
Local-network RTSP discovery.

Scans a subnet (auto-detected by default) for hosts with an open RTSP port
(554 by default, but any port can be scanned — some cameras use a custom
port) and confirms real RTSP servers with a lightweight OPTIONS handshake.
No credentials or stream paths are guessed; the caller fills those in when
adding a discovered host as a feed.
"""

import concurrent.futures
import ipaddress
import socket
import threading

DEFAULT_RTSP_PORT = 554


def local_ip() -> str:
    """Best-effort local IPv4 address, found without needing real connectivity."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def local_network(prefix: int = 24) -> ipaddress.IPv4Network:
    return ipaddress.ip_network(f"{local_ip()}/{prefix}", strict=False)


def probe_rtsp(ip: str, port: int, timeout: float = 0.6) -> dict | None:
    """Return a result dict if `ip:port` is open, else None."""
    try:
        with socket.create_connection((ip, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            rtsp_confirmed = False
            server = ""
            try:
                sock.sendall(f"OPTIONS rtsp://{ip}:{port}/ RTSP/1.0\r\nCSeq: 1\r\n\r\n".encode())
                resp = sock.recv(512)
                if resp.startswith(b"RTSP/"):
                    rtsp_confirmed = True
                    for line in resp.split(b"\r\n"):
                        if line.lower().startswith(b"server:"):
                            server = line.split(b":", 1)[1].strip().decode(errors="replace")
            except OSError:
                pass
            return {"ip": ip, "port": port, "rtsp_confirmed": rtsp_confirmed, "server": server}
    except OSError:
        return None


def scan(
    network: ipaddress.IPv4Network | None = None,
    port: int = DEFAULT_RTSP_PORT,
    timeout: float = 0.6,
    max_workers: int = 128,
    progress_callback=None,
    cancel_event: threading.Event | None = None,
) -> list[dict]:
    """Scan `network` for open `port`. Returns results sorted by IP.

    `progress_callback(done, total)` is invoked as hosts finish, if given.
    Pass `cancel_event` to stop early — already-issued probes may still
    complete before the scan actually returns.
    """
    if network is None:
        network = local_network()

    hosts = [str(h) for h in network.hosts()]
    total = len(hosts)
    results: list[dict] = []
    done = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(probe_rtsp, ip, port, timeout): ip for ip in hosts}
        for future in concurrent.futures.as_completed(futures):
            done += 1
            if progress_callback:
                progress_callback(done, total)
            if cancel_event is not None and cancel_event.is_set():
                for f in futures:
                    f.cancel()
                break
            result = future.result()
            if result:
                results.append(result)

    results.sort(key=lambda r: tuple(int(p) for p in r["ip"].split(".")))
    return results
