import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "notify_slack",
    Path(__file__).resolve().parent.parent / "scripts" / "notify_slack.py",
)
notify_slack = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(notify_slack)


def _block_text(payload: dict) -> str:
    return payload["blocks"][0]["text"]["text"]


def test_ok_payload_reports_success_and_timing() -> None:
    result = {
        "status": "ok",
        "success": True,
        "environment": "https://usegalaxy.org",
        "startup_seconds": 91.4,
        "expected_seconds": 120,
        "tool_id": "tool/0.11",
        "tool_version_policy": "latest",
    }
    payload = notify_slack.build_slack_payload(result, "https://run.example/1")
    text = _block_text(payload)

    assert payload["text"] == "PhysiCell Startup Monitor: OK (91.4s)"
    assert ":white_check_mark:" in text
    assert "91.4s" in text
    assert "`tool/0.11` (latest)" in text
    assert "<https://run.example/1|View GitHub run>" in text
    assert "Failure stage" not in text


def test_slow_payload_notes_expected_threshold() -> None:
    result = {
        "status": "slow",
        "success": True,
        "startup_seconds": 212.8,
        "expected_seconds": 120,
    }
    text = _block_text(notify_slack.build_slack_payload(result, None))

    assert ":warning:" in text
    assert "SLOW" in text
    assert "expected < 120s" in text


def test_fail_payload_includes_stage_and_error() -> None:
    result = {
        "status": "fail",
        "success": False,
        "failure_stage": "entry_point",
        "failure_message": "Interactive tool proxy error: proxy target missing",
    }
    text = _block_text(notify_slack.build_slack_payload(result, None))

    assert ":x:" in text
    assert "`entry_point`" in text
    assert "proxy target missing" in text


def test_missing_result_payload_is_built() -> None:
    text = _block_text(notify_slack.build_missing_result_payload("https://run.example/2"))
    assert "NO RESULT" in text
    assert "<https://run.example/2|View GitHub run>" in text
