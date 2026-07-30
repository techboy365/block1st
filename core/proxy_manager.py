"""
Advanced proxy manager with:
- Per-connection proxy (thread-safe, no global socket patching)
- Multiple rotation strategies: round_robin, random, weighted
- Background health checking with latency tracking
- Multi-format import: IP:PORT, IP:PORT:USER:PASS, JSON
- Auto-exclusion of consistently failing proxies
"""
import socket
import time
import threading
import logging
import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    import socks
    SOCKS_AVAILABLE = True
except ImportError:
    SOCKS_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class ProxyEntry:
    host: str
    port: int
    proxy_type: str = "socks5"       # socks5 | socks4 | http
    username: str = ""
    password: str = ""

    # Live stats
    latency_ms: float = field(default=9999.0, init=False, repr=False)
    success_count: int = field(default=0, init=False, repr=False)
    fail_count: int = field(default=0, init=False, repr=False)
    alive: bool = field(default=True, init=False, repr=False)
    last_checked: float = field(default=0.0, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        return self.success_count / total if total > 0 else 1.0

    @property
    def label(self) -> str:
        return f"{self.host}:{self.port}"

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "host": self.host,
            "port": self.port,
            "type": self.proxy_type,
        }
        if self.username:
            d["auth"] = {"user": self.username, "pass": self.password}
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ProxyEntry":
        auth = d.get("auth", {})
        return cls(
            host=d.get("host", ""),
            port=int(d.get("port", 1080)),
            proxy_type=d.get("type", "socks5").lower(),
            username=auth.get("user", d.get("username", "")),
            password=auth.get("pass", d.get("password", "")),
        )

    @classmethod
    def from_string(cls, s: str, default_type: str = "socks5") -> Optional["ProxyEntry"]:
        """
        Parse common proxy string formats:
          - IP:PORT
          - IP:PORT:USER:PASS
          - socks5://user:pass@host:port
          - http://host:port
        """
        s = s.strip()
        if not s or s.startswith("#"):
            return None

        # URI format
        uri_match = re.match(
            r"^(socks[45]?|http)://(?:([^:@]+):([^@]*)@)?([^:]+):(\d+)$", s, re.IGNORECASE
        )
        if uri_match:
            ptype, user, pwd, host, port = uri_match.groups()
            return cls(
                host=host,
                port=int(port),
                proxy_type=ptype.lower().replace("socks", "socks"),
                username=user or "",
                password=pwd or "",
            )

        # Plain formats
        parts = s.split(":")
        if len(parts) == 2:
            return cls(host=parts[0], port=int(parts[1]), proxy_type=default_type)
        if len(parts) == 4:
            return cls(
                host=parts[0],
                port=int(parts[1]),
                proxy_type=default_type,
                username=parts[2],
                password=parts[3],
            )
        return None


def validate_proxy(proxy: ProxyEntry, test_host: str = "8.8.8.8", test_port: int = 53,
                   timeout: int = 8) -> float:
    """
    Test connectivity through the proxy.
    Returns latency in ms, or -1 on failure.
    Does NOT modify global sockets.
    """
    if not SOCKS_AVAILABLE:
        return -1
    try:
        proxy_type_map = {
            "socks5": socks.SOCKS5,
            "socks4": socks.SOCKS4,
            "http": socks.HTTP,
        }
        ptype = proxy_type_map.get(proxy.proxy_type, socks.SOCKS5)
        sock = socks.socksocket(socket.AF_INET, socket.SOCK_STREAM)
        sock.set_proxy(
            ptype,
            proxy.host,
            proxy.port,
            username=proxy.username or None,
            password=proxy.password or None,
        )
        sock.settimeout(timeout)
        start = time.monotonic()
        sock.connect((test_host, test_port))
        latency = (time.monotonic() - start) * 1000
        sock.close()
        return latency
    except Exception:
        return -1


class ProxyManager:
    """
    Thread-safe proxy pool with rotation, validation and health tracking.
    """

    def __init__(
        self,
        proxy_list: List[Dict[str, Any]],
        rotation: str = "round_robin",
        auto_validate: bool = False,
        validate_workers: int = 20,
    ):
        self.proxies: List[ProxyEntry] = [ProxyEntry.from_dict(p) for p in proxy_list]
        self.rotation = rotation
        self._rr_index = 0
        self._lock = threading.Lock()

        if auto_validate and self.proxies:
            self._start_validation(validate_workers)

    # ------------------------------------------------------------------
    # Rotation / acquisition
    # ------------------------------------------------------------------

    def get_proxy(self) -> Optional[Dict[str, Any]]:
        """Return a proxy config dict suitable for create_smtp_connection."""
        with self._lock:
            alive = [p for p in self.proxies if p.alive]
            if not alive:
                return None

            if self.rotation == "random":
                import random
                p = random.choice(alive)
            elif self.rotation == "weighted":
                import random
                weights = [max(0.01, p.success_rate) for p in alive]
                p = random.choices(alive, weights=weights, k=1)[0]
            else:  # round_robin
                p = alive[self._rr_index % len(alive)]
                self._rr_index += 1

        return p.to_dict()

    def mark_success(self, proxy_dict: Dict[str, Any]):
        entry = self._find(proxy_dict.get("host", ""), proxy_dict.get("port", 0))
        if entry:
            with entry._lock:
                entry.success_count += 1

    def mark_failure(self, proxy_dict: Dict[str, Any]):
        entry = self._find(proxy_dict.get("host", ""), proxy_dict.get("port", 0))
        if entry:
            with entry._lock:
                entry.fail_count += 1
                # Disable proxy after 5 consecutive failures tracked externally
                if entry.fail_count > 0 and entry.success_count == 0 and entry.fail_count >= 5:
                    entry.alive = False

    # ------------------------------------------------------------------
    # Import helpers
    # ------------------------------------------------------------------

    @staticmethod
    def parse_text(
        text: str,
        default_type: str = "socks5",
    ) -> List[ProxyEntry]:
        """Parse multi-line proxy text (IP:PORT or IP:PORT:USER:PASS)."""
        results = []
        for line in text.splitlines():
            entry = ProxyEntry.from_string(line, default_type=default_type)
            if entry:
                results.append(entry)
        return results

    def import_from_text(self, text: str, default_type: str = "socks5") -> int:
        """Add proxies from raw text. Returns count added."""
        entries = self.parse_text(text, default_type=default_type)
        with self._lock:
            existing = {(p.host, p.port) for p in self.proxies}
            added = 0
            for e in entries:
                if (e.host, e.port) not in existing:
                    self.proxies.append(e)
                    existing.add((e.host, e.port))
                    added += 1
        return added

    def clear(self):
        with self._lock:
            self.proxies.clear()

    def remove(self, index: int):
        with self._lock:
            if 0 <= index < len(self.proxies):
                self.proxies.pop(index)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_all(
        self,
        workers: int = 20,
        on_result: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """
        Validate all proxies in parallel.
        on_result(proxy_entry, latency_ms) called for each result.
        Returns summary dict.
        """
        import concurrent.futures

        results = {"alive": 0, "dead": 0, "total": len(self.proxies)}

        def check(p: ProxyEntry):
            lat = validate_proxy(p)
            with p._lock:
                p.last_checked = time.monotonic()
                if lat >= 0:
                    p.alive = True
                    p.latency_ms = lat
                    results["alive"] += 1
                else:
                    p.alive = False
                    p.latency_ms = 9999.0
                    results["dead"] += 1
            if on_result:
                on_result(p, lat)

        with self._lock:
            proxies_snapshot = list(self.proxies)

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(check, proxies_snapshot))

        return results

    def get_stats(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {
                    "host": p.host,
                    "port": p.port,
                    "type": p.proxy_type,
                    "alive": p.alive,
                    "latency_ms": round(p.latency_ms, 1),
                    "success_rate": round(p.success_rate * 100, 1),
                    "success": p.success_count,
                    "fail": p.fail_count,
                }
                for p in self.proxies
            ]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _find(self, host: str, port: int) -> Optional[ProxyEntry]:
        with self._lock:
            for p in self.proxies:
                if p.host == host and p.port == port:
                    return p
        return None

    def _start_validation(self, workers: int):
        t = threading.Thread(target=self.validate_all, kwargs={"workers": workers}, daemon=True)
        t.start()
