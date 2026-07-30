"""
Advanced SMTP connection pool with:
- Multi-server support and auto rotation
- Per-connection proxy (no global socket monkey-patching)
- Weighted server selection based on live success rates
- Auto-cooldown and re-enable for failing servers
- Thread-safe connection reuse with RSET
"""
import smtplib
import ssl
import socket
import time
import threading
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple, Any

try:
    import socks
    SOCKS_AVAILABLE = True
except ImportError:
    SOCKS_AVAILABLE = False

logger = logging.getLogger(__name__)

PERMANENT_SMTP_ERRORS = {500, 501, 502, 503, 504, 550, 551, 552, 553, 554}
PROXY_TYPE_MAP = {}
if SOCKS_AVAILABLE:
    PROXY_TYPE_MAP = {
        "socks5": socks.SOCKS5,
        "socks4": socks.SOCKS4,
        "http": socks.HTTP,
    }


# ---------------------------------------------------------------------------
# Proxy-aware SMTP wrappers (NO global socket patching)
# ---------------------------------------------------------------------------

def _make_proxy_socket(proxy: Dict[str, Any]) -> "socks.socksocket":
    if not SOCKS_AVAILABLE:
        raise RuntimeError("PySocks not installed; cannot use proxy")
    auth = proxy.get("auth", {})
    ptype = PROXY_TYPE_MAP.get(proxy.get("type", "socks5").lower(), socks.SOCKS5)
    sock = socks.socksocket(socket.AF_INET, socket.SOCK_STREAM)
    sock.set_proxy(
        ptype,
        proxy["host"],
        int(proxy["port"]),
        username=auth.get("user") or None,
        password=auth.get("pass") or None,
    )
    return sock


class _ProxiedSMTP(smtplib.SMTP):
    """SMTP subclass that routes the initial connection through a SOCKS proxy."""

    def __init__(self, host, port, proxy_config=None, timeout=15, local_hostname=None):
        self._proxy_config = proxy_config
        super().__init__(host, port, local_hostname=local_hostname, timeout=timeout)

    def _get_socket(self, host, port, timeout):
        if self._proxy_config:
            sock = _make_proxy_socket(self._proxy_config)
            sock.settimeout(timeout)
            sock.connect((host, port))
            return sock
        return super()._get_socket(host, port, timeout)


class _ProxiedSMTP_SSL(smtplib.SMTP_SSL):
    """SMTP_SSL subclass that routes the initial connection through a SOCKS proxy."""

    def __init__(self, host, port, proxy_config=None, timeout=15,
                 local_hostname=None, context=None):
        self._proxy_config = proxy_config
        super().__init__(host, port, local_hostname=local_hostname,
                         timeout=timeout, context=context)

    def _get_socket(self, host, port, timeout):
        if self._proxy_config:
            sock = _make_proxy_socket(self._proxy_config)
            sock.settimeout(timeout)
            sock.connect((host, port))
            ctx = self._context
            if ctx is None:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            return ctx.wrap_socket(sock, server_hostname=host)
        return super()._get_socket(host, port, timeout)


def create_smtp_connection(
    smtp_config: Dict[str, Any],
    proxy_config: Optional[Dict[str, Any]] = None,
    timeout: int = 15,
) -> Optional[smtplib.SMTP]:
    """
    Create an authenticated SMTP connection, optionally through a proxy.
    Supports ports 25 (plain), 465 (SSL), and 587 (STARTTLS).
    Returns None on failure.
    """
    host = smtp_config.get("smtp_server", "")
    port = int(smtp_config.get("port", 587))
    username = smtp_config.get("username", "")
    password = smtp_config.get("password", "")

    try:
        if port == 465:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            server = _ProxiedSMTP_SSL(host, port, proxy_config=proxy_config,
                                      timeout=timeout, context=ctx)
        else:
            server = _ProxiedSMTP(host, port, proxy_config=proxy_config, timeout=timeout)
            server.ehlo_or_helo_if_needed()
            if port == 587:
                server.starttls()
                server.ehlo()

        if username:
            server.login(username, password)

        return server

    except Exception as e:
        logger.debug(f"SMTP connect failed {host}:{port} — {e}")
        return None


# ---------------------------------------------------------------------------
# Server entry with stats
# ---------------------------------------------------------------------------

@dataclass
class SMTPServerEntry:
    smtp_server: str
    port: int = 587
    username: str = ""
    password: str = ""
    from_email: str = ""
    enabled: bool = True

    # Live stats (not persisted)
    sent_count: int = field(default=0, init=False, repr=False)
    fail_count: int = field(default=0, init=False, repr=False)
    consecutive_failures: int = field(default=0, init=False, repr=False)
    total_latency_ms: float = field(default=0.0, init=False, repr=False)
    last_error: str = field(default="", init=False, repr=False)
    cooldown_until: float = field(default=0.0, init=False, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @property
    def success_rate(self) -> float:
        total = self.sent_count + self.fail_count
        return self.sent_count / total if total > 0 else 1.0

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.sent_count if self.sent_count > 0 else 9999.0

    @property
    def is_available(self) -> bool:
        return self.enabled and time.monotonic() > self.cooldown_until

    @property
    def effective_from(self) -> str:
        return self.from_email or self.username

    def record_success(self, latency_ms: float):
        with self._lock:
            self.sent_count += 1
            self.total_latency_ms += latency_ms
            self.consecutive_failures = 0

    def record_failure(self, error: str = ""):
        with self._lock:
            self.fail_count += 1
            self.consecutive_failures += 1
            self.last_error = error
            # Exponential backoff: 10s, 20s, 40s … max 300s
            if self.consecutive_failures >= 3:
                backoff = min(300.0, 10.0 * (2 ** (self.consecutive_failures - 3)))
                self.cooldown_until = time.monotonic() + backoff

    def to_dict(self) -> Dict[str, Any]:
        return {
            "smtp_server": self.smtp_server,
            "port": self.port,
            "username": self.username,
            "password": self.password,
            "from_email": self.from_email,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SMTPServerEntry":
        return cls(
            smtp_server=d.get("smtp_server", ""),
            port=int(d.get("port", 587)),
            username=d.get("username", ""),
            password=d.get("password", ""),
            from_email=d.get("from_email", ""),
            enabled=d.get("enabled", True),
        )


# ---------------------------------------------------------------------------
# Pooled connection wrapper
# ---------------------------------------------------------------------------

class PooledConnection:
    __slots__ = ("conn", "server_idx", "created_at", "use_count", "last_used", "alive")

    def __init__(self, conn: smtplib.SMTP, server_idx: int):
        self.conn = conn
        self.server_idx = server_idx
        self.created_at = time.monotonic()
        self.use_count = 0
        self.last_used = time.monotonic()
        self.alive = True

    def ping(self) -> bool:
        try:
            if self.conn.sock is None:
                self.alive = False
                return False
            code = self.conn.noop()[0]
            return code == 250
        except Exception:
            self.alive = False
            return False

    def reset(self) -> bool:
        """RSET the connection for reuse."""
        try:
            self.conn.rset()
            self.last_used = time.monotonic()
            return True
        except Exception:
            self.alive = False
            return False

    def close(self):
        try:
            self.conn.quit()
        except Exception:
            pass
        finally:
            self.alive = False


# ---------------------------------------------------------------------------
# Smart multi-server pool
# ---------------------------------------------------------------------------

class SmartSMTPPool:
    """
    Thread-safe multi-server SMTP pool.
    - Each server gets its own deque of idle connections.
    - Server selection is weighted by live success rate.
    - Failing servers enter an exponential-backoff cooldown.
    - Health maintenance runs on a background daemon thread.
    """

    def __init__(
        self,
        smtp_configs: List[Dict[str, Any]],
        proxy_manager=None,
        rotation: str = "weighted",
        max_conns_per_server: int = 10,
        max_reuse: int = 200,
        max_age: int = 600,
        timeout: int = 15,
    ):
        self.servers: List[SMTPServerEntry] = [
            SMTPServerEntry.from_dict(c) for c in smtp_configs
        ]
        self.proxy_manager = proxy_manager
        self.rotation = rotation
        self.max_conns = max_conns_per_server
        self.max_reuse = max_reuse
        self.max_age = max_age
        self.timeout = timeout

        n = len(self.servers)
        self._pools: List[deque] = [deque() for _ in range(n)]
        self._locks: List[threading.Lock] = [threading.Lock() for _ in range(n)]
        self._rr_index = 0
        self._global_lock = threading.Lock()

        # Aggregate counters
        self.total_sent = 0
        self.total_failed = 0
        self._cnt_lock = threading.Lock()

        self._running = True
        self._monitor = threading.Thread(target=self._health_loop, daemon=True)
        self._monitor.start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_connection(self) -> Optional[Tuple[PooledConnection, int]]:
        """
        Acquire a connection from the best available server.
        Returns (PooledConnection, server_index) or None if unavailable.
        """
        idx = self._pick_server()
        if idx is None:
            return None
        return self._acquire(idx)

    def release_connection(
        self,
        conn: PooledConnection,
        server_idx: int,
        success: bool,
        latency_ms: float = 0.0,
        error: str = "",
    ):
        """Return a connection to the pool (or discard if unhealthy)."""
        server = self.servers[server_idx]
        if success:
            server.record_success(latency_ms)
            with self._cnt_lock:
                self.total_sent += 1
            conn.use_count += 1
            # Try to recycle
            if conn.use_count < self.max_reuse and conn.alive and conn.reset():
                with self._locks[server_idx]:
                    if len(self._pools[server_idx]) < self.max_conns:
                        self._pools[server_idx].append(conn)
                        return
        else:
            server.record_failure(error)
            with self._cnt_lock:
                self.total_failed += 1
        conn.close()

    def test_server(self, smtp_config: Dict[str, Any]) -> Tuple[bool, str]:
        """Test a single SMTP config. Returns (ok, message)."""
        try:
            conn = create_smtp_connection(smtp_config, timeout=10)
            if conn:
                conn.quit()
                return True, "Connection successful"
            return False, "Failed to connect"
        except Exception as e:
            return False, str(e)

    def shutdown(self):
        self._running = False
        for i, pool in enumerate(self._pools):
            with self._locks[i]:
                while pool:
                    pool.popleft().close()

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_sent": self.total_sent,
            "total_failed": self.total_failed,
            "servers": [
                {
                    "host": s.smtp_server,
                    "port": s.port,
                    "username": s.username,
                    "from_email": s.effective_from,
                    "sent": s.sent_count,
                    "failed": s.fail_count,
                    "success_rate": round(s.success_rate * 100, 1),
                    "avg_latency_ms": round(s.avg_latency_ms, 1),
                    "status": self._server_status(s),
                    "last_error": s.last_error,
                    "pool_size": len(self._pools[i]),
                }
                for i, s in enumerate(self.servers)
            ],
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _server_status(self, s: SMTPServerEntry) -> str:
        if not s.enabled:
            return "disabled"
        if time.monotonic() < s.cooldown_until:
            remaining = int(s.cooldown_until - time.monotonic())
            return f"cooldown {remaining}s"
        return "active"

    def _pick_server(self) -> Optional[int]:
        available = [i for i, s in enumerate(self.servers) if s.is_available]
        if not available:
            # Re-enable servers whose cooldown has expired
            for s in self.servers:
                if s.enabled and time.monotonic() > s.cooldown_until:
                    s.cooldown_until = 0
            available = [i for i, s in enumerate(self.servers) if s.is_available]
        if not available:
            return None

        if self.rotation == "random":
            import random
            return random.choice(available)

        if self.rotation == "weighted":
            import random
            weights = [max(0.01, self.servers[i].success_rate) for i in available]
            return random.choices(available, weights=weights, k=1)[0]

        # round_robin (default)
        with self._global_lock:
            idx = available[self._rr_index % len(available)]
            self._rr_index += 1
        return idx

    def _acquire(self, server_idx: int) -> Optional[Tuple[PooledConnection, int]]:
        """Get or create a connection for the given server index."""
        now = time.monotonic()
        with self._locks[server_idx]:
            pool = self._pools[server_idx]
            while pool:
                conn = pool.popleft()
                if (conn.alive
                        and conn.use_count < self.max_reuse
                        and (now - conn.created_at) < self.max_age
                        and conn.ping()):
                    return conn, server_idx
                else:
                    conn.close()

        # No usable idle connection; create a new one
        server = self.servers[server_idx]
        proxy = self.proxy_manager.get_proxy() if self.proxy_manager else None
        raw = create_smtp_connection(server.to_dict(), proxy_config=proxy, timeout=self.timeout)
        if raw:
            return PooledConnection(raw, server_idx), server_idx

        server.record_failure("Connection creation failed")
        with self._cnt_lock:
            self.total_failed += 1
        return None

    def _health_loop(self):
        """Background: evict stale/dead idle connections."""
        while self._running:
            now = time.monotonic()
            for i in range(len(self.servers)):
                with self._locks[i]:
                    fresh = deque()
                    while self._pools[i]:
                        c = self._pools[i].popleft()
                        if (c.alive
                                and c.use_count < self.max_reuse
                                and (now - c.created_at) < self.max_age):
                            fresh.append(c)
                        else:
                            c.close()
                    self._pools[i] = fresh
            time.sleep(30)
