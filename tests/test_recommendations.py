"""Recommendation rules. Pure logic: no mocking needed, just CheckResult inputs."""

import pytest

from sysscout.recommendations import build_recommendations
from sysscout.results import Status


def test_healthy_results_produce_no_recommendations(make_result):
    results = [
        make_result("cpu", Status.PASS, percent=10.0),
        make_result("dns", Status.PASS),
        make_result("os", Status.INFO),
    ]
    assert build_recommendations(results) == []


def test_disk_warning_mentions_free_space(make_result):
    result = make_result("disk", Status.WARNING, free_gb=12.5, path="C:\\")

    [rec] = build_recommendations([result])

    assert rec.check_id == "disk"
    assert "Low disk space" in rec.message
    assert "12.5 GB free on C:\\" in rec.message


@pytest.mark.parametrize(
    ("check_id", "error_kind", "expected_phrase"),
    [
        ("dns", "dns_failure", "check DNS settings"),
        ("tcp", "timeout", "Check firewall settings"),
        ("tcp", "refused", "refused port 8080"),
        ("tcp", "unreachable", "internet access"),
        ("https", "cert_verification", "date and time"),
    ],
)
def test_failure_recommendations(make_result, check_id, error_kind, expected_phrase):
    result = make_result(check_id, Status.FAIL, error_kind=error_kind, port=8080, error="x")

    [rec] = build_recommendations([result])

    assert rec.status == Status.FAIL
    assert expected_phrase in rec.message


def test_unknown_failure_falls_back_to_generic_message(make_result):
    result = make_result("tcp", Status.FAIL, error_kind="something_new")

    [rec] = build_recommendations([result])

    assert "could not complete" in rec.message


@pytest.mark.parametrize(("days", "expect_recommendation"), [(2.0, False), (7.0, True), (30.0, True)])
def test_restart_suggested_after_long_uptime(make_result, days, expect_recommendation):
    recs = build_recommendations([make_result("uptime", Status.INFO, days=days)])

    assert bool(recs) == expect_recommendation


def test_https_warning_distinguishes_expiring_certificate(make_result):
    expiring = make_result("https", Status.WARNING, host="example.com", cert_days_left=3.0, http_status=200)
    server_error = make_result("https", Status.WARNING, host="example.com", cert_days_left=90.0, http_status=503)

    cert_rec, http_rec = build_recommendations([expiring, server_error])

    assert "expires in 3 days" in cert_rec.message
    assert "HTTP 503" in http_rec.message


def test_recommendations_keep_check_order(make_result):
    results = [
        make_result("memory", Status.WARNING),
        make_result("disk", Status.WARNING, free_gb=1.0, path="/"),
    ]
    assert [r.check_id for r in build_recommendations(results)] == ["memory", "disk"]
