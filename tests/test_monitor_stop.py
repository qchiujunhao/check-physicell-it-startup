"""The run log must not claim a session was stopped when Galaxy never said so."""

import pytest

from helpers import monitor, results
from helpers.galaxy_client import ToolStartupFailed


@pytest.fixture
def launched(tmp_path, monkeypatch):
    """A monitor run that launches a job and then fails while it starts."""
    monkeypatch.setattr(results, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(results, "_current_run_dir", None)
    monkeypatch.setattr(monitor, "PREFLIGHT_ENABLED", False)
    monkeypatch.setattr(monitor, "get_galaxy_instance", lambda: object())
    monkeypatch.setattr(
        monitor, "get_or_create_history", lambda gi, name, purge_existing=False: "h1"
    )
    monkeypatch.setattr(monitor, "launch_physicell", lambda gi, hid, tid: "job1")

    def broken(gi, job_id, timeout_seconds):
        raise ToolStartupFailed("Job job1 entered terminal state: error")

    monkeypatch.setattr(monitor, "wait_for_tool_ready", broken)
    yield
    results._current_run_dir = None


def _run_and_collect_log() -> list[str]:
    lines: list[str] = []
    with pytest.raises(ToolStartupFailed):
        monitor.run_physicell_monitor(log=lines.append)
    return lines


def test_log_says_stopped_when_galaxy_confirms(launched, monkeypatch) -> None:
    monkeypatch.setattr(monitor, "stop_interactive_tool", lambda gi, job_id: True)

    assert "Interactive tool session stopped." in _run_and_collect_log()


def test_log_says_so_when_galaxy_does_not_confirm(launched, monkeypatch) -> None:
    monkeypatch.setattr(monitor, "stop_interactive_tool", lambda gi, job_id: False)

    lines = _run_and_collect_log()

    assert "Interactive tool session stopped." not in lines
    assert any("did not confirm the stop" in line for line in lines)
