"""Build and save JSON diagnostic reports.

Report schema (version 1.0)
---------------------------
{
  "schema_version": "1.0",
  "tool":            {"name": "sysscout", "version": "0.1.0"},
  "generated_at":    "2026-11-07T18:30:00+00:00",   # ISO 8601, always UTC
  "command":         "scan" | "network",
  "platform":        {"system": "Windows", "release": "11", "architecture": "AMD64"},
  "settings":        {...the CLI options used, e.g. thresholds, host, port...},
  "overall_status":  "PASS" | "WARNING" | "FAIL",
  "status_counts":   {"PASS": 4, "WARNING": 1, "FAIL": 0, "INFO": 3, "SKIPPED": 0},
  "checks": [
    {"check_id": "cpu", "label": "CPU Usage", "status": "PASS",
     "summary": "12.0% across 8 logical cores", "details": {...raw values...}}
  ],
  "recommendations": [
    {"check_id": "memory", "status": "WARNING", "message": "..."}
  ]
}

Privacy: the report never includes the computer's hostname, the username,
file contents, or credentials. It only contains the measurements above and
the options the technician chose.
"""

import json
import platform
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sysscout import __version__
from sysscout.recommendations import Recommendation
from sysscout.results import CheckResult, Status, overall_status

SCHEMA_VERSION = "1.0"


def build_report(
    command: str,
    settings: dict[str, Any],
    results: list[CheckResult],
    recommendations: list[Recommendation],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Assemble the report as a plain dict (easy to test, easy to serialize).

    `generated_at` can be passed in so tests get a predictable timestamp.
    """
    generated_at = generated_at or datetime.now(timezone.utc)
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "sysscout", "version": __version__},
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "command": command,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "architecture": platform.machine(),
        },
        "settings": settings,
        "overall_status": overall_status(results),
        "status_counts": {
            status.value: sum(1 for r in results if r.status == status) for status in Status
        },
        # asdict() turns each dataclass into a dict, recursively.
        "checks": [asdict(result) for result in results],
        "recommendations": [asdict(rec) for rec in recommendations],
    }


def write_report(report: dict[str, Any], output_path: str | Path) -> Path:
    """Write the report as pretty-printed JSON, creating parent folders if needed.

    Raises OSError if the file can't be written (bad path, no permission);
    the CLI catches that and shows a friendly message.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Status is a StrEnum (a str subclass), so json writes it as "PASS" etc.
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return path
