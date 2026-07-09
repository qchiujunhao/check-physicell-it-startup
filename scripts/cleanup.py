"""Cancel leaked interactive-tool jobs and purge accumulated monitor datasets.

The monitor stops its own interactive-tool job in a ``finally`` block, but a
hard crash before that point can leave a running container behind or let
datasets accumulate in the monitor history. This runs on a schedule to sweep up
those leaks. It is scoped strictly to ``HISTORY_NAME`` so it never touches other
histories, and it only cancels jobs older than ``CLEANUP_MIN_AGE_MINUTES`` so it
cannot kill a monitor run that is still in flight.
"""

from datetime import UTC, datetime, timedelta

from config.settings import CLEANUP_MIN_AGE_MINUTES, HISTORY_NAME
from helpers.galaxy_client import get_galaxy_instance

_TERMINAL_STATES = {"ok", "error", "deleted", "discarded", "failed", "deleted_new"}


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _should_cancel(job: dict, now: datetime, min_age_minutes: int) -> bool:
    if job.get("state", "") in _TERMINAL_STATES:
        return False
    created = _parse_time(job.get("create_time"))
    if created is None:
        return True
    return now - created >= timedelta(minutes=min_age_minutes)


def find_history_id(gi, name: str) -> str | None:
    histories = gi.histories.get_histories(name=name)
    return histories[0]["id"] if histories else None


def cancel_active_jobs(gi, history_id: str, min_age_minutes: int) -> int:
    now = datetime.now(UTC)
    cancelled = 0
    for job in gi.jobs.get_jobs(history_id=history_id):
        if not _should_cancel(job, now, min_age_minutes):
            continue
        try:
            gi.jobs.cancel_job(job["id"])
            cancelled += 1
        except Exception as exc:
            print(f"warning: could not cancel job {job.get('id')}: {exc}")
    return cancelled


def purge_datasets(gi, history_id: str) -> int:
    purged = 0
    for dataset in gi.histories.show_matching_datasets(history_id):
        if dataset.get("purged"):
            continue
        try:
            gi.histories.delete_dataset(history_id, dataset["id"], purge=True)
            purged += 1
        except Exception as exc:
            print(f"warning: could not purge dataset {dataset.get('id')}: {exc}")
    return purged


def main() -> int:
    gi = get_galaxy_instance()
    history_id = find_history_id(gi, HISTORY_NAME)
    if history_id is None:
        print(f"No '{HISTORY_NAME}' history found; nothing to clean up.")
        return 0

    cancelled = cancel_active_jobs(gi, history_id, CLEANUP_MIN_AGE_MINUTES)
    purged = purge_datasets(gi, history_id)
    print(
        f"Cleanup complete for history '{HISTORY_NAME}': "
        f"cancelled {cancelled} active job(s), purged {purged} dataset(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
