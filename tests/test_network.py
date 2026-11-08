"""Network checks with fake sockets: no real DNS, TCP, or internet needed.

network.py calls `socket.getaddrinfo(...)`, `socket.create_connection(...)`,
and `ssl.create_default_context()` through the module objects, so we patch
those attributes. monkeypatch puts the real functions back after each test.
"""

import errno
import socket
import ssl
import threading
import time

import pytest

from sysscout import network
from sysscout.results import Status


def addrinfo(*ips):
    """Build getaddrinfo()-shaped tuples: (family, type, proto, canonname, sockaddr)."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in ips]


class FakeSocket:
    """Stands in for a connected socket; supports `with`."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fail_if_called(*args, **kwargs):
    raise AssertionError("this network call should not have happened")


# --- DNS -----------------------------------------------------------------------

def test_dns_success_deduplicates_addresses(monkeypatch):
    monkeypatch.setattr(
        network.socket, "getaddrinfo",
        lambda host, port, type: addrinfo("192.0.2.1", "192.0.2.1", "192.0.2.2"),
    )

    result = network.check_dns("example.com", timeout=1)

    assert result.status == Status.PASS
    assert result.details["addresses"] == ["192.0.2.1", "192.0.2.2"]


def test_dns_failure_is_reported(monkeypatch):
    def no_such_host(host, port, type):
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")

    monkeypatch.setattr(network.socket, "getaddrinfo", no_such_host)

    result = network.check_dns("does-not-exist.invalid", timeout=1)

    assert result.status == Status.FAIL
    assert result.details["error_kind"] == "dns_failure"


def test_dns_lookup_that_hangs_times_out(monkeypatch):
    release = threading.Event()

    def hanging_lookup(host, port, type):
        release.wait(5)  # simulates a resolver that never answers
        return addrinfo("192.0.2.1")

    monkeypatch.setattr(network.socket, "getaddrinfo", hanging_lookup)

    start = time.perf_counter()
    result = network.check_dns("slow.example", timeout=0.1)
    elapsed = time.perf_counter() - start
    release.set()  # let the background thread finish

    assert result.status == Status.FAIL
    assert result.details["error_kind"] == "timeout"
    assert elapsed < 2  # we stopped waiting; we didn't hang for 5 seconds


# --- TCP -----------------------------------------------------------------------

@pytest.mark.parametrize(
    ("error", "expected_kind"),
    [
        (ConnectionRefusedError(errno.ECONNREFUSED, "refused"), "refused"),
        (TimeoutError("timed out"), "timeout"),
        (OSError(errno.ENETUNREACH, "Network is unreachable"), "unreachable"),
        (OSError(errno.EACCES, "Permission denied"), "connection_error"),
    ],
)
def test_tcp_failures_are_classified(monkeypatch, error, expected_kind):
    def failing_connect(address, timeout):
        raise error

    monkeypatch.setattr(network.socket, "create_connection", failing_connect)

    result = network.check_tcp(["192.0.2.1"], port=443, timeout=1)

    assert result.status == Status.FAIL
    assert result.details["error_kind"] == expected_kind


def test_tcp_falls_back_to_next_address(monkeypatch):
    def connect(address, timeout):
        ip, port = address
        if ip == "2001:db8::1":  # broken IPv6
            raise OSError(errno.ENETUNREACH, "Network is unreachable")
        return FakeSocket()

    monkeypatch.setattr(network.socket, "create_connection", connect)

    result = network.check_tcp(["2001:db8::1", "192.0.2.1"], port=443, timeout=1)

    assert result.status == Status.PASS
    assert result.details["address"] == "192.0.2.1"
    assert result.details["failed_attempts"][0]["error_kind"] == "unreachable"


def test_tcp_reports_most_informative_failure(monkeypatch):
    errors = {
        "2001:db8::1": OSError(errno.ENETUNREACH, "unreachable"),
        "192.0.2.1": ConnectionRefusedError(errno.ECONNREFUSED, "refused"),
    }

    def connect(address, timeout):
        raise errors[address[0]]

    monkeypatch.setattr(network.socket, "create_connection", connect)

    result = network.check_tcp(list(errors), port=8080, timeout=1)

    assert result.details["error_kind"] == "refused"


# --- HTTPS / TLS ---------------------------------------------------------------

class FakeTLSSocket(FakeSocket):
    def __init__(self, cert_days_left: float, http_reply: bytes):
        expires = time.gmtime(time.time() + cert_days_left * 86400)
        self._cert = {"notAfter": time.strftime("%b %d %H:%M:%S %Y GMT", expires)}
        self._reply = http_reply
        self.sent = b""

    def getpeercert(self):
        return self._cert

    def version(self):
        return "TLSv1.3"

    def sendall(self, data):
        self.sent += data

    def recv(self, size):
        return self._reply


class FakeContext:
    """Records the hostname TLS is asked to verify; returns a fake TLS socket."""

    def __init__(self, tls_socket=None, error=None):
        self.tls_socket = tls_socket
        self.error = error
        self.server_hostname = None

    def wrap_socket(self, sock, server_hostname):
        self.server_hostname = server_hostname
        if self.error:
            raise self.error
        return self.tls_socket


@pytest.mark.parametrize(
    ("days_left", "http_reply", "expected"),
    [
        (90, b"HTTP/1.1 200 OK\r\n", Status.PASS),
        (5, b"HTTP/1.1 200 OK\r\n", Status.WARNING),                     # cert expiring soon
        (90, b"HTTP/1.1 503 Service Unavailable\r\n", Status.WARNING),  # server error
    ],
)
def test_https_success_and_warnings(monkeypatch, days_left, http_reply, expected):
    context = FakeContext(tls_socket=FakeTLSSocket(days_left, http_reply))
    monkeypatch.setattr(network.ssl, "create_default_context", lambda: context)
    monkeypatch.setattr(network.socket, "create_connection", lambda address, timeout: FakeSocket())

    result = network.check_https("example.com", "192.0.2.1", 443, timeout=1)

    assert result.status == expected
    # We connect to the IP, but the certificate must be checked against the NAME.
    assert context.server_hostname == "example.com"


def test_https_certificate_failure_is_reported(monkeypatch):
    error = ssl.SSLCertVerificationError(1, "certificate verify failed")
    error.verify_message = "certificate has expired"
    monkeypatch.setattr(network.ssl, "create_default_context", lambda: FakeContext(error=error))
    monkeypatch.setattr(network.socket, "create_connection", lambda address, timeout: FakeSocket())

    result = network.check_https("expired.example", "192.0.2.1", 443, timeout=1)

    assert result.status == Status.FAIL
    assert result.details["error_kind"] == "cert_verification"
    assert "certificate has expired" in result.summary


def test_https_never_disables_certificate_verification(monkeypatch):
    """Guard against anyone 'fixing' a TLS failure by turning verification off."""
    real_factory = ssl.create_default_context
    created = []

    def spy():
        context = real_factory()
        created.append(context)
        return context

    def refused(address, timeout):
        raise ConnectionRefusedError(errno.ECONNREFUSED, "refused")

    monkeypatch.setattr(network.ssl, "create_default_context", spy)
    monkeypatch.setattr(network.socket, "create_connection", refused)

    network.check_https("example.com", "192.0.2.1", 443, timeout=1)

    assert created[0].verify_mode == ssl.CERT_REQUIRED
    assert created[0].check_hostname is True


# --- The DNS -> TCP -> HTTPS chain ----------------------------------------------

def test_dns_failure_skips_later_checks(monkeypatch):
    def no_such_host(host, port, type):
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")

    monkeypatch.setattr(network.socket, "getaddrinfo", no_such_host)
    monkeypatch.setattr(network.socket, "create_connection", fail_if_called)

    results = network.run_network_checks("nope.invalid", 443, timeout=1)

    assert [r.status for r in results] == [Status.FAIL, Status.SKIPPED, Status.SKIPPED]


def test_tls_skipped_on_non_https_port(monkeypatch):
    monkeypatch.setattr(network.socket, "getaddrinfo", lambda host, port, type: addrinfo("192.0.2.1"))
    monkeypatch.setattr(network.socket, "create_connection", lambda address, timeout: FakeSocket())
    monkeypatch.setattr(network.ssl, "create_default_context", fail_if_called)

    dns, tcp, https = network.run_network_checks("example.com", 22, timeout=1)

    assert (dns.status, tcp.status, https.status) == (Status.PASS, Status.PASS, Status.SKIPPED)
