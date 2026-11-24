from pathlib import Path

from scripts import evaluate_alert


def test_alert_waits_until_failure_threshold() -> None:
    result = {
        "timestamp": "2026-05-31T12:00:00+00:00",
        "status": "fail",
        "failure_stage": "job_timeout",
        "failure_message": "Job did not start",
        "tool_id": "tool/0.11",
    }

    state, first = evaluate_alert.evaluate_alert(
        result,
        {},
        Path("output/run-1/result.json"),
        failure_threshold=2,
        immediate_stages={"authentication", "tool_not_available"},
        count_statuses={"fail", "slow"},
        repeat_every=0,
    )
    _, second = evaluate_alert.evaluate_alert(
        result,
        state,
        Path("output/run-2/result.json"),
        failure_threshold=2,
        immediate_stages={"authentication", "tool_not_available"},
        count_statuses={"fail", "slow"},
        repeat_every=0,
    )

    assert first["should_alert"] is False
    assert first["consecutive_alertable"] == 1
    assert second["should_alert"] is True
    assert second["reason"] == "threshold"
    assert second["consecutive_alertable"] == 2


def test_alert_sends_immediate_stage_once_per_signature() -> None:
    result = {
        "timestamp": "2026-05-31T12:00:00+00:00",
        "status": "fail",
        "failure_stage": "authentication",
        "failure_message": "401 Unauthorized",
        "tool_id": "tool/0.11",
    }

    state, first = evaluate_alert.evaluate_alert(
        result,
        {},
        Path("output/run-1/result.json"),
        failure_threshold=3,
        immediate_stages={"authentication", "tool_not_available"},
        count_statuses={"fail", "slow"},
        repeat_every=0,
    )
    _, second = evaluate_alert.evaluate_alert(
        result,
        state,
        Path("output/run-2/result.json"),
        failure_threshold=3,
        immediate_stages={"authentication", "tool_not_available"},
        count_statuses={"fail", "slow"},
        repeat_every=0,
    )

    assert first["should_alert"] is True
    assert first["reason"] == "immediate_stage"
    assert second["should_alert"] is False


def test_env_csv_treats_an_empty_variable_as_unset(monkeypatch) -> None:
    # GitHub Actions passes an undefined repository variable as "", which used
    # to yield an empty set and silently switch the alert rules off.
    monkeypatch.setenv("ALERT_COUNT_STATUSES", "")
    assert evaluate_alert.env_csv("ALERT_COUNT_STATUSES", "fail") == {"fail"}

    monkeypatch.setenv("ALERT_COUNT_STATUSES", "   ")
    assert evaluate_alert.env_csv("ALERT_COUNT_STATUSES", "fail") == {"fail"}

    monkeypatch.delenv("ALERT_COUNT_STATUSES")
    assert evaluate_alert.env_csv("ALERT_COUNT_STATUSES", "fail") == {"fail"}


def test_env_csv_parses_an_explicit_value(monkeypatch) -> None:
    monkeypatch.setenv("ALERT_COUNT_STATUSES", "fail, slow ,")

    assert evaluate_alert.env_csv("ALERT_COUNT_STATUSES", "fail") == {
        "fail",
        "slow",
    }
