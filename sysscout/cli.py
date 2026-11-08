"""Command-line interface for SysScout.

This module only parses arguments and dispatches to the right command.
The diagnostic logic will live in system.py, network.py,
recommendations.py, and reports.py (added in later stages).
"""

import argparse
from collections.abc import Sequence

from sysscout import __version__
from sysscout.results import CheckResult
from sysscout.system import run_system_checks

DEFAULT_HOST = "example.com"
DEFAULT_PORT = 443
DEFAULT_TIMEOUT = 5.0  # seconds

DEFAULT_CPU_WARNING = 85.0
DEFAULT_MEMORY_WARNING = 85.0
DEFAULT_DISK_WARNING = 85.0


# --- Argument validators -------------------------------------------------
# argparse calls these with the raw string the user typed. Raising
# ArgumentTypeError makes argparse print a clean usage error and exit,
# instead of letting a bad value crash the program later.

def percentage(value: str) -> float:
    """Accept a number from 0 to 100 (used for warning thresholds)."""
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is not a number") from None
    if not 0 <= number <= 100:
        raise argparse.ArgumentTypeError(f"{value} must be between 0 and 100")
    return number


def port_number(value: str) -> int:
    """Accept a valid TCP port (1-65535)."""
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is not a whole number") from None
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"{value} must be between 1 and 65535")
    return port


def positive_seconds(value: str) -> float:
    """Accept a timeout greater than zero."""
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is not a number") from None
    if seconds <= 0:
        raise argparse.ArgumentTypeError(f"{value} must be greater than 0")
    return seconds


# --- Output formatting -----------------------------------------------------

def format_result(result: CheckResult) -> str:
    """One aligned line per check, e.g. 'CPU Usage         23.0% ...   [PASS]'."""
    return f"  {result.label:<18}{result.summary:<50} [{result.status}]"


def print_section(title: str, results: list[CheckResult]) -> None:
    print(f"\n{title}")
    print("-" * len(title))
    for result in results:
        print(format_result(result))


# --- Command handlers -------------------------------------------------------

def run_scan(args: argparse.Namespace) -> int:
    """Full scan: system health + (optionally) network checks."""
    print("SysScout scan")
    system_results = run_system_checks(
        cpu_warning=args.cpu_warning,
        memory_warning=args.memory_warning,
        disk_warning=args.disk_warning,
        disk_path=args.disk_path,
    )
    print_section("System Health", system_results)

    # Placeholders until Stages 3-4.
    if not args.no_network:
        print(f"\n(Network checks to {args.host}:{args.port} arrive in Stage 3)")
    if args.output:
        print(f"(JSON report to {args.output} arrives in Stage 4)")
    return 0


def run_network(args: argparse.Namespace) -> int:
    """Network-only checks against one explicitly chosen destination."""
    print("SysScout network  [Stage 1 skeleton: checks not implemented yet]")
    print(f"  Target  -> {args.host}:{args.port}")
    print(f"  Timeout -> {args.timeout:g}s")
    return 0


# --- Parser construction ---------------------------------------------------

def _add_network_arguments(parser: argparse.ArgumentParser) -> None:
    """Network options shared by the `scan` and `network` commands."""
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help="hostname to test (default: %(default)s)",
    )
    parser.add_argument(
        "--port",
        type=port_number,
        default=DEFAULT_PORT,
        help="TCP port to test (default: %(default)s)",
    )
    parser.add_argument(
        "--timeout",
        type=positive_seconds,
        default=DEFAULT_TIMEOUT,
        metavar="SECONDS",
        help="give up on each network step after this long (default: %(default)s)",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser. Kept separate from main() so tests can use it."""
    parser = argparse.ArgumentParser(
        prog="sysscout",
        description=(
            "SysScout: read-only system health and network diagnostics "
            "for IT troubleshooting. It never changes settings or deletes files."
        ),
        epilog=(
            "examples:\n"
            "  python -m sysscout scan\n"
            "  python -m sysscout scan --disk-warning 90 --output reports/scan.json\n"
            "  python -m sysscout network --host example.com --port 443\n"
            "\nrun 'python -m sysscout COMMAND --help' for command options."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    # `scan` command
    scan = subparsers.add_parser(
        "scan",
        help="check CPU, memory, disk, OS info, and network connectivity",
        description="Run system health checks and network checks, then show recommendations.",
    )
    scan.add_argument(
        "--cpu-warning", type=percentage, default=DEFAULT_CPU_WARNING, metavar="PERCENT",
        help="warn when CPU usage is at or above this (default: %(default)s)",
    )
    scan.add_argument(
        "--memory-warning", type=percentage, default=DEFAULT_MEMORY_WARNING, metavar="PERCENT",
        help="warn when memory usage is at or above this (default: %(default)s)",
    )
    scan.add_argument(
        "--disk-warning", type=percentage, default=DEFAULT_DISK_WARNING, metavar="PERCENT",
        help="warn when disk usage is at or above this (default: %(default)s)",
    )
    scan.add_argument(
        "--disk-path", default=None, metavar="PATH",
        help="drive or mount point to check, e.g. C:\\ or / (default: system drive)",
    )
    _add_network_arguments(scan)
    scan.add_argument(
        "--no-network", action="store_true",
        help="skip network checks (useful when you know the machine is offline)",
    )
    scan.add_argument(
        "--output", metavar="FILE",
        help="also save the results as a JSON report, e.g. reports/scan.json",
    )
    scan.set_defaults(handler=run_scan)

    # `network` command
    network = subparsers.add_parser(
        "network",
        help="check DNS, TCP, and HTTPS connectivity to one host",
        description="Test DNS resolution, TCP connection, and TLS/HTTPS to a single host.",
    )
    _add_network_arguments(network)
    network.set_defaults(handler=run_network)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, run the chosen command, and return an exit code.

    `argv` defaults to the real command line (sys.argv[1:]); tests can pass
    their own list, e.g. main(["scan", "--disk-warning", "90"]).
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)
