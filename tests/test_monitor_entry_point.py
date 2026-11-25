"""How long the monitor keeps probing an entry point that is not serving yet."""

import pytest

from helpers import monitor, results
from helpers.entry_point import InteractiveToolProxyError

_TOOL_URL = "https://ep1-secrettoken.interactivetool.example.org/"


def _window(monkeypatch, left_of_startup_budget: int, configured: int = 180) -> int:
    monkeypatch.setattr(monitor, "ENTRY_POINT_VERIFY_TIMEOUT_SECONDS", configured)
    monkeypatch.setattr(
        monitor, "seconds_remaining", lambda deadline: left_of_startup_budget
    )
    return monitor.entry_point_window(deadline=0.0)


def test_quickly_started_job_gets_the_whole_window(monkeypatch) -> None:
    assert _window(monkeypatch, left_of_startup_budget=586) == 180


def test_window_shrinks_to_what_the_slow_job_left(monkeypatch) -> None:
    assert _window(monkeypatch, left_of_startup_budget=100) == 100


def test_window_never_drops_below_thirty_seconds(monkeypatch) -> None:
    assert _window(monkeypatch, left_of_startup_budget=1) == 30


def test_shorter_configured_window_is_respected(monkeypatch) -> None:
    assert _window(monkeypatch, left_of_startup_budget=586, configured=10) == 10


@pytest.fixture
def started(tmp_path, monkeypatch):
    """A monitor run whose job is running and has an entry point URL."""
    monkeypatch.setattr(results, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(results, "_current_run_dir", None)
    monkeypatch.setattr(monitor, "PREFLIGHT_ENABLED", False)
    monkeypatch.setattr(monitor, "STARTUP_TIMEOUT_SECONDS", 600)
    monkeypatch.setattr(monitor, "ENTRY_POINT_VERIFY_TIMEOUT_SECONDS", 180)
    monkeypatch.setattr(monitor, "get_galaxy_instance", lambda: object())
    monkeypatch.setattr(
        monitor, "get_or_create_history", lambda gi, name, purge_existing=False: "h1"
    )
    monkeypatch.setattr(monitor, "launch_physicell", lambda gi, hid, tid: "job1")
    monkeypatch.setattr(
        monitor, "wait_for_tool_ready", lambda gi, job_id, timeout_seconds: None
    )
    monkeypatch.setattr(
        monitor, "get_interactive_tool_url", lambda gi, job_id, timeout=0: _TOOL_URL
    )
    monkeypatch.setattr(monitor, "stop_interactive_tool", lambda gi, job_id: True)
    yield
    results._current_run_dir = None


def test_monitor_hands_the_check_its_window_and_the_run_log(
    started, monkeypatch
) -> None:
    seen = {}

    def never_serves(url, timeout, log):
        seen.update(url=url, timeout=timeout)
        log("[entry point] probe 1 at +0.0s: HTTP 502, server: nginx/1.20.1")
        raise InteractiveToolProxyError(
            f"Interactive tool proxy returned HTTP 502 from {url}"
        )

    monkeypatch.setattr(monitor, "verify_entry_point", never_serves)
    lines: list[str] = []

    with pytest.raises(InteractiveToolProxyError) as excinfo:
        monitor.run_physicell_monitor(log=lines.append)

    assert seen == {"url": _TOOL_URL, "timeout": 180}
    assert "[entry point] probe 1 at +0.0s: HTTP 502, server: nginx/1.20.1" in lines
    assert "secrettoken" not in str(excinfo.value)
    assert any("failed at stage 'entry_point'" in line for line in lines)
