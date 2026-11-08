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
    """

    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    INFO = "INFO"


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
