#!/usr/bin/env python3
"""
SSL VPN Detection Tool
======================
Identifies whether a supplied IP address or domain hosts a Fortinet SSL VPN
or Cisco SSL VPN web portal.

Usage
-----
  # Targets as arguments
  python3 vpn_checker.py 192.168.1.10 vpn.example.com 203.0.113.50

  # Targets from a file (one per line, # comments ignored)
  python3 vpn_checker.py --input targets.txt

  # Custom options
  python3 vpn_checker.py --input targets.txt --timeout 15 --retries 2 --retry-delay 3 -v

Options
-------
  TARGET                IP addresses or domains to scan
  -i/--input FILE       File containing one target per line
  --timeout SECONDS     HTTP request timeout (default: 10)
  --retries N           Retry attempts per failed request (default: 3)
  --retry-delay SECONDS Delay between retries in seconds (default: 2)
  --fortinet-out FILE   Output file for Fortinet hits (default: fortinet.txt)
  --cisco-out FILE      Output file for Cisco hits (default: cisco.txt)
  -v/--verbose          Enable debug logging

Dependencies
------------
  Python 3.6+ standard library only — no third-party packages required.
"""

import argparse
import http.client
import logging
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Detection configuration
# ---------------------------------------------------------------------------

FORTINET_PATH = "/remote/login?lang=en"
CISCO_PATH = "/+CSCOE+/logon.html"

FORTINET_INDICATORS = ["fortinet", "fortigate", "fortissl", "forticlient"]
CISCO_INDICATORS = ["cisco", "webvpn", "cscoe"]

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT = 10
DEFAULT_RETRIES = 3
DEFAULT_RETRY_DELAY = 2.0
FORTINET_OUTPUT = "fortinet.txt"
CISCO_OUTPUT = "cisco.txt"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TLS context — skip certificate verification for self-signed VPN appliances
# ---------------------------------------------------------------------------

_SSL_CTX = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def normalize_target(target: str) -> str:
    """Return a fully-qualified HTTPS URL for *target*.

    Plain hostnames and IPs are prefixed with ``https://``.
    Targets that already carry a scheme are returned unchanged (trailing
    slash stripped).
    """
    target = target.strip()
    if not target:
        raise ValueError("Empty target")
    if "://" in target:
        return target.rstrip("/")
    return f"https://{target}"


def http_get(url: str, timeout: int) -> tuple[int, str]:
    """Perform an HTTP GET for *url* and return ``(status_code, body)``.

    Uses a permissive TLS context so self-signed certificates are accepted.
    Raises :class:`urllib.error.URLError` / :class:`OSError` on network
    failures.
    """
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; VPN-Checker/1.0)"},
    )
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        return resp.status, body


def fetch_with_retry(
    url: str,
    timeout: int,
    retries: int,
    retry_delay: float,
) -> tuple[int, str] | None:
    """Fetch *url*, retrying up to *retries* times on failure.

    Returns ``(status_code, body)`` on success or ``None`` after all
    attempts are exhausted.
    """
    max_attempts = retries + 1
    for attempt in range(1, max_attempts + 1):
        try:
            return http_get(url, timeout)
        except urllib.error.HTTPError as exc:
            # HTTPError carries a real HTTP status — return it directly so
            # callers can decide whether it is a hit (unlikely at 4xx/5xx).
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            return exc.code, body
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            if attempt < max_attempts:
                logger.warning(
                    "Attempt %d/%d failed for %s: %s — retrying in %.1fs",
                    attempt,
                    max_attempts,
                    url,
                    exc,
                    retry_delay,
                )
                time.sleep(retry_delay)
            else:
                logger.error(
                    "All %d attempt(s) failed for %s: %s",
                    max_attempts,
                    url,
                    exc,
                )
    return None


def body_contains(body: str, indicators: list) -> bool:
    """Return True if *body* contains any indicator (case-insensitive)."""
    lower = body.lower()
    return any(ind.lower() in lower for ind in indicators)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def check_fortinet(base_url: str, timeout: int, retries: int, retry_delay: float) -> bool:
    url = base_url + FORTINET_PATH
    result = fetch_with_retry(url, timeout, retries, retry_delay)
    if result is None:
        return False
    status, body = result
    if status != 200:
        logger.debug("Fortinet check: %s returned HTTP %d", url, status)
        return False
    if body_contains(body, FORTINET_INDICATORS):
        logger.info("Fortinet SSL VPN detected at %s", base_url)
        return True
    return False


def check_cisco(base_url: str, timeout: int, retries: int, retry_delay: float) -> bool:
    url = base_url + CISCO_PATH
    result = fetch_with_retry(url, timeout, retries, retry_delay)
    if result is None:
        return False
    status, body = result
    if status != 200:
        logger.debug("Cisco check: %s returned HTTP %d", url, status)
        return False
    if body_contains(body, CISCO_INDICATORS):
        logger.info("Cisco SSL VPN detected at %s", base_url)
        return True
    return False


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def load_existing(path: str) -> set:
    p = Path(path)
    if not p.exists():
        return set()
    return {line.strip() for line in p.read_text().splitlines() if line.strip()}


def record_hit(path: str, url: str, seen: set) -> None:
    """Append *url* to *path* once, skipping duplicates."""
    if url in seen:
        return
    seen.add(url)
    with open(path, "a") as fh:
        fh.write(url + "\n")
    logger.info("Written to %s: %s", path, url)


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------


def scan(
    targets: list,
    timeout: int,
    retries: int,
    retry_delay: float,
    fortinet_out: str,
    cisco_out: str,
) -> tuple[list, list]:
    fortinet_seen = load_existing(fortinet_out)
    cisco_seen = load_existing(cisco_out)

    fortinet_hits = []
    cisco_hits = []
    total = len(targets)

    for idx, raw in enumerate(targets, 1):
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue

        try:
            base_url = normalize_target(raw)
        except ValueError as exc:
            logger.warning("Skipping invalid target %r: %s", raw, exc)
            continue

        logger.info("[%d/%d] Scanning %s", idx, total, base_url)

        if check_fortinet(base_url, timeout, retries, retry_delay):
            record_hit(fortinet_out, base_url, fortinet_seen)
            fortinet_hits.append(base_url)
            continue  # per spec: skip Cisco check if already Fortinet

        if check_cisco(base_url, timeout, retries, retry_delay):
            record_hit(cisco_out, base_url, cisco_seen)
            cisco_hits.append(base_url)

    return fortinet_hits, cisco_hits


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Detect Fortinet and Cisco SSL VPN portals",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "targets",
        nargs="*",
        metavar="TARGET",
        help="IP addresses or domains to scan",
    )
    parser.add_argument(
        "-i", "--input",
        metavar="FILE",
        help="File containing one target per line",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        metavar="SECONDS",
        help="HTTP request timeout in seconds",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        metavar="N",
        help="Retry attempts per failed request",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=DEFAULT_RETRY_DELAY,
        metavar="SECONDS",
        help="Delay in seconds between retries",
    )
    parser.add_argument(
        "--fortinet-out",
        default=FORTINET_OUTPUT,
        metavar="FILE",
        help="Output file for detected Fortinet portals",
    )
    parser.add_argument(
        "--cisco-out",
        default=CISCO_OUTPUT,
        metavar="FILE",
        help="Output file for detected Cisco portals",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug-level logging",
    )
    return parser.parse_args(argv)


def collect_targets(args) -> list:
    targets = list(args.targets)

    if args.input:
        p = Path(args.input)
        if not p.exists():
            logger.error("Input file not found: %s", args.input)
            sys.exit(1)
        targets.extend(
            line.strip()
            for line in p.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        )

    if not targets:
        logger.error("No targets supplied. Use positional arguments or --input FILE.")
        sys.exit(1)

    # Deduplicate while preserving order
    seen: set = set()
    unique = []
    for t in targets:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def main(argv=None):
    args = parse_args(argv)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    targets = collect_targets(args)
    logger.info(
        "Starting scan of %d target(s) — timeout=%ds retries=%d",
        len(targets),
        args.timeout,
        args.retries,
    )

    fortinet_hits, cisco_hits = scan(
        targets=targets,
        timeout=args.timeout,
        retries=args.retries,
        retry_delay=args.retry_delay,
        fortinet_out=args.fortinet_out,
        cisco_out=args.cisco_out,
    )

    print("\nScan complete.")
    print(f"  Fortinet SSL VPN portals found : {len(fortinet_hits)}")
    print(f"  Cisco SSL VPN portals found    : {len(cisco_hits)}")
    if fortinet_hits:
        print(f"  Fortinet results written to    : {args.fortinet_out}")
    if cisco_hits:
        print(f"  Cisco results written to       : {args.cisco_out}")


if __name__ == "__main__":
    main()
