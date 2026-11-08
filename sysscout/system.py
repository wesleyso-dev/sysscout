"""System health checks: CPU, memory, disk, uptime, OS, and Python version.

Every check is read-only. Nothing here needs administrator rights, changes
settings, or looks at the contents of user files.
"""

import os
import platform
import sys
import time

import psutil

from sysscout.results import CheckResult, Status

BYTES_PER_GB = 1024**3
CPU_SAMPLE_SECONDS = 1.0


def classify_usage(percent: float, warning_threshold: float) -> Status:
    """Turn a usage percentage into PASS or WARNING.

    Kept as a tiny pure function (no psutil, no I/O) so it is trivial to test.
    """
    return Status.WARNING if percent >= warning_threshold else Status.PASS


def default_disk_path() -> str:
    """Return the drive/mount point that holds the user's data on this OS."""
    if sys.platform == "win32":
        # SystemDrive is usually "C:"; disk_usage needs the root, "C:\".
        return os.environ.get("SystemDrive", "C:") + "\\"
    if sys.platform == "darwin" and os.path.isdir("/System/Volumes/Data"):
        # On modern macOS "/" is a small read-only system volume; user files
        # live on the Data volume, so that is the one that fills up.
        return "/System/Volumes/Data"
    return "/"


def _to_gb(num_bytes: int) -> float:
    return round(num_bytes / BYTES_PER_GB, 1)


def _failed(check_id: str, label: str, error: Exception) -> CheckResult:
    """Build a FAIL result when a check could not be measured at all."""
    return CheckResult(
        check_id=check_id,
        label=label,
        status=Status.FAIL,
        summary=f"could not be measured ({type(error).__name__}: {error})",
        details={"error": str(error), "error_type": type(error).__name__},
    )


def check_cpu(warning_threshold: float) -> CheckResult:
    """Average CPU usage across all cores, sampled over one second."""
    try:
        percent = psutil.cpu_percent(interval=CPU_SAMPLE_SECONDS)
        logical_cores = psutil.cpu_count(logical=True)
    except (OSError, psutil.Error) as error:
        return _failed("cpu", "CPU Usage", error)

    return CheckResult(
        check_id="cpu",
        label="CPU Usage",
        status=classify_usage(percent, warning_threshold),
        summary=f"{percent:.1f}% across {logical_cores} logical cores",
        details={
            "percent": percent,
            "logical_cores": logical_cores,
            "warning_threshold": warning_threshold,
        },
    )


def check_memory(warning_threshold: float) -> CheckResult:
    """RAM in use: (total - available) / total."""
    try:
        memory = psutil.virtual_memory()
    except (OSError, psutil.Error) as error:
        return _failed("memory", "Memory Usage", error)

    used = memory.total - memory.available
    return CheckResult(
        check_id="memory",
        label="Memory Usage",
        status=classify_usage(memory.percent, warning_threshold),
        summary=f"{memory.percent:.1f}% ({_to_gb(used)} GB of {_to_gb(memory.total)} GB)",
        details={
            "percent": memory.percent,
            "total_gb": _to_gb(memory.total),
            "available_gb": _to_gb(memory.available),
            "warning_threshold": warning_threshold,
        },
    )


def check_disk(warning_threshold: float, path: str | None = None) -> CheckResult:
    """Space used on one drive or mount point."""
    path = path or default_disk_path()
    try:
        usage = psutil.disk_usage(path)
    except (OSError, psutil.Error) as error:
        # Most common cause: a typo'd or disconnected drive, e.g. --disk-path Z:\
        return _failed("disk", "Disk Usage", error)

    return CheckResult(
        check_id="disk",
        label="Disk Usage",
        status=classify_usage(usage.percent, warning_threshold),
        summary=f"{usage.percent:.1f}% of {path} ({_to_gb(usage.free)} GB free)",
        details={
            "path": path,
            "percent": usage.percent,
            "total_gb": _to_gb(usage.total),
            "free_gb": _to_gb(usage.free),
            "warning_threshold": warning_threshold,
        },
    )


def check_uptime() -> CheckResult:
    """How long since the last reboot (pending updates often need one)."""
    try:
        seconds = time.time() - psutil.boot_time()
    except (OSError, psutil.Error) as error:
        return _failed("uptime", "Uptime", error)

    days = seconds / 86400
    return CheckResult(
        check_id="uptime",
        label="Uptime",
        status=Status.INFO,
        summary=f"{days:.1f} days since last restart",
        details={"days": round(days, 2)},
    )


def check_os() -> CheckResult:
    """Operating system name, version, and CPU architecture.

    Deliberately excludes the hostname and username: they identify a person
    or machine and are not needed to troubleshoot.
    """
    system = platform.system()  # "Windows", "Darwin", or "Linux"
    if system == "Darwin":
        # platform.release() gives the Darwin kernel version (e.g. 23.5.0);
        # mac_ver() gives the macOS version users recognize (e.g. 14.5).
        version = platform.mac_ver()[0]
        name = "macOS"
    else:
        version = platform.release()
        name = system
    machine = platform.machine()  # e.g. AMD64, x86_64, arm64

    return CheckResult(
        check_id="os",
        label="Operating System",
        status=Status.INFO,
        summary=f"{name} {version} ({machine})",
        details={
            "system": system,
            "version": version,
            "build": platform.version(),
            "architecture": machine,
        },
    )


def check_python() -> CheckResult:
    """The Python interpreter running SysScout."""
    return CheckResult(
        check_id="python",
        label="Python Version",
        status=Status.INFO,
        summary=f"{platform.python_version()} ({platform.python_implementation()})",
        details={
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
        },
    )


def run_system_checks(
    cpu_warning: float,
    memory_warning: float,
    disk_warning: float,
    disk_path: str | None = None,
) -> list[CheckResult]:
    """Run every system check and return the results in display order."""
    return [
        check_os(),
        check_python(),
        check_uptime(),
        check_cpu(cpu_warning),
        check_memory(memory_warning),
        check_disk(disk_warning, disk_path),
    ]
