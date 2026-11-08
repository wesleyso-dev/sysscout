"""JSON report building and writing, using pytest's tmp_path for real files."""

import getpass
import json
import socket
from datetime import datetime, timezone

import pytest

from sysscout.recommendations import build_recommendations
from sysscout.reports import build_report, write_report
from sysscout.results import Status, overall_status

FIXED_TIME = datetime(2026, 1, 15, 9, 30, 0, tzinfo=timezone.utc)


@pytest.fixture
def sample_results(make_result):
    return [
        make_result("os", Status.INFO),
        make_result("cpu", Status.PASS, percent=12.0),
        make_result("disk", Status.WARNING, percent=91.0, free_gb=20.0, path="C:\\"),
        make_result("dns", Status.FAIL, error_kind="dns_failure", error="nope.invalid"),
        make_result("tcp", Status.SKIPPED),
    ]


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([Status.PASS, Status.INFO], Status.PASS),
        ([Status.PASS, Status.WARNING], Status.WARNING),
        ([Status.WARNING, Status.FAIL, Status.PASS], Status.FAIL),
        ([Status.INFO, Status.SKIPPED], Status.PASS),
    ],
)
def test_overall_status_is_worst_status(make_result, statuses, expected):
    results = [make_result("x", status) for status in statuses]
    assert overall_status(results) == expected


def test_report_contains_documented_schema(sample_results):
    recs = build_recommendations(sample_results)

    report = build_report("scan", {"disk_warning": 85.0}, sample_results, recs, generated_at=FIXED_TIME)

    assert report["schema_version"] == "1.0"
    assert report["generated_at"] == "2026-01-15T09:30:00+00:00"
    assert report["command"] == "scan"
    assert set(report["platform"]) == {"system", "release", "architecture"}
    assert report["settings"] == {"disk_warning": 85.0}
    assert report["overall_status"] == "FAIL"
    assert report["status_counts"] == {"PASS": 1, "WARNING": 1, "FAIL": 1, "INFO": 1, "SKIPPED": 1}
    assert [c["check_id"] for c in report["checks"]] == ["os", "cpu", "disk", "dns", "tcp"]
    assert {r["check_id"] for r in report["recommendations"]} == {"disk", "dns"}


def test_write_report_creates_folders_and_valid_json(tmp_path, sample_results):
    report = build_report("scan", {}, sample_results, [], generated_at=FIXED_TIME)
    target = tmp_path / "nested" / "reports" / "scan.json"

    written = write_report(report, target)

    assert written == target
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded["checks"][2]["status"] == "WARNING"  # enum stored as plain text
    assert loaded == json.loads(json.dumps(report))     # round-trips unchanged


def test_report_excludes_identifying_information(sample_results):
    report_text = json.dumps(build_report("scan", {}, sample_results, []))

    for identifier in (socket.gethostname(), getpass.getuser()):
        if len(identifier) >= 4:  # skip very short names that could match by accident
            assert identifier not in report_text


def test_write_report_raises_for_unwritable_path(tmp_path):
    blocker = tmp_path / "not_a_folder"
    blocker.write_text("I am a file")

    with pytest.raises(OSError):
        write_report({}, blocker / "scan.json")  # parent is a file, so this must fail
