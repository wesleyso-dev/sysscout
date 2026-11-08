"""Shared data types for every SysScout check.

System checks, network checks, recommendations, and reports all speak this
same "language", so it lives in its own small module instead of inside
system.py (which would make network.py depend on system.py for no reason).
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Status(StrEnum):
    """Outcome of a single check.

    PASS    - measured, and within the healthy range
    WARNING - measured, and worth a technician's attention
    FAIL    - the check could not complete, or the thing tested is broken
    INFO    - informational only (e.g. OS version); nothing to judge
    SKIPPED - not run, usually because an earlier step it depends on failed
    """

    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    INFO = "INFO"
    SKIPPED = "SKIPPED"


@dataclass
class CheckResult:
    """The result of one diagnostic check.

    check_id - stable machine-friendly name ("cpu", "disk", ...). Recommendations
               and JSON reports key off this, so it must never change casually.
    label    - human-friendly name shown in the terminal ("CPU Usage").
    status   - PASS / WARNING / FAIL / INFO.
    summary  - one short human-readable line ("23.0% across 8 logical cores").
    details  - raw values for the JSON report (numbers, not formatted strings).
    """

    check_id: str
    label: str
    status: Status
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


def overall_status(results: list[CheckResult]) -> Status:
    """The worst status across all checks: FAIL > WARNING > PASS.

    INFO and SKIPPED don't count (a SKIPPED check always has a FAIL before it).
    """
    statuses = {result.status for result in results}
    if Status.FAIL in statuses:
        return Status.FAIL
    if Status.WARNING in statuses:
        return Status.WARNING
    return Status.PASS


# Process exit codes, following the Nagios monitoring-plugin convention that
# many IT monitoring tools understand: 0 = OK, 1 = WARNING, 2 = CRITICAL.
EXIT_CODES = {Status.PASS: 0, Status.WARNING: 1, Status.FAIL: 2}
