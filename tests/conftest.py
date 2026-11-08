"""Shared pytest fixtures. pytest loads this file automatically."""

import pytest

from sysscout.results import CheckResult, Status


@pytest.fixture
def make_result():
    """Factory for CheckResult objects, so tests only spell out what matters."""

    def _make(check_id: str, status: Status, **details) -> CheckResult:
        return CheckResult(
            check_id=check_id,
            label=check_id.upper(),
            status=status,
            summary="test",
            details=details,
        )

    return _make
