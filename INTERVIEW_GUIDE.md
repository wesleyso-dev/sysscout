# SysScout Interview Guide

Preparation notes for discussing SysScout in an IT Support / Research Computing interview.
Everything here describes what was actually built and tested.

---

## 1. Project overview

### 30-second explanation

> SysScout is a cross-platform Python command-line tool I built for first-pass IT
> troubleshooting. One command checks a computer's CPU, memory, disk, and uptime, then tests
> connectivity to a site layer by layer: DNS, TCP, then HTTPS with full certificate
> verification. It flags warnings and failures, suggests where to look next, and can export
> a JSON report to attach to a ticket. It's read-only, needs no admin rights, and it has a
> mocked pytest suite that runs on Windows, macOS, and Linux in GitHub Actions.

### 90-second technical walkthrough

> It's a Python package run with `python -m sysscout`. **argparse** handles two subcommands,
> `scan` and `network`, and validates input up front. Thresholds must be 0–100, ports 1–65535,
> timeouts positive. Bad input gets a clean usage error instead of a crash.
>
> Every check returns the same small dataclass, a **CheckResult**, with an ID, a status
> (PASS, WARNING, FAIL, INFO, or SKIPPED), a readable summary, and raw details. That shared
> type is what lets the other modules stay independent.
>
> **System checks** use psutil, so one API works on all three operating systems. CPU is
> sampled over one second because a single instant reading is meaningless. On macOS I check
> the Data volume rather than `/`, because `/` is a sealed read-only system volume there.
>
> **Network checks** run as a dependent chain. `getaddrinfo` for DNS, then a TCP connection to
> the resolved addresses, then a TLS handshake using Python's default SSL context, which
> verifies the certificate chain and hostname, followed by an HTTP HEAD request. If a layer
> fails, the later ones are marked SKIPPED, so the first failure is where you start.
> Exceptions are classified into categories such as refused, timeout, unreachable, and
> certificate failure. Everything has a timeout. DNS has no timeout parameter, so I run it in
> a daemon thread and stop waiting after the limit.
>
> A **rules table** maps each warning or failure to a practical suggestion. A **report module**
> builds a versioned JSON document with a UTC timestamp and no identifying data. The process
> **exit code** follows the Nagios convention: 0 OK, 1 warning, 2 failure.
>
> The **pytest suite** has 59 cases. psutil, sockets, and SSL are replaced with fakes, so it
> runs offline in under a second. GitHub Actions runs it on Ubuntu, Windows, and macOS, plus a
> real unmocked smoke test of the CLI on each OS.

### The problem it solves

Most support tickets start with "it's slow" or "I can't connect." The first ten minutes are
always the same questions:
- Is the disk full?
- Is memory exhausted?
- When did it last restart?
- Can it resolve the name?
- Can it reach the port?
- Is the certificate valid?

SysScout answers all of them in about two seconds, the same way on every OS. It produces a
report a user can send in, and it makes the first broken layer obvious. It doesn't replace a
technician's judgment. It speeds up the routine part and makes it consistent.

### Why Python

- **Cross-platform.** One codebase runs on Windows, macOS, and Linux, which matches a mixed
  research environment like ICSI's.
- **Standard library coverage.** `socket`, `ssl`, `json`, `argparse`, `platform`, `threading`
  are all built in. The only runtime dependency is psutil.
- **Readable.** Other staff can maintain and extend it, which matters for internal IT tools.
- **Common in research computing.** Researchers already have it, and it connects naturally to
  future automation (AWS's boto3, Google's Admin SDK).

---

## 2. Technical questions

### What does psutil do?

psutil ("process and system utilities") is a cross-platform library for system information:
CPU, memory, disks, network interfaces, processes, boot time. Under the hood it calls
OS-specific interfaces:
- Windows APIs on Windows
- `sysctl` and Mach calls on macOS
- `/proc` and `/sys` files on Linux

It exposes all of them through one Python API, so `psutil.virtual_memory()` works the same
everywhere. In SysScout I use:
- `cpu_percent(interval=1.0)`: busy time across a 1-second sample
- `cpu_count()`
- `virtual_memory()`
- `disk_usage(path)`
- `boot_time()`

### How does DNS work?

DNS turns a name like `example.com` into IP addresses.
1. The application asks the operating system (in Python, `socket.getaddrinfo`).
2. The OS checks its cache and the hosts file, then asks the configured resolver. That's
   usually the router, the ISP, the organization's DNS server, or a public resolver like
   1.1.1.1 or 8.8.8.8.
3. If the resolver doesn't have the answer cached, it walks the hierarchy: a root server
   points to the `.com` servers, which point to `example.com`'s authoritative server, which
   returns the A (IPv4) and AAAA (IPv6) records.
4. Answers are cached for their TTL.

**Common failures:**
- the name doesn't exist (typo, or NXDOMAIN)
- the resolver is unreachable (no network, VPN issue)
- a captive portal intercepting DNS
- stale cache entries

In SysScout, a `socket.gaierror` means the lookup failed, and a timeout means no answer.

### What happens during a TCP connection?

The three-way handshake:
1. The client sends **SYN** ("I'd like to connect to port 443").
2. The server replies **SYN-ACK** ("OK").
3. The client sends **ACK**. The connection is established.

How failures look:
- **Nothing listening on that port:** the host replies **RST**, and Python raises
  `ConnectionRefusedError`. The machine is reachable but the service isn't there, or a
  firewall is actively rejecting.
- **Packets silently dropped:** a firewall, a down host, or a routing problem. Nothing comes
  back, so you get a **timeout**.
- **No route at all:** for example no network, or IPv6 without connectivity. The OS reports
  **network/host unreachable**.

SysScout distinguishes these three, because each one points somewhere different. It opens and
immediately closes the connection without sending data.

### How does TLS certificate verification work?

During the TLS handshake, the server presents its certificate plus intermediate certificates.
The client then checks:
1. **Chain of trust.** Each certificate is signed by the next, up to a **root CA** already in
   the OS or browser trust store.
2. **Validity dates.** The current date must fall between "not before" and "not after."
   A wrong system clock breaks this.
3. **Hostname.** The certificate's Subject Alternative Names must include the hostname
   requested. The client sends that name via **SNI**, so a server hosting many sites knows
   which certificate to present.
4. Then key exchange establishes encryption.

In Python, `ssl.create_default_context()` enables all of this (`CERT_REQUIRED` and
`check_hostname=True`) using the OS trust store. I pass `server_hostname=host`, so the
certificate is checked against the name, even though I connect to a specific IP. A test
asserts verification is never disabled.

**A real example from building it:** example.com initially failed with "unable to get local
issuer certificate" while Google and GitHub passed. I pulled the chain and found it ended at
an SSL.com root. I checked the Windows root store and retested, and it then passed. The
likely cause is that Windows installs some trusted roots on demand through its own crypto
stack, and Python's OpenSSL reads the store without triggering that download. That's the
classic "works in the browser, fails in my script" problem. The fix is the trust store, never
`verify=False`.

### What is a timeout?

A timeout is the longest a program will wait for an operation before giving up. Without one,
a dropped connection can block for minutes, and a diagnostic tool that hangs is useless.
SysScout:
- sets a timeout on every socket (default 5 s, configurable with `--timeout`)
- caps TCP attempts at 3 addresses, so the worst case is bounded
- runs DNS, which has no timeout parameter, in a daemon thread that the main thread stops
  waiting for after the limit

### Why does exception handling matter?

**1. One broken check shouldn't take down the whole report.** An invalid disk path produces
a FAIL line and the other checks still run.

**2. The exception type is the diagnosis.** Examples:
- `ConnectionRefusedError` → the service is down
- `TimeoutError` → traffic is being dropped
- `SSLCertVerificationError` → certificate problem

**3. Catch narrowly.** I catch the specific expected exceptions (`OSError`, `psutil.Error`,
`socket.gaierror`, `ssl.SSLError`), not bare `Exception`, so real bugs aren't hidden. Order
matters too: `SSLCertVerificationError` is a subclass of `SSLError`, which is a subclass of
`OSError`, so the most specific `except` must come first.

### How are JSON reports generated?

1. Every check returns a `CheckResult` dataclass.
2. `build_report()` assembles a plain dict: schema version, tool version, UTC ISO 8601
   timestamp, platform, the CLI settings used, overall status, counts for every status, the
   checks (via `dataclasses.asdict`), and the recommendations.
3. `Status` is a `StrEnum` (a string subclass), so `json.dumps` writes `"PASS"` with no
   custom encoder.
4. `write_report()` creates parent folders and writes UTF-8 JSON.

The schema is documented and versioned so scripts can rely on it. Privacy is a design rule:
no hostname, username, or file contents.

### How does pytest mocking work?

pytest's `monkeypatch` fixture temporarily replaces an attribute, such as
`socket.create_connection`, with a fake for the duration of one test, then restores it
automatically. Fakes can:
- return canned data, like 90% disk usage
- raise the exact exceptions the OS would, like `ConnectionRefusedError` or a certificate
  error
- simulate a hang, like a DNS lookup that never returns

So the tests are deterministic, fast (0.6 s for 59 cases), and offline.

**The key rule is to patch where the name is looked up:**
- `network.py` calls `socket.getaddrinfo` through the module, so I patch
  `network.socket.getaddrinfo`.
- `cli.py` did `from sysscout.system import run_system_checks`, which copies the name into
  `cli`, so I patch `cli.run_system_checks`.

I validated the tests by planting three bugs, each caught by a specific test:
- `>=` changed to `>`
- TLS verification disabled
- an internal field leaking into the report

### How does GitHub Actions CI work?

CI (continuous integration) automatically builds and tests code on every change. In GitHub
Actions, a YAML workflow in `.github/workflows/` defines:
- **triggers:** push, pull request, manual
- **jobs:** each runs on a fresh virtual machine (runner)
- **steps:** the commands each job runs

SysScout's workflow uses a **matrix**: Ubuntu, Windows, and macOS × Python 3.11 and 3.13,
which is six jobs in parallel. Each one checks out the code, sets up Python, installs
requirements, runs pytest, and runs an unmocked smoke test of the CLI. If any command exits
non-zero, the job fails and the commit shows a red X.

**Why it matters for IT automation:** a script that silently breaks on macOS after a
"small fix" for Windows can mislead technicians or damage trust in the tool. CI catches that
before it's used.

### How does it support multiple operating systems?

- **psutil** hides most OS differences behind one API.
- **Explicit handling where needed:**
  - **Default disk:** `%SystemDrive%\` on Windows, `/System/Volumes/Data` on modern macOS
    (because `/` is the sealed system volume), `/` on Linux.
  - **macOS version:** `platform.mac_ver()` instead of the Darwin kernel version.
  - **Encoding:** reports are written with explicit UTF-8, because Windows defaults differ.
  - **Output:** ASCII-only, so old Windows consoles don't show garbled characters.
- **CI** runs the tests and a real smoke run on all three platforms.
- **Tests** can simulate other platforms by patching `sys.platform`.

---

## 3. Troubleshooting scenarios

### A researcher cannot connect to a website

**How a technician investigates:**
1. Is it just this site or everything?
2. Is it just this machine or everyone?
3. Then work up the layers: DNS → TCP → TLS → application.

**Run:** `python -m sysscout network --host the-site.edu`

**What SysScout can determine:**

| Result | What it suggests | Next steps |
|---|---|---|
| DNS FAIL | Typo, resolver problem, or no network | Try another site; compare `nslookup` against a different resolver; check VPN and captive portal |
| TCP timeout | Packets dropped: firewall, VPN needed, host down | Try from another network; check whether the site requires the institutional VPN |
| TCP refused | Host reachable, service not running on that port | Contact the service owner |
| TLS `cert_verification` | Expired certificate, wrong hostname, or untrusted root | Check the system clock; check for TLS-inspecting proxies; check the trust store |
| All PASS | The network path is fine | The problem is higher up: browser cache, extensions, authentication, or the application itself |

**What SysScout cannot determine:**
- browser-specific issues
- proxy configuration
- login or SSO problems
- whether the site is down for everyone (test from a second network)

### A laptop is running slowly

**How a technician investigates:** ask when it started and what's open, then check resource
pressure.

**Run:** `python -m sysscout scan`

**What SysScout can determine:**
- **Memory WARNING:** swapping is likely. Close apps and restart, or the workload may need
  more RAM. This matters for researchers running large datasets.
- **CPU WARNING while idle:** something is busy. Next step: Task Manager / Activity Monitor
  sorted by CPU.
- **Disk WARNING:** very little free space slows the system and breaks updates.
- **Long uptime:** a restart may apply pending updates and release leaked memory.

**What SysScout cannot determine:**
- which process is responsible
- thermal throttling
- failing hardware (SSD health, battery)
- malware
- slowness that isn't happening during the 1-second sample

### A computer has almost no disk space

**Run:** `python -m sysscout scan --disk-warning 85`. Use `--disk-path` for another drive.

**Typical next steps:**
- empty Recycle Bin / Trash
- clear Downloads
- remove unused applications
- clear caches
- move large research datasets to approved shared or cloud storage
- check for huge log files
- on Windows, use Storage Sense / Disk Cleanup; on macOS, System Settings → Storage

**What SysScout can determine:** the percentage used and the free space on the drive.

**What SysScout cannot determine:** *what* is using the space. It deliberately doesn't scan
user files, for privacy reasons. The technician should use the OS storage tools with the
user's permission.

### A network service is refusing connections

**Run:** `python -m sysscout network --host server.example --port 5432`

If **TCP is refused**, the host is up and reachable, but nothing accepted on that port.

**Likely causes:**
- the service is stopped or crashed
- it's listening on a different port
- it's listening only on localhost
- a host firewall is sending rejections

**Next steps:**
- check the service status on the server, or contact the owner
- confirm the port number
- compare with a timeout result: a timeout means something in the path is dropping traffic,
  which is a different problem

**What SysScout cannot determine:** why the service isn't listening. It only sees the
network's answer.

### An automated diagnostic check fails

For example, a scheduled run or a CI job returns exit code 2.

**How a technician investigates:**
1. Read the JSON report: `overall_status`, the first FAIL in `checks`, and its
   `details.error_kind`.
2. Decide whether the problem is in the **environment** (the machine or network really
   changed) or in the **check** (bad `--disk-path`, unreachable test host, too-tight
   threshold).
3. Re-run it manually.
4. Compare the report with an earlier one.

In CI, I avoid false alarms by setting thresholds to 100 and skipping network checks for the
smoke test, so CI failures mean the code broke, not that the runner was busy.

**What SysScout can determine:** which check failed, the error category, and the settings
used.

**What SysScout cannot determine:** whether a failure is intermittent. It's a snapshot, not
monitoring over time.

---

## 4. Architecture

```
                         ┌──────────────────────────────┐
  user / script  ──────► │ cli.py                       │
  python -m sysscout     │ argparse, validation,        │
                         │ printing, exit code          │
                         └──────┬─────────────┬─────────┘
                                │             │
                 thresholds,    │             │  host, port,
                 disk path      ▼             ▼  timeout
              ┌─────────────────────┐   ┌──────────────────────────┐
              │ system.py           │   │ network.py               │
              │ psutil + platform   │   │ DNS ─► TCP ─► HTTPS/TLS  │
              │ cpu, memory, disk,  │   │ socket + ssl, timeouts,  │
              │ uptime, os, python  │   │ SKIPPED after a failure  │
              └──────────┬──────────┘   └────────────┬─────────────┘
                         │   list[CheckResult]        │
                         └────────────┬───────────────┘
                                      ▼   (results.py: CheckResult, Status,
                                          overall_status, EXIT_CODES)
                         ┌──────────────────────────────┐
                         │ recommendations.py           │
                         │ (check_id, error_kind) table │
                         └──────────────┬───────────────┘
                                        ▼
                 ┌───────────────────────────────────────────┐
                 │ cli.finish()                              │
                 │ prints results + recommendations          │
                 │ overall status ─► exit code 0 / 1 / 2     │
                 └──────────────┬────────────────────────────┘
                                │ --output FILE
                                ▼
                         ┌──────────────────────────────┐
                         │ reports.py                   │
                         │ build_report() ─► dict       │
                         │ write_report() ─► .json      │
                         └──────────────────────────────┘
```

**Design principles worth mentioning:**
- **Separation of concerns.** Data gathering never prints. Display, recommendations, and
  reports never call psutil or sockets.
- **One shared data type** (`CheckResult`) connects all modules.
- **Pure functions where possible**, such as `classify_usage`, `overall_status`, and
  `build_report`, which are trivial to test.

---

## 5. Resume bullets

- Built **SysScout**, a cross-platform Python CLI (psutil, socket, ssl, argparse) that
  diagnoses CPU, memory, disk, and uptime with configurable thresholds and tests DNS, TCP,
  and HTTPS/TLS connectivity layer by layer with enforced timeouts and full certificate
  verification.
- Implemented a rule-based troubleshooting recommendation engine and versioned JSON report
  export (UTC timestamps, no identifying data), with Nagios-style exit codes for use in
  scripts and scheduled tasks.
- Wrote 59 pytest cases using mocked psutil, socket, and TLS calls to test failure modes
  offline (DNS timeouts, refused connections, certificate errors), and automated them with
  GitHub Actions on Windows, macOS, and Ubuntu.

*(Use the third bullet once the GitHub Actions run is green.)*

---

## 6. Honest limitations (good to raise yourself)

- It's a snapshot, not monitoring. A 1-second CPU sample can miss intermittent spikes.
- It checks TCP only. No ICMP ping, UDP, or traceroute, so it can't show *where* along the
  path packets are dropped.
- It doesn't read proxy, VPN, or firewall settings. It reports their symptoms.
- Recommendations are general guidance, not root-cause analysis.

**Possible next steps if asked:**
- a `--json` stdout mode for piping
- checking several hosts from a config file
- proxy awareness
- a top-processes summary
- packaging with a `sysscout` command via `pyproject.toml`
