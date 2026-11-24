"""Cancel leaked interactive-tool jobs and purge accumulated monitor datasets.

The monitor stops its own interactive-tool job in a ``finally`` block, but a
hard crash before that point can leave a running container behind or let
datasets accumulate in the monitor history. This runs on a schedule to sweep up
those leaks. It is scoped strictly to ``HISTORY_NAME`` so it never touches other
histories, and it only cancels jobs older than ``CLEANUP_MIN_AGE_MINUTES`` so it
cannot kill a monitor run that is still in flight.

Purging is paced and bounded: it pauses between requests, stops as soon as
Galaxy's proxy answers HTTP 429 (rate limited), and stops after a time budget.
Whatever is left is picked up by the next run, which skips everything already
purged, so a large backlog is worked off over a few days.
"""

import time
from datetime import UTC, datetime, timedelta

from config.settings import CLEANUP_MIN_AGE_MINUTES, HISTORY_NAME
from helpers.galaxy_client import brief_error, get_galaxy_instance

# States in which there is nothing left to cancel. "deleting" belongs here:
# Galaxy already has the cancel and answers a second one with "already
# finished". Jobs can sit in that state for months on usegalaxy.org.
_TERMINAL_STATES = {
    "ok",
    "error",
    "deleting",
    "deleted",
    "discarded",
    "failed",
    "deleted_new",
}

# Stop purging this long after the sweep starts. The workflow allows the job
# 10 minutes; this leaves room for setup and for one last slow request.
_TIME_BUDGET_SECONDS = 420

# Pause between purge requests. usegalaxy.org's proxy rate-limits API clients,
# and a daily background sweep has no reason to send requests back to back.
_PURGE_PAUSE_SECONDS = 1.0


def _say(message: str) -> None:
    # Flushed, so that a run which is killed still shows how far it got.
    print(message, flush=True)


def _rate_limited(exc: Exception) -> bool:
    return getattr(exc, "status_code", None) == 429


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
        # The state is logged so that a job which keeps turning up here can be
        # recognised: the cancel is evidently not taking effect for it.
        label = (
            f"job {job.get('id')} (state {job.get('state', 'unknown')}, "
            f"created {job.get('create_time', 'unknown')})"
        )
        try:
            took_effect = gi.jobs.cancel_job(job["id"])
        except Exception as exc:
            _say(f"warning: could not cancel {label}: {brief_error(exc)}")
            continue
        if took_effect is False:
            _say(f"Galaxy reports {label} as already finished.")
        else:
            cancelled += 1
            _say(f"Galaxy accepted the cancel for {label}.")
    return cancelled


def list_unpurged_datasets(gi, history_id: str) -> list[dict]:
    """List the history's datasets that still hold data, in a single request.

    BioBlend's ``show_matching_datasets`` looks every item up with a request of
    its own. Once the monitor history held months of runs, that alone took
    longer than the job is allowed, so nothing was ever purged.
    """
    contents = gi.histories.show_history(history_id, contents=True)
    return [
        item
        for item in contents
        if item.get("history_content_type", "dataset") == "dataset"
        and not item.get("purged")
    ]


def purge_datasets(
    gi, history_id: str, deadline: float | None = None
) -> tuple[int, int]:
    """Purge what is not purged yet. Returns (purged, left for the next run)."""
    pending = list_unpurged_datasets(gi, history_id)
    _say(f"{len(pending)} dataset(s) to purge.")
    purged = 0
    for index, dataset in enumerate(pending):
        if deadline is not None and time.monotonic() >= deadline:
            _say("Time budget used up; stopping here.")
            break
        if index:
            time.sleep(_PURGE_PAUSE_SECONDS)
        try:
            gi.histories.delete_dataset(history_id, dataset["id"], purge=True)
            purged += 1
        except Exception as exc:
            if _rate_limited(exc):
                # More requests now would only be refused too.
                _say("Galaxy is rate-limiting requests (HTTP 429); stopping here.")
                break
            reason = brief_error(exc)
            _say(f"warning: could not purge dataset {dataset.get('id')}: {reason}")
    return purged, len(pending) - purged


def main() -> int:
    deadline = time.monotonic() + _TIME_BUDGET_SECONDS
    try:
        gi = get_galaxy_instance()
        history_id = find_history_id(gi, HISTORY_NAME)
        if history_id is None:
            _say(f"No '{HISTORY_NAME}' history found; nothing to clean up.")
            return 0

        cancelled = cancel_active_jobs(gi, history_id, CLEANUP_MIN_AGE_MINUTES)
        _say(f"Cancelled {cancelled} active job(s).")
        purged, left = purge_datasets(gi, history_id, deadline)
    except Exception as exc:
        _say(f"Cleanup failed: {brief_error(exc)}")
        return 1

    _say(
        f"Cleanup complete for history '{HISTORY_NAME}': "
        f"cancelled {cancelled} active job(s), purged {purged} dataset(s)."
    )
    if left:
        _say(f"{left} dataset(s) are left for the next run.")
    if left and not purged:
        # A backlog and no progress at all is a failure, not a partial sweep.
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
