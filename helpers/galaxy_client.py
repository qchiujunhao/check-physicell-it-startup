import time

from bioblend.galaxy import GalaxyInstance

from config.settings import (
    GALAXY_API_KEY,
    GALAXY_BASE_URL,
    GALAXY_PASSWORD,
    GALAXY_USERNAME,
)


def get_galaxy_instance() -> GalaxyInstance:
    """Connect to Galaxy using API key or username/password."""
    if GALAXY_API_KEY:
        return GalaxyInstance(GALAXY_BASE_URL, key=GALAXY_API_KEY)

    if GALAXY_USERNAME and GALAXY_PASSWORD:
        return GalaxyInstance(
            GALAXY_BASE_URL, email=GALAXY_USERNAME, password=GALAXY_PASSWORD
        )

    raise ValueError(
        "Set GALAXY_API_KEY or both GALAXY_USERNAME and GALAXY_PASSWORD"
    )


def get_or_create_history(gi: GalaxyInstance, name: str) -> str:
    """Find an existing history by name or create a new one. Returns history ID."""
    histories = gi.histories.get_histories(name=name)
    if histories:
        history = histories[0]
        # Clean old datasets to keep the history tidy
        datasets = gi.histories.show_matching_datasets(history["id"])
        for ds in datasets:
            gi.histories.delete_dataset(history["id"], ds["id"], purge=True)
        return history["id"]

    new_history = gi.histories.create_history(name=name)
    return new_history["id"]


def launch_physicell(gi: GalaxyInstance, history_id: str, tool_id: str) -> str:
    """Launch the PhysiCell interactive tool. Returns the job ID."""
    result = gi.tools.run_tool(history_id, tool_id, tool_inputs={})
    jobs = result.get("jobs", [])
    if not jobs:
        raise RuntimeError(f"No job created when launching tool '{tool_id}'")
    return jobs[0]["id"]


class ToolStartupTimeout(Exception):
    pass


class ToolStartupFailed(Exception):
    pass


class EntryPointTimeout(Exception):
    pass


def wait_for_tool_ready(
    gi: GalaxyInstance, job_id: str, timeout: int, poll_interval: int = 10
) -> None:
    """Poll job state until running. Raises on timeout or error."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = gi.jobs.show_job(job_id, full_details=True)
        state = job.get("state", "unknown")

        if state == "running":
            return
        if state in ("error", "deleted", "paused"):
            raise ToolStartupFailed(
                f"Job {job_id} entered terminal state: {state}"
            )

        time.sleep(poll_interval)

    raise ToolStartupTimeout(
        f"Job {job_id} did not reach 'running' within {timeout}s"
    )


def get_interactive_tool_url(
    gi: GalaxyInstance,
    job_id: str,
    timeout: int = 120,
    poll_interval: int = 5,
) -> str:
    """Fetch the entry point URL for a running interactive tool.

    Uses the Galaxy API endpoint /api/entry_points which may not be
    exposed through BioBlend directly.
    """
    deadline = time.time() + timeout
    url = f"{gi.base_url}/api/entry_points?job_id={job_id}"
    last_issue = (
        f"No entry points found for job {job_id}. "
        "The tool may not be an interactive tool."
    )

    while time.time() < deadline:
        response = gi.make_get_request(url)
        response.raise_for_status()
        entry_points = response.json()

        if not entry_points:
            last_issue = (
                f"No entry points found for job {job_id}. "
                "The tool may not be an interactive tool."
            )
            time.sleep(poll_interval)
            continue

        for entry_point in entry_points:
            target = entry_point.get("target")
            if target:
                if target.startswith("http"):
                    return target
                return f"{gi.base_url.rstrip('/')}/{target.lstrip('/')}"

        entry_point = entry_points[0]
        details = []
        for key in ("id", "active", "deleted", "configured", "host", "port"):
            if key in entry_point:
                details.append(f"{key}={entry_point[key]}")
        detail_text = f" ({', '.join(details)})" if details else ""
        last_issue = (
            f"Entry point for job {job_id} has no target URL yet{detail_text}"
        )
        time.sleep(poll_interval)

    raise EntryPointTimeout(f"{last_issue} after waiting {timeout}s")
