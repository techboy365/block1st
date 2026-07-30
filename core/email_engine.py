"""
High-performance email sending engine.

Architecture:
  - Single shared work queue populated once with all recipients.
  - N worker threads pull from queue; each handles retries independently.
  - Pause/stop via threading.Event.
  - Callback-based status reporting (GUI-friendly, called from worker threads).
  - Exchange (OWA) mode supported alongside SMTP.
"""
import queue
import threading
import time
import smtplib
import logging
import itertools
from typing import Any, Callable, Dict, List, Optional

from core.smtp_pool import SmartSMTPPool, PERMANENT_SMTP_ERRORS
from core.proxy_manager import ProxyManager
from core.message_builder import build_email, replace_placeholders

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Thread-safe atomic counter
# ---------------------------------------------------------------------------

class _AtomicInt:
    def __init__(self, initial: int = 0):
        self._v = initial
        self._lock = threading.Lock()

    def inc(self, by: int = 1) -> int:
        with self._lock:
            self._v += by
            return self._v

    def get(self) -> int:
        return self._v

    def reset(self, v: int = 0):
        with self._lock:
            self._v = v


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class EmailEngine:
    """
    Orchestrates multi-threaded bulk email sending.

    Callbacks (all called from worker threads — schedule GUI updates via after()):
      on_progress(sent, failed, total)
      on_log(level, message)          level ∈ 'INFO' | 'WARNING' | 'ERROR'
      on_complete(sent, failed, total, duration_s)
    """

    def __init__(self):
        self._smtp_pool: Optional[SmartSMTPPool] = None
        self._proxy_manager: Optional[ProxyManager] = None
        self._config: Dict[str, Any] = {}
        self._links_list: List[str] = []

        self._work_queue: queue.Queue = queue.Queue()
        self._running = False
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # initially not paused

        self._workers: List[threading.Thread] = []
        self._sent = _AtomicInt()
        self._failed = _AtomicInt()
        self._total = 0
        self._start_time = 0.0

        # Callbacks
        self.on_progress: Optional[Callable] = None
        self.on_log: Optional[Callable] = None
        self.on_complete: Optional[Callable] = None

    # ------------------------------------------------------------------
    # Public control API
    # ------------------------------------------------------------------

    def configure(
        self,
        config: Dict[str, Any],
        smtp_pool: SmartSMTPPool,
        proxy_manager: Optional[ProxyManager] = None,
        links_list: Optional[List[str]] = None,
    ):
        self._config = config
        self._smtp_pool = smtp_pool
        self._proxy_manager = proxy_manager
        self._links_list = links_list or []

    def start(self, recipients: List[str]):
        if self._running:
            return

        # Drain any leftover items
        while not self._work_queue.empty():
            try:
                self._work_queue.get_nowait()
            except queue.Empty:
                break

        for r in recipients:
            self._work_queue.put(r)

        self._total = len(recipients)
        self._sent.reset()
        self._failed.reset()
        self._start_time = time.monotonic()
        self._running = True
        self._stop_event.clear()
        self._pause_event.set()

        num_workers = max(1, self._config.get("num_threads", 50))

        if self._config.get("use_exchange", False):
            self._start_exchange_workers(num_workers)
        else:
            self._start_smtp_workers(num_workers)

        # Watchdog thread closes out when queue empties
        t = threading.Thread(target=self._watchdog, daemon=True)
        t.start()

    def stop(self):
        self._stop_event.set()
        self._pause_event.set()  # unblock any paused workers
        self._running = False

    def pause(self):
        self._pause_event.clear()

    def resume(self):
        self._pause_event.set()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return not self._pause_event.is_set()

    def get_stats(self) -> Dict[str, Any]:
        elapsed = time.monotonic() - self._start_time if self._start_time else 0
        sent = self._sent.get()
        rate = sent / elapsed if elapsed > 0 else 0.0
        remaining = max(0, self._total - sent - self._failed.get())
        eta = remaining / rate if rate > 0 else 0
        return {
            "total": self._total,
            "sent": sent,
            "failed": self._failed.get(),
            "elapsed_s": round(elapsed, 1),
            "rate": round(rate, 2),
            "eta_s": round(eta, 1),
            "running": self._running,
            "paused": self.is_paused,
        }

    # ------------------------------------------------------------------
    # SMTP workers
    # ------------------------------------------------------------------

    def _start_smtp_workers(self, num_workers: int):
        self._workers = []
        for _ in range(num_workers):
            t = threading.Thread(target=self._smtp_worker, daemon=True)
            t.start()
            self._workers.append(t)

    def _smtp_worker(self):
        config = self._config
        max_retries = config.get("max_retries", 3)
        max_errors = config.get("max_errors_before_stop", 1000)

        while not self._stop_event.is_set():
            self._pause_event.wait()
            if self._stop_event.is_set():
                break

            try:
                recipient = self._work_queue.get(timeout=1)
            except queue.Empty:
                break

            try:
                self._send_smtp(recipient, max_retries, max_errors)
            finally:
                self._work_queue.task_done()

    def _send_smtp(self, recipient: str, max_retries: int, max_errors: int):
        last_error = ""
        for attempt in range(max_retries + 1):
            if self._stop_event.is_set():
                return
            if self._failed.get() >= max_errors:
                self._log("WARNING", f"Max error threshold reached, stopping")
                self.stop()
                return

            result = self._smtp_pool.get_connection()
            if result is None:
                time.sleep(0.2 * (attempt + 1))
                continue

            conn, server_idx = result
            server = self._smtp_pool.servers[server_idx]
            from_email = server.effective_from
            sender_name = self._config.get("sender_name", "")

            try:
                msg = build_email(
                    self._config,
                    recipient,
                    self._links_list,
                    from_email=from_email,
                    sender_name=sender_name,
                )
                t0 = time.monotonic()
                conn.conn.mail(from_email)
                conn.conn.rcpt(recipient)
                conn.conn.data(msg.encode() if isinstance(msg, str) else msg)
                latency = (time.monotonic() - t0) * 1000

                self._smtp_pool.release_connection(conn, server_idx, True, latency)
                self._sent.inc()
                self._report_progress()
                self._log("INFO", f"✓ {recipient}  ({latency:.0f} ms)  [{server.smtp_server}]")
                return

            except smtplib.SMTPResponseException as e:
                last_error = f"SMTP {e.smtp_code}: {e.smtp_error}"
                conn.alive = False
                self._smtp_pool.release_connection(conn, server_idx, False, error=last_error)
                if e.smtp_code in PERMANENT_SMTP_ERRORS:
                    break  # permanent rejection — no retry
            except (smtplib.SMTPServerDisconnected, ConnectionResetError, OSError) as e:
                last_error = str(e)
                conn.alive = False
                self._smtp_pool.release_connection(conn, server_idx, False, error=last_error)
            except Exception as e:
                last_error = str(e)
                conn.alive = False
                self._smtp_pool.release_connection(conn, server_idx, False, error=last_error)

        self._failed.inc()
        self._report_progress()
        self._log("ERROR", f"✗ {recipient}  — {last_error}")

    # ------------------------------------------------------------------
    # Exchange (OWA) workers
    # ------------------------------------------------------------------

    def _start_exchange_workers(self, num_workers: int):
        owas = self._config.get("exchange", {}).get("owas", [])
        if not owas:
            self._log("ERROR", "No Exchange (OWA) accounts configured")
            self.stop()
            return

        owa_cycle = itertools.cycle(owas)
        self._workers = []
        for _ in range(num_workers):
            t = threading.Thread(
                target=self._exchange_worker, args=(owa_cycle,), daemon=True
            )
            t.start()
            self._workers.append(t)

    def _exchange_worker(self, owa_cycle):
        delay = self._config.get("exchange", {}).get("sending_delay", 0.05)

        while not self._stop_event.is_set():
            self._pause_event.wait()
            if self._stop_event.is_set():
                break

            try:
                recipient = self._work_queue.get(timeout=1)
            except queue.Empty:
                break

            try:
                self._send_exchange(recipient, next(owa_cycle))
            finally:
                self._work_queue.task_done()
                time.sleep(delay)

    def _send_exchange(self, recipient: str, owa: Dict[str, Any]):
        try:
            from exchangelib import (
                Credentials, Configuration, Account, DELEGATE,
                HTMLBody, Message, Mailbox, FileAttachment,
            )
            from core.message_builder import generate_pdf_bytes, replace_placeholders

            credentials = Credentials(owa["username"], owa["password"])
            exch_cfg = Configuration(server=owa["server"], credentials=credentials)
            account = Account(
                primary_smtp_address=owa["username"],
                config=exch_cfg,
                autodiscover=False,
                access_type=DELEGATE,
            )
            subject = replace_placeholders(
                self._config.get("subject", ""), recipient, self._links_list
            )
            body = replace_placeholders(
                self._config.get("message_body", ""), recipient, self._links_list
            )
            message = Message(
                account=account,
                subject=subject,
                body=HTMLBody(body),
                to_recipients=[Mailbox(email_address=recipient)],
            )

            if self._config.get("html2pdf", False):
                import os
                html_file = replace_placeholders(
                    self._config.get("html2pdf_file", ""), recipient, self._links_list
                )
                if html_file and os.path.exists(html_file):
                    with open(html_file, "r", encoding="utf-8") as f:
                        html_content = f.read()
                    pdf = generate_pdf_bytes(
                        html_content, recipient, self._links_list,
                        self._config.get("wkhtmltopdf_path", ""),
                    )
                    if pdf:
                        attach_name = replace_placeholders(
                            self._config.get("html2pdf_attachment_name", "doc.pdf"),
                            recipient, self._links_list,
                        )
                        message.attach(FileAttachment(name=attach_name, content=pdf))

            message.send()
            self._sent.inc()
            self._report_progress()
            self._log("INFO", f"✓ [Exchange] {recipient}")

        except Exception as e:
            self._failed.inc()
            self._report_progress()
            self._log("ERROR", f"✗ [Exchange] {recipient}  — {e}")

    # ------------------------------------------------------------------
    # Watchdog
    # ------------------------------------------------------------------

    def _watchdog(self):
        self._work_queue.join()
        if self._running:
            self._running = False
            elapsed = time.monotonic() - self._start_time
            if self.on_complete:
                self.on_complete(
                    self._sent.get(), self._failed.get(), self._total, elapsed
                )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _report_progress(self):
        if self.on_progress:
            self.on_progress(self._sent.get(), self._failed.get(), self._total)

    def _log(self, level: str, msg: str):
        if self.on_log:
            self.on_log(level, msg)
        getattr(logger, level.lower(), logger.info)(msg)
