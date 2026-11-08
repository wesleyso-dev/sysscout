"""End-to-end CLI tests with the checks faked out.

cli.py does `from sysscout.system import run_system_checks`, which copies the
function into cli's own namespace. So we patch `cli.run_system_checks`, the
name cli actually looks up, not `system.run_system_checks`.
"""

import json

import pytest

from sysscout import cli
from sysscout.results import Status


@pytest.mark.parametrize(
    "bad_args",
    [
        ["scan", "--disk-warning", "150"],
        ["scan", "--cpu-warning", "abc"],
        ["network", "--port", "70000"],
        ["network", "--timeout", "0"],
        [],  # no command at all
    ],
)
def test_invalid_arguments_exit_with_usage_error(bad_args, capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(bad_args)

    assert exit_info.value.code == 2
    assert "error:" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("statuses", "expected_exit"),
    [
        ([Status.PASS, Status.INFO], 0),
        ([Status.PASS, Status.WARNING], 1),
        ([Status.WARNING, Status.FAIL], 2),
    ],
)
def test_scan_exit_code_matches_worst_status(monkeypatch, make_result, statuses, expected_exit):
    results = [make_result("cpu", status, percent=50.0) for status in statuses]
    monkeypatch.setattr(cli, "run_system_checks", lambda **kwargs: results)

    assert cli.main(["scan", "--no-network"]) == expected_exit


def test_scan_writes_report_with_settings(monkeypatch, make_result, tmp_path, capsys):
    monkeypatch.setattr(
        cli, "run_system_checks",
        lambda **kwargs: [make_result("disk", Status.WARNING, free_gb=5.0, path="C:\\")],
    )
    monkeypatch.setattr(
        cli, "run_network_checks",
        lambda host, port, timeout, tls: [make_result("dns", Status.PASS)],
    )
    output = tmp_path / "scan.json"

    code = cli.main(["scan", "--disk-warning", "80", "--host", "example.org", "--output", str(output)])

    report = json.loads(output.read_text(encoding="utf-8"))
    assert code == 1
    assert report["settings"]["disk_warning"] == 80.0
    assert report["settings"]["host"] == "example.org"
    assert "handler" not in report["settings"]  # internal field not leaked
    assert "Low disk space" in capsys.readouterr().out
