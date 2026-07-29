# SSL VPN Detection Tool

A Python command-line tool that identifies whether a supplied IP address or domain hosts a **Fortinet SSL VPN** or **Cisco SSL VPN** web portal.

## Features

- Detects Fortinet SSL VPN portals via `/remote/login?lang=en`
- Detects Cisco SSL VPN portals via `/+CSCOE+/logon.html`
- Configurable request timeout and retry count
- Writes confirmed portals to separate output files (`fortinet.txt` / `cisco.txt`)
- Skips duplicate entries across runs
- Logs connection failures and retry attempts without stopping the scan

## Requirements

- Python 3.10+
- [requests](https://pypi.org/project/requests/)

Install dependencies:

```bash
pip install -r requirements.txt
```

## Usage

```
usage: vpn_checker.py [-h] [-i FILE] [--timeout SECONDS] [--retries N]
                      [--retry-delay SECONDS] [--fortinet-out FILE]
                      [--cisco-out FILE] [-v]
                      [TARGET ...]
```

### Scan targets provided as arguments

```bash
python vpn_checker.py 192.168.1.10 vpn.example.com 203.0.113.50
```

### Scan targets from a file

Create a plain-text file with one IP address or domain per line (lines starting with `#` are treated as comments):

```text
# targets.txt
192.168.1.10
vpn.example.com
203.0.113.50
```

```bash
python vpn_checker.py --input targets.txt
```

### Mix both

Positional arguments and `--input` targets are merged and deduplicated:

```bash
python vpn_checker.py 10.0.0.1 --input targets.txt
```

### Options

| Option | Default | Description |
|---|---|---|
| `TARGET` | — | One or more IP addresses / domains |
| `-i FILE`, `--input FILE` | — | File containing one target per line |
| `--timeout SECONDS` | `10` | HTTP request timeout |
| `--retries N` | `3` | Retry attempts per failed request |
| `--retry-delay SECONDS` | `2` | Delay between retries |
| `--fortinet-out FILE` | `fortinet.txt` | Output file for Fortinet hits |
| `--cisco-out FILE` | `cisco.txt` | Output file for Cisco hits |
| `-v`, `--verbose` | — | Enable debug-level logging |

## Output

Detected portals are appended to the output files (one URL per line). Duplicates are never written twice.

**fortinet.txt**
```
https://vpn.company1.com
https://203.0.113.15
```

**cisco.txt**
```
https://vpn.company2.com
https://198.51.100.20
```

## Detection Logic

For each target the tool:

1. Normalises the target to a fully-qualified `https://` URL.
2. Checks for a Fortinet portal (`/remote/login?lang=en` — HTTP 200 + body contains `fortinet`).
3. If not Fortinet, checks for a Cisco portal (`/+CSCOE+/logon.html` — HTTP 200 + body contains `cisco`, `webvpn`, or `cscoe`).
4. Unrecognised targets are silently skipped.

TLS certificate verification is intentionally disabled because VPN appliances commonly use self-signed certificates.

## Example Run

```
$ python vpn_checker.py --input targets.txt --timeout 15 --retries 2
2026-07-29 12:00:00 [INFO] Starting scan of 3 target(s) — timeout=15s retries=2
2026-07-29 12:00:00 [INFO] [1/3] Scanning https://192.168.1.10
2026-07-29 12:00:05 [INFO] [2/3] Scanning https://vpn.example.com
2026-07-29 12:00:05 [INFO] Fortinet SSL VPN detected at https://vpn.example.com
2026-07-29 12:00:05 [INFO] Written to fortinet.txt: https://vpn.example.com
2026-07-29 12:00:10 [INFO] [3/3] Scanning https://203.0.113.50

Scan complete.
  Fortinet SSL VPN portals found : 1
  Cisco SSL VPN portals found    : 0
  Results written to             : fortinet.txt
```
