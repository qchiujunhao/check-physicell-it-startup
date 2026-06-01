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
