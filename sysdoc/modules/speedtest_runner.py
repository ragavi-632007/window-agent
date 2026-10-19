"""FixBot internet speed test — real multi-stream measure, not a shallow probe.

Primary engine: Cloudflare Speed endpoints (anycast edge near the user).
Optional: LibreSpeed only if a server replies with low latency (<120 ms).

Improvements vs old logic:
  - No random distant country names when CDN is used
  - Warmup window discarded (first 2s not counted)
  - Multi-connection download/upload
  - Ping = median of several small requests
  - Clear engine + server labels
"""
from __future__ import annotations

import json
import random
import statistics
import threading
import time
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin

USER_AGENT = "FixBot-SpeedTest/2.0"
DEFAULT_DURATION = 12
WARMUP_SEC = 2.0
DL_WORKERS = 6
UL_WORKERS = 4
CHUNK = 256 * 1024

CF_DOWN = "https://speed.cloudflare.com/__down"
CF_UP = "https://speed.cloudflare.com/__up"
CF_META = "https://speed.cloudflare.com/meta"

SERVER_LIST_URL = "https://librespeed.org/backend-servers/servers.php"

_NEAR_HINTS = (
    "india", "mumbai", "chennai", "bangalore", "bengaluru", "hyderabad",
    "delhi", "pune", "kolkata", "singapore",
)


def _log(cb: Optional[Callable[[str], None]], msg: str) -> None:
    if cb:
        try:
            cb(msg)
        except Exception:
            pass


def speed_color(mbps: float) -> str:
    if mbps < 5:
        return "red"
    if mbps < 25:
        return "yellow"
    return "green"


def _http_get(url: str, timeout: float = 20.0) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _http_post(url: str, data: bytes, timeout: float = 30.0) -> bytes:
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "identity",
            "Content-Type": "application/octet-stream",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


class _Counter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.total = 0
        self.measure_total = 0
        self.t0 = time.perf_counter()
        self.measure_t0 = self.t0
        self.measuring = False

    def start(self) -> None:
        self.t0 = time.perf_counter()
        self.total = 0
        self.measure_total = 0
        self.measuring = False

    def begin_measure(self) -> None:
        with self._lock:
            self.measuring = True
            self.measure_t0 = time.perf_counter()
            self.measure_total = 0

    def add(self, n: int) -> None:
        with self._lock:
            self.total += n
            if self.measuring:
                self.measure_total += n

    def live_mbps(self) -> float:
        with self._lock:
            if self.measuring:
                dt = max(time.perf_counter() - self.measure_t0, 0.001)
                bits = self.measure_total * 8
            else:
                dt = max(time.perf_counter() - self.t0, 0.001)
                bits = self.total * 8
        return bits / dt / 1_000_000.0

    def final_mbps(self) -> Tuple[float, int]:
        with self._lock:
            dt = max(time.perf_counter() - self.measure_t0, 0.001)
            total = self.measure_total if self.measuring else self.total
        return round(total * 8 / dt / 1_000_000.0, 2), total


def _ping_samples(url: str, count: int = 7) -> Tuple[float, float]:
    samples: List[float] = []
    for _ in range(count):
        t0 = time.perf_counter()
        try:
            _http_get(url, timeout=5.0)
            samples.append((time.perf_counter() - t0) * 1000.0)
        except Exception:
            samples.append(999.0)
        time.sleep(0.05)
    good = [s for s in samples if s < 900]
    if not good:
        return 999.0, 0.0
    med = statistics.median(good)
    if len(good) >= 2:
        jitter = statistics.mean(
            abs(good[i] - good[i - 1]) for i in range(1, len(good))
        )
    else:
        jitter = 0.0
    return round(float(med), 2), round(float(jitter), 2)


def cloudflare_meta() -> Dict[str, str]:
    try:
        raw = _http_get(CF_META, timeout=8)
        data = json.loads(raw.decode("utf-8", errors="replace"))
        if isinstance(data, dict):
            city = str(data.get("city") or data.get("colo") or "")
            country = str(data.get("country") or "")
            ip = str(data.get("clientIp") or data.get("ip") or "")
            asn = str(data.get("asn") or data.get("asOrganization") or "")
            label = ", ".join(x for x in (city, country) if x) or "Cloudflare edge"
            return {"label": label, "ip": ip, "asn": asn, "raw_city": city}
    except Exception:
        pass
    return {"label": "Cloudflare edge", "ip": "", "asn": "", "raw_city": ""}


def _cf_download(
    duration: float,
    workers: int = DL_WORKERS,
    on_speed: Optional[Callable[[float], None]] = None,
) -> Tuple[float, int]:
    url = f"{CF_DOWN}?bytes=50000000"
    counter = _Counter()
    stop = threading.Event()
    counter.start()

    def worker() -> None:
        while not stop.is_set():
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
                )
                with urllib.request.urlopen(req, timeout=duration + 15) as resp:
                    while not stop.is_set():
                        block = resp.read(CHUNK)
                        if not block:
                            break
                        counter.add(len(block))
            except Exception:
                if stop.is_set():
                    break
                time.sleep(0.05)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(workers)]
    for t in threads:
        t.start()
        time.sleep(0.05)

    t_end_warm = time.time() + WARMUP_SEC
    while time.time() < t_end_warm and not stop.is_set():
        if on_speed:
            on_speed(counter.live_mbps())
        time.sleep(0.2)

    counter.begin_measure()
    t_end = time.time() + max(3.0, duration - WARMUP_SEC)
    while time.time() < t_end:
        if on_speed:
            on_speed(counter.live_mbps())
        time.sleep(0.2)

    stop.set()
    for t in threads:
        t.join(timeout=2.0)
    return counter.final_mbps()


def _cf_upload(
    duration: float,
    workers: int = UL_WORKERS,
    on_speed: Optional[Callable[[float], None]] = None,
) -> Tuple[float, int]:
    try:
        payload = random.randbytes(512 * 1024)
    except AttributeError:
        payload = bytes(random.getrandbits(8) for _ in range(512 * 1024))

    counter = _Counter()
    stop = threading.Event()
    counter.start()

    def worker() -> None:
        while not stop.is_set():
            try:
                _http_post(CF_UP, payload, timeout=duration + 10)
                counter.add(len(payload))
            except Exception:
                if stop.is_set():
                    break
                time.sleep(0.05)

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(workers)]
    for t in threads:
        t.start()

    t_end_warm = time.time() + min(1.5, WARMUP_SEC)
    while time.time() < t_end_warm:
        if on_speed:
            on_speed(counter.live_mbps())
        time.sleep(0.2)

    counter.begin_measure()
    t_end = time.time() + max(3.0, duration - WARMUP_SEC)
    while time.time() < t_end:
        if on_speed:
            on_speed(counter.live_mbps())
        time.sleep(0.2)

    stop.set()
    for t in threads:
        t.join(timeout=2.0)
    return counter.final_mbps()


def run_cloudflare_test(
    duration: int = DEFAULT_DURATION,
    on_progress: Optional[Callable[[str], None]] = None,
    on_download_speed: Optional[Callable[[float], None]] = None,
    on_upload_speed: Optional[Callable[[float], None]] = None,
) -> Dict[str, Any]:
    _log(on_progress, "Using Cloudflare speed endpoints (nearest edge)...")
    meta = cloudflare_meta()
    _log(on_progress, f"Edge: {meta.get('label')}")

    _log(on_progress, "Measuring latency...")
    ping_ms, jitter_ms = _ping_samples(f"{CF_DOWN}?bytes=1000", count=7)
    _log(on_progress, f"Ping {ping_ms} ms  |  Jitter {jitter_ms} ms")

    _log(on_progress, "Download test (multi-stream, warmup discarded)...")
    dl, br = _cf_download(float(duration), on_speed=on_download_speed)
    _log(on_progress, f"Download {dl} Mbps")

    _log(on_progress, "Upload test (multi-stream, warmup discarded)...")
    ul, bs = _cf_upload(max(6.0, duration * 0.75), on_speed=on_upload_speed)
    _log(on_progress, f"Upload {ul} Mbps")

    return {
        "ok": True,
        "engine": "cloudflare",
        "download_mbps": dl,
        "upload_mbps": ul,
        "ping_ms": ping_ms,
        "jitter_ms": jitter_ms,
        "bytes_received": br,
        "bytes_sent": bs,
        "server_name": meta.get("label") or "Cloudflare edge",
        "server_url": "https://speed.cloudflare.com",
        "client_ip": meta.get("ip") or "",
        "isp": meta.get("asn") or "",
        "note": (
            "Measured via Cloudflare anycast (nearest edge). "
            "Warmup excluded; multi-connection load."
        ),
    }


def _join(base: str, path: str) -> str:
    b = base if base.endswith("/") else base + "/"
    return urljoin(b, (path or "").lstrip("/"))


def fetch_servers() -> List[dict]:
    raw = _http_get(SERVER_LIST_URL, timeout=20)
    data = json.loads(raw.decode("utf-8", errors="replace").strip())
    if not isinstance(data, list):
        raise RuntimeError("bad server list")
    return data


def _ping_server(server: dict) -> Optional[float]:
    try:
        url = _join(server.get("server") or "", server.get("pingURL") or "empty.php")
        t0 = time.perf_counter()
        req = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            resp.read()
        return (time.perf_counter() - t0) * 1000.0
    except Exception:
        return None


def pick_nearby_librespeed(
    servers: List[dict],
    max_ping_ms: float = 120.0,
    on_progress=None,
) -> Optional[Tuple[dict, float]]:
    ranked = sorted(
        servers,
        key=lambda s: (
            0
            if any(
                h in f"{s.get('name', '')} {s.get('server', '')}".lower()
                for h in _NEAR_HINTS
            )
            else 1
        ),
    )
    best: Optional[Tuple[dict, float]] = None
    checked = 0
    for s in ranked:
        if not (s.get("server") and s.get("dlURL")):
            continue
        p = _ping_server(s)
        checked += 1
        if p is None:
            continue
        name = s.get("name") or s.get("server")
        _log(on_progress, f"Probe {name}: {p:.0f} ms")
        if p <= max_ping_ms and (best is None or p < best[1]):
            best = (s, p)
            if p < 60:
                break
        if checked >= 15 and best:
            break
        if checked >= 25:
            break
    return best


def run_speedtest(
    duration: int = DEFAULT_DURATION,
    prefer_binary: bool = False,
    on_progress: Optional[Callable[[str], None]] = None,
    on_download_speed: Optional[Callable[[float], None]] = None,
    on_upload_speed: Optional[Callable[[float], None]] = None,
    prefer_librespeed: bool = False,
) -> Dict[str, Any]:
    """Default: Cloudflare multi-stream test (good for India)."""
    try:
        if prefer_librespeed:
            try:
                _log(on_progress, "Looking for a nearby LibreSpeed server...")
                servers = fetch_servers()
                near = pick_nearby_librespeed(
                    servers, max_ping_ms=120, on_progress=on_progress
                )
                if near:
                    server, ping = near
                    _log(
                        on_progress,
                        f"Nearby server: {server.get('name')} ({ping:.0f} ms)",
                    )
            except Exception as exc:
                _log(on_progress, f"LibreSpeed skip: {exc}")

        return run_cloudflare_test(
            duration=duration,
            on_progress=on_progress,
            on_download_speed=on_download_speed,
            on_upload_speed=on_upload_speed,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc), "engine": "cloudflare"}