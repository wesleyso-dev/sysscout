"""System checks, with psutil replaced by fakes so results don't depend on this machine."""

from types import SimpleNamespace

import pytest

from sysscout import system
from sysscout.results import Status

GB = 1024**3


@pytest.mark.parametrize(
    ("percent", "threshold", "expected"),
    [
        (84.9, 85, Status.PASS),     # just under
        (85.0, 85, Status.WARNING),  # exactly at the threshold warns (>=)
        (99.0, 85, Status.WARNING),
        (50.0, 40, Status.WARNING),  # custom threshold respected
        (0.0, 0, Status.WARNING),    # threshold 0 warns on everything
    ],
)
def test_classify_usage(percent, threshold, expected):
    assert system.classify_usage(percent, threshold) == expected


def test_check_cpu_uses_sampled_value(monkeypatch):
    calls = {}

    def fake_cpu_percent(interval):
        calls["interval"] = interval
        return 92.5

    monkeypatch.setattr(system.psutil, "cpu_percent", fake_cpu_percent)
    monkeypatch.setattr(system.psutil, "cpu_count", lambda logical=True: 8)

    result = system.check_cpu(warning_threshold=85)

    assert result.status == Status.WARNING
    assert result.details["percent"] == 92.5
    assert result.details["logical_cores"] == 8
    assert calls["interval"] > 0  # a real sample, not the meaningless first-call 0.0


def test_check_memory_reports_used_and_total(monkeypatch):
    fake = SimpleNamespace(total=16 * GB, available=4 * GB, percent=75.0)
    monkeypatch.setattr(system.psutil, "virtual_memory", lambda: fake)

    result = system.check_memory(warning_threshold=85)

    assert result.status == Status.PASS
    assert "12.0 GB of 16.0 GB" in result.summary
    assert result.details["available_gb"] == 4.0


def test_check_disk_warns_when_nearly_full(monkeypatch):
    fake = SimpleNamespace(total=500 * GB, used=450 * GB, free=50 * GB, percent=90.0)
    monkeypatch.setattr(system.psutil, "disk_usage", lambda path: fake)

    result = system.check_disk(warning_threshold=85, path="/fake")

    assert result.status == Status.WARNING
    assert result.details == {
        "path": "/fake",
        "percent": 90.0,
        "total_gb": 500.0,
        "free_gb": 50.0,
        "warning_threshold": 85,
    }


def test_check_disk_missing_path_is_fail_not_crash(monkeypatch):
    def missing(path):
        raise FileNotFoundError(2, "No such file or directory", path)

    monkeypatch.setattr(system.psutil, "disk_usage", missing)

    result = system.check_disk(warning_threshold=85, path="Z:\\")

    assert result.status == Status.FAIL
    assert result.details["error_type"] == "FileNotFoundError"


@pytest.mark.parametrize(
    ("platform_name", "has_data_volume", "expected"),
    [
        ("win32", False, "D:\\"),
        ("darwin", True, "/System/Volumes/Data"),
        ("darwin", False, "/"),  # older macOS without a separate Data volume
        ("linux", False, "/"),
    ],
)
def test_default_disk_path_per_os(monkeypatch, platform_name, has_data_volume, expected):
    monkeypatch.setattr(system.sys, "platform", platform_name)
    monkeypatch.setenv("SystemDrive", "D:")
    monkeypatch.setattr(system.os.path, "isdir", lambda path: has_data_volume)

    assert system.default_disk_path() == expected
