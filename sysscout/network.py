"""Network checks: DNS resolution, TCP connection, and HTTPS/TLS.

The three checks run as a chain, because each layer depends on the one before:

    DNS  (name -> IP address)
     └─ TCP  (can we open a connection to that IP and port?)
         └─ TLS/HTTPS  (is the server who it claims to be? does it answer HTTP?)

If a layer fails, the layers above it are marked SKIPPED rather than also
reported as failures, so the technician sees the *first* thing that broke.

Every network operation has a timeout so SysScout never hangs. Only the one
host and port the user asked for are contacted; nothing is scanned.
"""

import errno
import socket
import ssl
import threading
import time

from sysscout import __version__
from sysscout.results import CheckResult, Status

MAX_TCP_ATTEMPTS = 3            # try at most this many resolved addresses
SLOW_CONNECT_MS = 1000          # TCP connect slower than this -> WARNING
CERT_EXPIRY_WARNING_DAYS = 14   # certificate expiring sooner -> WARNING
HTTPS_PORT = 443

UNREACHABLE_ERRNOS = {errno.ENETUNREACH, errno.EHOSTUNREACH}

# Plain-English descriptions for each kind of failure. Recommendations
# (Stage 4) key off these same `error_kind` strings.
ERROR_DESCRIPTIONS = {
    "dns_failure": "name could not be resolved",
    "timeout": "timed out",
    "refused": "connection refused",
    "unreachable": "network or host unreachable",
    "connection_error": "connection failed",
    "cert_verification": "certificate verification failed",
    "tls_error": "TLS handshake failed",
}


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


def _failed(check_id: str, label: str, kind: str, detail: str, **extra) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        label=label,
        status=Status.FAIL,
        summary=f"{ERROR_DESCRIPTIONS[kind]}: {detail}",
        details={"error_kind": kind, "error": detail, **extra},
    )


def _skipped(check_id: str, label: str, reason: str) -> CheckResult:
    return CheckResult(check_id, label, Status.SKIPPED, reason, {"skipped_reason": reason})


def classify_connection_error(error: OSError) -> str:
    """Map a socket exception to one of our error_kind strings."""
    if isinstance(error, ConnectionRefusedError):
        return "refused"
    if isinstance(error, TimeoutError):
        return "timeout"
    if error.errno in UNREACHABLE_ERRNOS:
        return "unreachable"
    return "connection_error"


# --- DNS ----------------------------------------------------------------------

def resolve(host: str, timeout: float) -> list[str]:
    """Return the IP addresses for `host`, in the order the OS prefers them.

    socket.getaddrinfo() has no timeout parameter, and a broken resolver can
    make it block for a long time. So we run it in a background "daemon"
    thread and stop waiting after `timeout` seconds. (A daemon thread won't
    keep the program alive if the lookup is still stuck when we exit.)
    """
    outcome: dict[str, object] = {}

    def lookup() -> None:
        try:
            outcome["infos"] = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except Exception as error:  # handed back to the caller below
            outcome["error"] = error

    worker = threading.Thread(target=lookup, daemon=True)
    worker.start()
    worker.join(timeout)

    if worker.is_alive():
        raise TimeoutError(f"no answer from DNS within {timeout:g}s")
    if "error" in outcome:
        raise outcome["error"]  # type: ignore[misc]

    # Each info is (family, type, proto, canonname, sockaddr); sockaddr[0] is
    # the IP. dict.fromkeys() removes duplicates while keeping the order.
    return list(dict.fromkeys(info[4][0] for info in outcome["infos"]))  # type: ignore[union-attr]


def check_dns(host: str, timeout: float) -> CheckResult:
    start = time.perf_counter()
    try:
        addresses = resolve(host, timeout)
    except TimeoutError as error:
        return _failed("dns", "DNS Resolution", "timeout", str(error), host=host)
    except socket.gaierror as error:
        # gaierror = "get address info error": the name doesn't exist, or no
        # DNS server could be reached.
        return _failed("dns", "DNS Resolution", "dns_failure", f"{host} ({error.strerror})", host=host)
    except UnicodeError:
        # Raised for malformed names such as "bad..host".
        return _failed("dns", "DNS Resolution", "dns_failure", f"'{host}' is not a valid hostname", host=host)

    elapsed = _elapsed_ms(start)
    more = f" (+{len(addresses) - 1} more)" if len(addresses) > 1 else ""
    return CheckResult(
        check_id="dns",
        label="DNS Resolution",
        status=Status.PASS,
        summary=f"{host} -> {addresses[0]}{more} in {elapsed:.0f} ms",
        details={"host": host, "addresses": addresses, "elapsed_ms": elapsed},
    )


# --- TCP ----------------------------------------------------------------------

# When several addresses fail differently, report the most informative one.
# "refused" is the strongest evidence: a real machine answered and said no.
_KIND_PRIORITY = ["refused", "timeout", "unreachable", "connection_error"]


def check_tcp(addresses: list[str], port: int, timeout: float) -> CheckResult:
    """Open (and immediately close) a TCP connection to the first address that works."""
    failures: list[dict[str, str]] = []

    for address in addresses[:MAX_TCP_ATTEMPTS]:
        start = time.perf_counter()
        try:
            # create_connection does the TCP three-way handshake. The `with`
            # block closes the socket right away; we send no data.
            with socket.create_connection((address, port), timeout=timeout):
                elapsed = _elapsed_ms(start)
        except OSError as error:
            failures.append({
                "address": address,
                "error_kind": classify_connection_error(error),
                "error": str(error) or type(error).__name__,
            })
            continue

        return CheckResult(
            check_id="tcp",
            label="TCP Connection",
            status=Status.WARNING if elapsed >= SLOW_CONNECT_MS else Status.PASS,
            summary=f"connected to {address} port {port} in {elapsed:.0f} ms",
            details={
                "address": address,
                "port": port,
                "connect_ms": elapsed,
                "failed_attempts": failures,
            },
        )

    worst = min(failures, key=lambda f: _KIND_PRIORITY.index(f["error_kind"]))
    return _failed(
        "tcp", "TCP Connection", worst["error_kind"],
        f"port {port} on {worst['address']}",
        port=port, attempts=failures,
    )


# --- HTTPS / TLS --------------------------------------------------------------

def _http_status(tls_sock: ssl.SSLSocket, host: str) -> int | None:
    """Send a minimal HTTP HEAD request and return the status code, if any.

    HEAD asks for headers only (no page body), so almost no data is transferred.
    """
    request = (
        f"HEAD / HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"User-Agent: SysScout/{__version__}\r\n"
        f"Connection: close\r\n\r\n"
    )
    tls_sock.sendall(request.encode("ascii"))
    first_line = tls_sock.recv(1024).split(b"\r\n", 1)[0].decode("ascii", "replace")
    parts = first_line.split()  # e.g. ["HTTP/1.1", "200", "OK"]
    if len(parts) >= 2 and parts[0].startswith("HTTP/") and parts[1].isdigit():
        return int(parts[1])
    return None


def check_https(host: str, address: str, port: int, timeout: float) -> CheckResult:
    """TLS handshake with full certificate verification, then an HTTP HEAD request."""
    # create_default_context() turns ON certificate and hostname verification
    # and uses the OS's trusted root certificates. We never turn these off.
    context = ssl.create_default_context()
    label = "HTTPS/TLS"
    try:
        with socket.create_connection((address, port), timeout=timeout) as raw_sock:
            start = time.perf_counter()
            # server_hostname does two jobs: tells the server which site we
            # want (SNI), and is the name the certificate must match.
            with context.wrap_socket(raw_sock, server_hostname=host) as tls_sock:
                handshake_ms = _elapsed_ms(start)
                cert = tls_sock.getpeercert()
                tls_version = tls_sock.version()
                http_status = _http_status(tls_sock, host)
    # Order matters: the more specific exception classes must come first,
    # because SSLCertVerificationError is an SSLError, which is an OSError.
    except ssl.SSLCertVerificationError as error:
        return _failed("https", label, "cert_verification", error.verify_message or str(error), host=host)
    except ssl.SSLError as error:
        return _failed("https", label, "tls_error", error.reason or str(error), host=host)
    except OSError as error:
        return _failed("https", label, classify_connection_error(error),
                       str(error) or type(error).__name__, host=host)

    expires_at = ssl.cert_time_to_seconds(cert["notAfter"])
    days_left = (expires_at - time.time()) / 86400

    status = Status.PASS
    notes = []
    if days_left < CERT_EXPIRY_WARNING_DAYS:
        status = Status.WARNING
        notes.append(f"certificate expires in {days_left:.0f} days")
    if http_status is None:
        notes.append("no HTTP response")
    elif http_status >= 500:
        status = Status.WARNING
        notes.append(f"server error HTTP {http_status}")

    http_text = f"HTTP {http_status}" if http_status is not None else "no HTTP"
    summary = f"{tls_version}, cert valid, {http_text} ({handshake_ms:.0f} ms handshake)"
    if notes:
        summary += " - " + "; ".join(notes)

    return CheckResult(
        check_id="https",
        label=label,
        status=status,
        summary=summary,
        details={
            "host": host,
            "port": port,
            "tls_version": tls_version,
            "handshake_ms": handshake_ms,
            "http_status": http_status,
            "cert_expires": cert["notAfter"],
            "cert_days_left": round(days_left, 1),
        },
    )


# --- Orchestration ------------------------------------------------------------

def run_network_checks(host: str, port: int, timeout: float, force_tls: bool = False) -> list[CheckResult]:
    """Run DNS -> TCP -> HTTPS, skipping later steps when an earlier one fails."""
    dns = check_dns(host, timeout)
    if dns.status == Status.FAIL:
        return [
            dns,
            _skipped("tcp", "TCP Connection", "skipped: DNS lookup failed"),
            _skipped("https", "HTTPS/TLS", "skipped: DNS lookup failed"),
        ]

    tcp = check_tcp(dns.details["addresses"], port, timeout)
    if tcp.status == Status.FAIL:
        return [dns, tcp, _skipped("https", "HTTPS/TLS", "skipped: TCP connection failed")]

    if port != HTTPS_PORT and not force_tls:
        reason = f"skipped: port {port} is not {HTTPS_PORT} (use --tls to test TLS anyway)"
        return [dns, tcp, _skipped("https", "HTTPS/TLS", reason)]

    return [dns, tcp, check_https(host, tcp.details["address"], port, timeout)]
