import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "cleanup",
    Path(__file__).resolve().parent.parent / "scripts" / "cleanup.py",
)
cleanup = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cleanup)


class _RateLimited(Exception):
    status_code = 429


@pytest.fixture(autouse=True)
def pauses(monkeypatch) -> list[float]:
    """Record the pauses between purge requests instead of sleeping."""
    recorded: list[float] = []
    monkeypatch.setattr(cleanup.time, "sleep", recorded.append)
    return recorded


def _iso(minutes_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()


class _FakeJobs:
    def __init__(self, jobs: list[dict]) -> None:
        self._jobs = jobs
        self.cancelled: list[str] = []
        self.already_finished: set[str] = set()

    def get_jobs(self, history_id=None):
        return self._jobs

    def cancel_job(self, job_id: str) -> bool:
        self.cancelled.append(job_id)
        return job_id not in self.already_finished


class _FakeHistories:
    def __init__(self, histories: list[dict], datasets: list[dict]) -> None:
        self._histories = histories
        self._datasets = datasets
        self.purged: list[tuple[str, bool]] = []
        self.listings = 0
        self.fail_on: set[str] = set()
        self.rate_limit_on: set[str] = set()

    def get_histories(self, name=None):
        return self._histories

    def show_history(self, history_id, contents=False):
        assert contents is True
        self.listings += 1
        if isinstance(self._datasets, Exception):
            raise self._datasets
        return self._datasets

    def show_dataset(self, history_id, dataset_id):
        raise AssertionError("datasets must not be looked up one request at a time")

    def delete_dataset(self, history_id, dataset_id, purge=False) -> None:
        if dataset_id in self.rate_limit_on:
            raise _RateLimited("Unexpected HTTP status code: 429")
        if dataset_id in self.fail_on:
            raise RuntimeError("GET: error 502: b'<html>\n<body>gateway page</body>")
        self.purged.append((dataset_id, purge))


class _FakeGi:
    def __init__(self, jobs=None, histories=None, datasets=None) -> None:
        self.jobs = _FakeJobs(jobs or [])
        self.histories = _FakeHistories(histories or [], datasets or [])


def test_should_cancel_skips_terminal_and_young_jobs() -> None:
    now = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)
    old = {"state": "running", "create_time": (now - timedelta(hours=3)).isoformat()}
    young_time = (now - timedelta(minutes=5)).isoformat()
    young = {"state": "running", "create_time": young_time}
    terminal = {"state": "ok", "create_time": (now - timedelta(hours=3)).isoformat()}
    unknown = {"state": "running"}

    assert cleanup._should_cancel(old, now, 60) is True
    assert cleanup._should_cancel(young, now, 60) is False
    assert cleanup._should_cancel(terminal, now, 60) is False
    assert cleanup._should_cancel(unknown, now, 60) is True


def test_cancel_active_jobs_only_cancels_stale_running_jobs() -> None:
    gi = _FakeGi(
        jobs=[
            {"id": "old", "state": "running", "create_time": _iso(180)},
            {"id": "young", "state": "running", "create_time": _iso(2)},
            {"id": "done", "state": "ok", "create_time": _iso(180)},
        ]
    )
    cancelled = cleanup.cancel_active_jobs(gi, "h1", 60)
    assert cancelled == 1
    assert gi.jobs.cancelled == ["old"]


def test_cancel_active_jobs_logs_each_job_state_and_outcome(capsys) -> None:
    gi = _FakeGi(
        jobs=[
            {"id": "live", "state": "running", "create_time": _iso(180)},
            {"id": "gone", "state": "deleting", "create_time": _iso(180)},
        ]
    )
    gi.jobs.already_finished = {"gone"}

    assert cleanup.cancel_active_jobs(gi, "h1", 60) == 2

    out = capsys.readouterr().out
    assert "Galaxy accepted the cancel for job live (state running, created" in out
    assert "Galaxy reports job gone (state deleting, created" in out
    assert "as already finished." in out


def test_purge_datasets_skips_already_purged() -> None:
    gi = _FakeGi(datasets=[{"id": "a"}, {"id": "b", "purged": True}, {"id": "c"}])
    purged, left = cleanup.purge_datasets(gi, "h1")
    assert (purged, left) == (2, 0)
    assert gi.histories.purged == [("a", True), ("c", True)]
    assert gi.histories.listings == 1


def test_purge_datasets_leaves_collections_alone() -> None:
    gi = _FakeGi(
        datasets=[
            {"id": "a", "history_content_type": "dataset"},
            {"id": "list", "history_content_type": "dataset_collection"},
        ]
    )
    assert cleanup.purge_datasets(gi, "h1") == (1, 0)
    assert gi.histories.purged == [("a", True)]


def test_purge_datasets_stops_at_the_time_budget(monkeypatch) -> None:
    gi = _FakeGi(datasets=[{"id": "a"}, {"id": "b"}, {"id": "c"}])
    ticks = iter([0.0, 5.0, 11.0, 12.0])
    monkeypatch.setattr(cleanup.time, "monotonic", lambda: next(ticks))

    purged, left = cleanup.purge_datasets(gi, "h1", deadline=10.0)

    assert (purged, left) == (2, 1)
    assert gi.histories.purged == [("a", True), ("b", True)]


def test_purge_datasets_pauses_between_requests(pauses) -> None:
    gi = _FakeGi(datasets=[{"id": "a"}, {"id": "b"}, {"id": "c"}])

    cleanup.purge_datasets(gi, "h1")

    assert pauses == [cleanup._PURGE_PAUSE_SECONDS] * 2


def test_purge_datasets_stops_when_galaxy_rate_limits(capsys) -> None:
    gi = _FakeGi(datasets=[{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}])
    gi.histories.rate_limit_on = {"b", "c", "d"}

    assert cleanup.purge_datasets(gi, "h1") == (1, 3)

    assert gi.histories.purged == [("a", True)]
    assert capsys.readouterr().out.count("HTTP 429") == 1  # asked once, not 3 times


def test_purge_datasets_counts_a_failed_purge_as_left(capsys) -> None:
    gi = _FakeGi(datasets=[{"id": "a"}, {"id": "b"}])
    gi.histories.fail_on = {"a"}

    assert cleanup.purge_datasets(gi, "h1") == (1, 1)

    warning = capsys.readouterr().out
    assert "could not purge dataset a" in warning
    assert "gateway page" not in warning  # only the first line of the error


def test_main_reports_what_is_left_and_still_succeeds(monkeypatch, capsys) -> None:
    gi = _FakeGi(histories=[{"id": "h1"}], datasets=[{"id": "a"}, {"id": "b"}])
    monkeypatch.setattr(cleanup, "get_galaxy_instance", lambda: gi)
    monkeypatch.setattr(cleanup, "_TIME_BUDGET_SECONDS", 10)
    ticks = iter([0.0, 5.0, 11.0])
    monkeypatch.setattr(cleanup.time, "monotonic", lambda: next(ticks))

    assert cleanup.main() == 0

    out = capsys.readouterr().out
    assert "purged 1 dataset(s)" in out
    assert "1 dataset(s) are left for the next run." in out


def test_main_fails_when_a_backlog_makes_no_progress(monkeypatch, capsys) -> None:
    gi = _FakeGi(histories=[{"id": "h1"}], datasets=[{"id": "a"}, {"id": "b"}])
    gi.histories.rate_limit_on = {"a"}
    monkeypatch.setattr(cleanup, "get_galaxy_instance", lambda: gi)

    assert cleanup.main() == 1

    assert "2 dataset(s) are left for the next run." in capsys.readouterr().out


def test_main_fails_briefly_when_galaxy_does_not_answer(monkeypatch, capsys) -> None:
    gi = _FakeGi(
        histories=[{"id": "h1"}],
        datasets=RuntimeError("GET: error 502: b'<html>\n<body>gateway page</body>"),
    )
    monkeypatch.setattr(cleanup, "get_galaxy_instance", lambda: gi)

    assert cleanup.main() == 1

    out = capsys.readouterr().out
    assert "Cleanup failed: RuntimeError: GET: error 502" in out
    assert "gateway page" not in out


def test_find_history_id_returns_none_when_absent() -> None:
    assert cleanup.find_history_id(_FakeGi(histories=[]), "PhysiCell Monitor") is None
    gi = _FakeGi(histories=[{"id": "h1"}])
    assert cleanup.find_history_id(gi, "PhysiCell Monitor") == "h1"
