#!/usr/bin/env python3
"""
SSL VPN Detection Tool

Identifies whether a supplied IP address or domain hosts a Fortinet SSL VPN
or Cisco SSL VPN web portal.
"""

import argparse
import logging
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from requests.exceptions import ConnectionError, Timeout, RequestException

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FORTINET_PATH = "/remote/login?lang=en"
CISCO_PATH = "/+CSCOE+/logon.html"

FORTINET_INDICATORS = ["fortinet", "fortigate", "fortissl", "forticlient"]
CISCO_INDICATORS = ["cisco", "webvpn", "cscoe", "+cscoe+"]

DEFAULT_TIMEOUT = 10
DEFAULT_RETRIES = 3
DEFAULT_RETRY_DELAY = 2  # seconds between retries
DEFAULT_CONCURRENCY = 20

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
# Helpers
# ---------------------------------------------------------------------------


def normalize_target(target: str) -> str:
    """Return a fully qualified HTTPS URL for *target*.

    If the target already contains a scheme it is returned unchanged.
    Plain IP addresses and hostnames are prefixed with ``https://``.
    """
    target = target.strip()
    if not target:
        raise ValueError("Empty target")

    if "://" in target:
        return target.rstrip("/")

    return f"https://{target}"


def build_session(timeout: int, retries: int) -> requests.Session:
    """Return a :class:`requests.Session` with TLS verification disabled."""
    session = requests.Session()
    # Suppress InsecureRequestWarning; TLS certs on VPN appliances are often
    # self-signed and we intentionally skip verification.
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    session.verify = False
    return session


def fetch_with_retry(
    session: requests.Session,
    url: str,
    timeout: int,
    retries: int,
    retry_delay: float,
) -> requests.Response | None:
    """Fetch *url* with up to *retries* retry attempts on failure.

    Returns the :class:`requests.Response` on success or ``None`` if all
    attempts fail.
    """
    last_exc: Exception | None = None

    for attempt in range(1, retries + 2):  # initial attempt + retries
        try:
            resp = session.get(url, timeout=timeout, allow_redirects=True)
            return resp
        except (ConnectionError, Timeout) as exc:
            last_exc = exc
            if attempt <= retries:
                logger.warning(
                    "Attempt %d/%d failed for %s: %s — retrying in %.1fs",
                    attempt,
                    retries + 1,
                    url,
                    exc,
                    retry_delay,
                )
                time.sleep(retry_delay)
            else:
                logger.error(
                    "All %d attempt(s) failed for %s: %s",
                    retries + 1,
                    url,
                    exc,
                )
        except RequestException as exc:
            last_exc = exc
            logger.error("Request error for %s: %s", url, exc)
            break  # non-retriable error

    return None


def response_contains(response: requests.Response, indicators: list[str]) -> bool:
    """Return True if the response body contains any of *indicators* (case-insensitive)."""
    body = response.text.lower()
    return any(indicator.lower() in body for indicator in indicators)


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def check_fortinet(
    base_url: str,
    session: requests.Session,
    timeout: int,
    retries: int,
    retry_delay: float,
) -> bool:
    """Return True if *base_url* serves a Fortinet SSL VPN login page."""
    url = base_url + FORTINET_PATH
    resp = fetch_with_retry(session, url, timeout, retries, retry_delay)
    if resp is None:
        return False
    if resp.status_code != 200:
        logger.debug("Fortinet check: %s returned HTTP %d", url, resp.status_code)
        return False
    if response_contains(resp, FORTINET_INDICATORS):
        logger.info("Fortinet SSL VPN detected at %s", base_url)
        return True
    return False


def check_cisco(
    base_url: str,
    session: requests.Session,
    timeout: int,
    retries: int,
    retry_delay: float,
) -> bool:
    """Return True if *base_url* serves a Cisco SSL VPN login page."""
    url = base_url + CISCO_PATH
    resp = fetch_with_retry(session, url, timeout, retries, retry_delay)
    if resp is None:
        return False
    if resp.status_code != 200:
        logger.debug("Cisco check: %s returned HTTP %d", url, resp.status_code)
        return False
    if response_contains(resp, CISCO_INDICATORS):
        logger.info("Cisco SSL VPN detected at %s", base_url)
        return True
    return False


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def load_existing(path: str) -> set[str]:
    """Return the set of URLs already written to *path*."""
    p = Path(path)
    if not p.exists():
        return set()
    return {line.strip() for line in p.read_text().splitlines() if line.strip()}


def append_result(path: str, url: str, seen: set[str]) -> None:
    """Append *url* to *path* if it has not been written before."""
    if url in seen:
        return
    seen.add(url)
    with open(path, "a") as fh:
        fh.write(url + "\n")
    logger.info("Written to %s: %s", path, url)


# ---------------------------------------------------------------------------
# Main scan logic
# ---------------------------------------------------------------------------


def scan_targets(
    targets: list[str],
    timeout: int,
    retries: int,
    retry_delay: float,
    fortinet_out: str,
    cisco_out: str,
) -> tuple[list[str], list[str]]:
    """Scan each target and return (fortinet_hits, cisco_hits)."""
    fortinet_seen = load_existing(fortinet_out)
    cisco_seen = load_existing(cisco_out)

    session = build_session(timeout, retries)

    fortinet_hits: list[str] = []
    cisco_hits: list[str] = []

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

        if check_fortinet(base_url, session, timeout, retries, retry_delay):
            append_result(fortinet_out, base_url, fortinet_seen)
            fortinet_hits.append(base_url)
            continue  # per spec: only check Cisco if not Fortinet

        if check_cisco(base_url, session, timeout, retries, retry_delay):
            append_result(cisco_out, base_url, cisco_seen)
            cisco_hits.append(base_url)

    session.close()
    return fortinet_hits, cisco_hits


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect Fortinet and Cisco SSL VPN portals",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "targets",
        nargs="*",
        metavar="TARGET",
        help="IP addresses or domains to scan (overrides --input if both supplied)",
    )
    parser.add_argument(
        "-i",
        "--input",
        metavar="FILE",
        help="Path to a file containing one target per line",
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
        help="Number of retry attempts per failed request",
    )
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=DEFAULT_RETRY_DELAY,
        metavar="SECONDS",
        help="Delay in seconds between retry attempts",
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
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug-level logging",
    )
    return parser.parse_args(argv)


def collect_targets(args: argparse.Namespace) -> list[str]:
    """Return the list of targets from CLI positional args and/or --input file."""
    targets: list[str] = list(args.targets)

    if args.input:
        input_path = Path(args.input)
        if not input_path.exists():
            logger.error("Input file not found: %s", args.input)
            sys.exit(1)
        file_targets = [
            line.strip()
            for line in input_path.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        targets.extend(file_targets)

    if not targets:
        logger.error("No targets supplied. Use positional arguments or --input FILE.")
        sys.exit(1)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for t in targets:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def main(argv: list[str] | None = None) -> None:
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

    fortinet_hits, cisco_hits = scan_targets(
        targets=targets,
        timeout=args.timeout,
        retries=args.retries,
        retry_delay=args.retry_delay,
        fortinet_out=args.fortinet_out,
        cisco_out=args.cisco_out,
    )

    print(f"\nScan complete.")
    print(f"  Fortinet SSL VPN portals found : {len(fortinet_hits)}")
    print(f"  Cisco SSL VPN portals found    : {len(cisco_hits)}")
    if fortinet_hits:
        print(f"  Results written to             : {args.fortinet_out}")
    if cisco_hits:
        print(f"  Results written to             : {args.cisco_out}")


if __name__ == "__main__":
    main()
