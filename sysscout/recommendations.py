"""Turn check results into practical next steps for a technician.

These are suggestions about *where to look*, not a diagnosis. A failed DNS
lookup, for example, can have several causes; the message lists the usual ones.

How it works: each WARNING/FAIL result is looked up in a table by
(check_id, status-or-error_kind). Messages may contain {placeholders} that are
filled from the result's `details`, e.g. {port}.
"""

from dataclasses import dataclass

from sysscout.results import CheckResult, Status

UPTIME_RESTART_DAYS = 7


@dataclass
class Recommendation:
    check_id: str   # which check triggered it
    status: Status  # that check's status
    message: str


# Measured values past a threshold (status WARNING).
WARNING_MESSAGES: dict[str, str] = {
    "cpu": (
        "CPU usage is high. Check Task Manager (Windows) or Activity Monitor (macOS) "
        "for the processes using the most CPU; updates, cloud sync, and antivirus "
        "scans are common causes."
    ),
    "memory": (
        "Memory is nearly full, which forces the system to use much slower disk swap. "
        "Close unused applications and browser tabs, and restart if usage stays high. "
        "Consistently high usage may mean the workload needs more RAM."
    ),
    "disk": (
        "Low disk space may cause slow performance and failed updates. Review large "
        "files and unused applications, and empty the Recycle Bin/Trash and Downloads "
        "folder. ({free_gb} GB free on {path})"
    ),
    "tcp": (
        "The connection succeeded but was slow ({connect_ms} ms). Check Wi-Fi signal "
        "strength, VPN, and network congestion."
    ),
}

# Checks that could not complete, keyed by (check_id, error_kind).
FAILURE_MESSAGES: dict[tuple[str, str], str] = {
    ("dns", "dns_failure"): (
        "DNS lookup failed. Verify the hostname is spelled correctly, then check DNS "
        "settings, network connectivity, and the configured DNS resolver. If other "
        "sites also fail, the device may have no internet connection."
    ),
    ("dns", "timeout"): (
        "The DNS server did not answer in time. Check network connectivity and the "
        "configured DNS resolver; a VPN or captive portal (hotel/guest Wi-Fi) can "
        "also block DNS."
    ),
    ("tcp", "refused"): (
        "The host answered but refused port {port}. The service may not be running, "
        "may be on a different port, or a firewall is actively rejecting connections."
    ),
    ("tcp", "timeout"): (
        "No response on port {port}. Check firewall settings, network routing, and "
        "whether the destination service is running. Some networks block uncommon ports."
    ),
    ("tcp", "unreachable"): (
        "The network or host is unreachable. Check that Wi-Fi/Ethernet is connected, "
        "that a VPN is connected if the destination requires one, and that this "
        "device has internet access."
    ),
    ("tcp", "connection_error"): (
        "The connection to port {port} failed. Check firewall settings, network "
        "routing, and whether the destination service is running."
    ),
    ("https", "cert_verification"): (
        "The server's certificate could not be verified ({error}). Check that this "
        "computer's date and time are correct. If many HTTPS sites fail, the OS "
        "certificate store may be outdated or a network device may be intercepting "
        "TLS. Do not bypass certificate warnings."
    ),
    ("https", "tls_error"): (
        "The TLS handshake failed ({error}). The service on this port may not use "
        "TLS, or it may only support protocols this system does not allow."
    ),
    ("https", "timeout"): (
        "The TLS handshake timed out. The server may be overloaded or a firewall may "
        "be interfering; try again with a longer --timeout."
    ),
}

GENERIC_FAILURE = (
    "The {label} check could not complete. Review the error shown above and try again."
)


def _fill(template: str, result: CheckResult) -> str:
    """Insert values from result.details into a message template."""
    return template.format(label=result.label, **result.details)


def _recommend(result: CheckResult) -> str | None:
    """Return a recommendation for one result, or None if nothing to suggest."""
    if result.status == Status.WARNING:
        if result.check_id == "https":
            # HTTPS warnings have two different causes; say which one.
            if result.details.get("cert_days_left", 999) < 14:
                return (
                    f"The certificate for {result.details['host']} expires in "
                    f"{result.details['cert_days_left']:.0f} days. Notify the site owner."
                )
            return (
                f"The web server responded with HTTP {result.details.get('http_status')}, "
                f"a server-side error. The site is reachable but may be malfunctioning."
            )
        template = WARNING_MESSAGES.get(result.check_id)
        return _fill(template, result) if template else None

    if result.status == Status.FAIL:
        if result.check_id == "disk":
            return (
                "Disk usage could not be read. Check that the --disk-path drive or "
                "mount point exists and is connected."
            )
        key = (result.check_id, result.details.get("error_kind", ""))
        return _fill(FAILURE_MESSAGES.get(key, GENERIC_FAILURE), result)

    if result.check_id == "uptime" and result.details.get("days", 0) >= UPTIME_RESTART_DAYS:
        return (
            f"This computer has not restarted in {result.details['days']:.0f} days. "
            "Restarting applies pending updates and frees memory held by long-running apps."
        )

    return None


def build_recommendations(results: list[CheckResult]) -> list[Recommendation]:
    """One recommendation per result that needs attention, in check order."""
    recommendations = []
    for result in results:
        message = _recommend(result)
        if message:
            recommendations.append(Recommendation(result.check_id, result.status, message))
    return recommendations
