# SysScout

![tests](https://github.com/YOUR-USERNAME/sysscout/actions/workflows/tests.yml/badge.svg)

A lightweight, cross-platform, **read-only** command-line tool for first-pass IT
troubleshooting. One command checks a computer's health (CPU, memory, disk, uptime, OS)
and its connectivity to a chosen site (DNS, TCP, HTTPS/TLS), suggests where to look next,
and can save everything as a JSON report to attach to a support ticket.

```
$ python -m sysscout scan

System Health
-------------
  Operating System  Windows 11 (AMD64)                                 [INFO]
  Python Version    3.13.17 (CPython)                                  [INFO]
  Uptime            15.6 days since last restart                       [INFO]
  CPU Usage         10.4% across 8 logical cores                       [PASS]
  Memory Usage      85.0% (13.2 GB of 15.5 GB)                         [WARNING]
  Disk Usage        35.0% of C:\ (308.3 GB free)                       [PASS]

Network (example.com:443)
-------------------------
  DNS Resolution    example.com -> 2606:4700:10::6814:179a (+3 more) in 31 ms [PASS]
  TCP Connection    connected to 2606:4700:10::6814:179a port 443 in 8 ms [PASS]
  HTTPS/TLS         TLSv1.3, cert valid, HTTP 200 (18 ms handshake)    [PASS]

Recommendations
---------------
  1. [INFO] This computer has not restarted in 16 days. Restarting applies pending
     updates and frees memory held by long-running apps.
  2. [WARNING] Memory is nearly full, which forces the system to use much slower disk
     swap. Close unused applications and browser tabs, and restart if usage stays high.
     Consistently high usage may mean the workload needs more RAM.

Overall: WARNING
```

## Safety and privacy

- **Read-only.** SysScout never changes settings, installs anything, or deletes files.
- **No administrator rights needed.**
- **Contacts only the one host and port you specify.** It does not scan networks or address ranges.
- **Never disables TLS certificate verification.**
- **Reports exclude identifying data:** no hostname, username, file contents, or credentials.

## Installation

Requires **Python 3.11 or newer** on Windows, macOS, or Linux.

```bash
git clone https://github.com/YOUR-USERNAME/sysscout.git
cd sysscout
python -m venv .venv

# Activate the virtual environment
.\.venv\Scripts\Activate.ps1      # Windows PowerShell
source .venv/bin/activate         # macOS / Linux

pip install -r requirements.txt
```

On macOS, use `python3` if `python` is not found.

## Usage

```bash
python -m sysscout --help                     # overview
python -m sysscout scan --help                # all scan options
```

| Task | Command |
|---|---|
| Full check (system + network) | `python -m sysscout scan` |
| Save a JSON report | `python -m sysscout scan --output reports/scan.json` |
| Custom warning thresholds | `python -m sysscout scan --cpu-warning 90 --memory-warning 90 --disk-warning 85` |
| Check a different drive | `python -m sysscout scan --disk-path D:\` |
| System checks only (offline machine) | `python -m sysscout scan --no-network` |
| Test one site | `python -m sysscout network --host example.com --port 443` |
| Test a non-HTTPS service | `python -m sysscout network --host mail.example.com --port 993` |
| Force TLS on a custom port | `python -m sysscout network --host intranet.example --port 8443 --tls` |
| Slow network | `python -m sysscout network --host example.com --timeout 15` |

### Options

| Option | Default | Meaning |
|---|---|---|
| `--cpu-warning PERCENT` | 85 | Warn when CPU usage is at or above this |
| `--memory-warning PERCENT` | 85 | Warn when memory usage is at or above this |
| `--disk-warning PERCENT` | 85 | Warn when disk usage is at or above this |
| `--disk-path PATH` | system drive | `C:\` on Windows, `/System/Volumes/Data` on macOS, `/` on Linux |
| `--host HOST` | example.com | Host for network checks |
| `--port PORT` | 443 | TCP port for network checks |
| `--timeout SECONDS` | 5 | Limit for each network step |
| `--tls` | off | Run the TLS check even if the port is not 443 |
| `--no-network` | off | (`scan` only) Skip network checks |
| `--output FILE` | none | Also save a JSON report |

## What each check means

| Check | Measures | PASS / WARNING / FAIL |
|---|---|---|
| CPU Usage | Average busy % across all cores over a 1-second sample | WARNING at or above threshold |
| Memory Usage | RAM in use: (total − available) / total | WARNING at or above threshold |
| Disk Usage | Space used on the chosen drive | WARNING at or above threshold; FAIL if the drive can't be read |
| Uptime | Days since last restart | INFO (restart suggested after 7+ days) |
| Operating System / Python | Version and architecture | INFO |
| DNS Resolution | Can the hostname be turned into IP addresses? | FAIL on lookup failure or timeout |
| TCP Connection | Can a connection be opened to that IP and port? | FAIL if refused, timed out, or unreachable; WARNING if slower than 1 s |
| HTTPS/TLS | Valid, trusted certificate for that name, and an HTTP response | FAIL on certificate or handshake errors; WARNING if the certificate expires within 14 days or the server returns HTTP 5xx |

Network checks run in order. If one fails, the later ones are marked **SKIPPED**, so the
first failure shown is the place to start investigating.

Recommendations are suggestions about where to look, not a definitive diagnosis.

## Exit codes

Follows the common Nagios monitoring convention, so scripts and scheduled tasks can react:

| Code | Meaning |
|---|---|
| 0 | All checks passed |
| 1 | At least one WARNING |
| 2 | At least one FAIL, a report could not be written, or invalid command-line arguments |

## JSON report format

`--output` writes a report with this structure (schema version 1.0):

```json
{
  "schema_version": "1.0",
  "tool": {"name": "sysscout", "version": "0.1.0"},
  "generated_at": "2026-11-08T00:54:42+00:00",
  "command": "scan",
  "platform": {"system": "Windows", "release": "11", "architecture": "AMD64"},
  "settings": {"cpu_warning": 85.0, "memory_warning": 85.0, "disk_warning": 85.0,
               "disk_path": null, "host": "example.com", "port": 443,
               "timeout": 5.0, "tls": false, "no_network": false},
  "overall_status": "WARNING",
  "status_counts": {"PASS": 5, "WARNING": 1, "FAIL": 0, "INFO": 3, "SKIPPED": 0},
  "checks": [
    {"check_id": "memory", "label": "Memory Usage", "status": "WARNING",
     "summary": "85.0% (13.2 GB of 15.5 GB)",
     "details": {"percent": 85.0, "total_gb": 15.5, "available_gb": 2.3,
                 "warning_threshold": 85.0}}
  ],
  "recommendations": [
    {"check_id": "memory", "status": "WARNING", "message": "Memory is nearly full, ..."}
  ]
}
```

- `generated_at` is ISO 8601 in UTC.
- `status_counts` always contains all five statuses.
- `check_id` values: `os`, `python`, `uptime`, `cpu`, `memory`, `disk`, `dns`, `tcp`, `https`.
- Failed network checks include `details.error_kind`: `dns_failure`, `timeout`, `refused`,
  `unreachable`, `connection_error`, `cert_verification`, or `tls_error`.

The `reports/` folder is git-ignored so reports from real machines aren't committed by accident.

## Project structure

```
sysscout/
├── __main__.py         entry point for `python -m sysscout`
├── cli.py              argument parsing, terminal output, exit codes
├── results.py          shared CheckResult / Status types, overall status
├── system.py           CPU, memory, disk, uptime, OS, Python checks (psutil)
├── network.py          DNS -> TCP -> HTTPS/TLS checks (socket, ssl)
├── recommendations.py  rule table mapping results to suggestions
└── reports.py          JSON report building and writing
tests/                  pytest suite (system and network calls are mocked)
.github/workflows/      CI on Windows, macOS, and Ubuntu
```

## Development

```bash
python -m pytest            # run all tests (offline, under a second)
python -m pytest -v -k dns  # verbose, only DNS-related tests
```

The tests replace psutil, sockets, and SSL with fakes, so they don't depend on the
machine's real load or on internet access. GitHub Actions runs them on Ubuntu,
Windows, and macOS with Python 3.11 and 3.13 on every push and pull request,
plus a real (unmocked) smoke run of the CLI on each OS.

## Limitations

- Checks one destination at a time, and only TCP (no UDP, ping/ICMP, or traceroute).
- Does not inspect proxy, VPN, or firewall configuration directly; it reports their symptoms.
- CPU usage is a 1-second snapshot, not a trend over time.
- Recommendations are general guidance, not a root-cause diagnosis.
