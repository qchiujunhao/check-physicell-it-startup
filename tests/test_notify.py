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


def test_screenshot_for_picks_connected_on_success(tmp_path) -> None:
    (tmp_path / "connected.png").write_bytes(b"x")
    (tmp_path / "failure.png").write_bytes(b"x")
    ok_shot = notify_slack.screenshot_for(tmp_path, {"status": "ok"})
    fail_shot = notify_slack.screenshot_for(tmp_path, {"status": "fail"})
    assert ok_shot.name == "connected.png"
    assert fail_shot.name == "failure.png"


def test_screenshot_for_returns_none_when_absent(tmp_path) -> None:
    assert notify_slack.screenshot_for(tmp_path, {"status": "ok"}) is None


def test_failure_mentions_user_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("SLACK_MENTION_USER_ID", "U06M3MMR588")
    fail = notify_slack.summary_text({"status": "fail"}, None)
    ok = notify_slack.summary_text({"status": "ok"}, None)
    slow = notify_slack.summary_text({"status": "slow"}, None)
    missing = notify_slack.missing_result_text(None)

    assert fail.startswith("<@U06M3MMR588>")
    assert missing.startswith("<@U06M3MMR588>")
    assert "<@U06M3MMR588>" not in ok
    assert "<@U06M3MMR588>" not in slow


def test_no_mention_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("SLACK_MENTION_USER_ID", raising=False)
    assert "<@" not in notify_slack.summary_text({"status": "fail"}, None)


def test_multiple_mentions(monkeypatch) -> None:
    monkeypatch.setenv("SLACK_MENTION_USER_ID", "U06M3MMR588, U6LDS1MS6")
    fail = notify_slack.summary_text({"status": "fail"}, None)
    assert fail.startswith("<@U06M3MMR588> <@U6LDS1MS6>")
