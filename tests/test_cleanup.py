import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "cleanup",
    Path(__file__).resolve().parent.parent / "scripts" / "cleanup.py",
)
cleanup = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cleanup)


def _iso(minutes_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()


class _FakeJobs:
    def __init__(self, jobs: list[dict]) -> None:
        self._jobs = jobs
        self.cancelled: list[str] = []

    def get_jobs(self, history_id=None):
        return self._jobs

    def cancel_job(self, job_id: str) -> None:
        self.cancelled.append(job_id)


class _FakeHistories:
    def __init__(self, histories: list[dict], datasets: list[dict]) -> None:
        self._histories = histories
        self._datasets = datasets
        self.purged: list[tuple[str, bool]] = []

    def get_histories(self, name=None):
        return self._histories

    def show_matching_datasets(self, history_id):
        return self._datasets

    def delete_dataset(self, history_id, dataset_id, purge=False) -> None:
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


def test_purge_datasets_skips_already_purged() -> None:
    gi = _FakeGi(datasets=[{"id": "a"}, {"id": "b", "purged": True}, {"id": "c"}])
    purged = cleanup.purge_datasets(gi, "h1")
    assert purged == 2
    assert gi.histories.purged == [("a", True), ("c", True)]


def test_find_history_id_returns_none_when_absent() -> None:
    assert cleanup.find_history_id(_FakeGi(histories=[]), "PhysiCell Monitor") is None
    gi = _FakeGi(histories=[{"id": "h1"}])
    assert cleanup.find_history_id(gi, "PhysiCell Monitor") == "h1"
