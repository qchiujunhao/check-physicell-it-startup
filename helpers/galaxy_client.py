import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from bioblend.galaxy import GalaxyInstance

from config.settings import (
    GALAXY_API_KEY,
    GALAXY_BASE_URL,
    GALAXY_PASSWORD,
    GALAXY_STATUSPAGE_SUMMARY_URL,
    GALAXY_USERNAME,
    PREFLIGHT_TIMEOUT_SECONDS,
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


def get_or_create_history(
    gi: GalaxyInstance,
    name: str,
    purge_existing: bool = False,
) -> str:
    """Find an existing history by name or create a new one. Returns history ID."""
    histories = gi.histories.get_histories(name=name)
    if histories:
        history = histories[0]
        if purge_existing:
            datasets = gi.histories.show_matching_datasets(history["id"])
            for ds in datasets:
                gi.histories.delete_dataset(history["id"], ds["id"], purge=True)
        return history["id"]

    new_history = gi.histories.create_history(name=name)
    return new_history["id"]


class ToolNotAvailable(Exception):
    pass


def _fetch_json(url: str, timeout: int) -> dict | list:
    request = Request(
        url,
        headers={"User-Agent": "physicell-startup-monitor/0.1"},
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_json_result(url: str, timeout: int) -> tuple[dict | list | None, str | None]:
    try:
        return _fetch_json(url, timeout), None
    except HTTPError as exc:
        return None, f"HTTP {exc.code} for {url}"
    except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _natural_version_key(value: str) -> tuple[tuple[int, int | str], ...]:
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in re.split(r"(\d+)", value)
    )


def latest_version(versions: list[str]) -> str | None:
    """Return the highest version from Galaxy's installed version list."""
    if not versions:
        return None
    return max(versions, key=_natural_version_key)


def tool_id_for_version(tool_id: str, current_version: str | None, version: str) -> str:
    """Replace the terminal tool version in a Galaxy Tool Shed tool ID."""
    normalized = tool_id.rstrip("/")
    if current_version and normalized.endswith(f"/{current_version}"):
        prefix = normalized[: -len(current_version)]
        return f"{prefix}{version}"

    parts = normalized.split("/")
    if parts:
        parts[-1] = version
        return "/".join(parts)

    return normalized


def resolve_tool_id(
    configured_tool_id: str,
    version_policy: str,
    tool_metadata: dict,
) -> str:
    """Choose the tool ID to launch after applying the version policy."""
    if version_policy == "pinned":
        return configured_tool_id

    versions = [str(version) for version in tool_metadata.get("versions", [])]
    selected_version = latest_version(versions)
    current_version = tool_metadata.get("version")
    if selected_version is None or selected_version == current_version:
        return configured_tool_id

    return tool_id_for_version(configured_tool_id, current_version, selected_version)


def _tool_metadata_url(galaxy_base_url: str, tool_id: str) -> str:
    return f"{galaxy_base_url.rstrip('/')}/api/tools/{tool_id.lstrip('/')}"


def _summarize_tool_metadata(metadata: dict | None) -> dict:
    if not metadata:
        return {}

    return {
        "id": metadata.get("id"),
        "name": metadata.get("name"),
        "version": metadata.get("version"),
        "versions": metadata.get("versions", []),
        "model_class": metadata.get("model_class"),
        "hidden": metadata.get("hidden"),
        "panel_section_name": metadata.get("panel_section_name"),
    }


def run_preflight_checks(
    galaxy_base_url: str,
    configured_tool_id: str,
    version_policy: str,
    statuspage_summary_url: str = GALAXY_STATUSPAGE_SUMMARY_URL,
    timeout: int = PREFLIGHT_TIMEOUT_SECONDS,
) -> dict:
    """Collect cheap public signals before launching the interactive tool.

    The preflight is deliberately non-throwing. It records statuspage, Galaxy
    API, and tool metadata problems so the later startup result can explain
    whether a full launch failure is likely local to the tool or part of a
    broader Galaxy service issue.
    """
    preflight = {
        "status": "ok",
        "galaxy_base_url": galaxy_base_url,
        "configured_tool_id": configured_tool_id,
        "selected_tool_id": configured_tool_id,
        "tool_version_policy": version_policy,
    }

    def mark(status: str) -> None:
        if status == "fail" or preflight["status"] == "fail":
            preflight["status"] = "fail"
        elif status == "degraded" and preflight["status"] == "ok":
            preflight["status"] = "degraded"

    if statuspage_summary_url:
        payload, error = _fetch_json_result(statuspage_summary_url, timeout)
        if isinstance(payload, dict):
            components = {
                component.get("name"): component.get("status")
                for component in payload.get("components", [])
                if component.get("name")
                in {"Galaxy Main", "Webserver 1", "Webserver 2", "Main Tool Shed"}
            }
            indicator = payload.get("status", {}).get("indicator")
            preflight["statuspage"] = {
                "url": statuspage_summary_url,
                "indicator": indicator,
                "description": payload.get("status", {}).get("description"),
                "components": components,
                "unresolved_incident_count": len(payload.get("incidents", [])),
                "scheduled_maintenance_count": len(
                    payload.get("scheduled_maintenances", [])
                ),
            }
            if indicator and indicator != "none":
                mark("degraded")
        else:
            preflight["statuspage"] = {
                "url": statuspage_summary_url,
                "error": error,
            }
            mark("degraded")

    version_url = f"{galaxy_base_url.rstrip('/')}/api/version"
    payload, error = _fetch_json_result(version_url, timeout)
    if isinstance(payload, dict):
        preflight["galaxy_version"] = {
            "url": version_url,
            "version_major": payload.get("version_major"),
            "version_minor": payload.get("version_minor"),
        }
    else:
        preflight["galaxy_version"] = {"url": version_url, "error": error}
        mark("fail")

    configured_url = _tool_metadata_url(galaxy_base_url, configured_tool_id)
    payload, error = _fetch_json_result(configured_url, timeout)
    if isinstance(payload, dict):
        selected_tool_id = resolve_tool_id(configured_tool_id, version_policy, payload)
        preflight["selected_tool_id"] = selected_tool_id
        preflight["tool"] = {
            "configured": _summarize_tool_metadata(payload),
            "configured_available": True,
        }

        if selected_tool_id != configured_tool_id:
            selected_url = _tool_metadata_url(galaxy_base_url, selected_tool_id)
            selected_payload, selected_error = _fetch_json_result(selected_url, timeout)
            if isinstance(selected_payload, dict):
                preflight["tool"]["selected"] = _summarize_tool_metadata(
                    selected_payload
                )
                preflight["tool"]["selected_available"] = True
            else:
                preflight["tool"]["selected"] = {
                    "id": selected_tool_id,
                    "url": selected_url,
                    "error": selected_error,
                }
                preflight["tool"]["selected_available"] = False
                mark("fail")
        else:
            preflight["tool"]["selected"] = preflight["tool"]["configured"]
            preflight["tool"]["selected_available"] = True
    else:
        preflight["tool"] = {
            "configured": {
                "id": configured_tool_id,
                "url": configured_url,
                "error": error,
            },
            "configured_available": False,
            "selected_available": False,
        }
        mark("fail")

    return preflight


def check_tool_exists(gi: GalaxyInstance, tool_id: str) -> None:
    """Verify the tool is installed and available on this Galaxy instance."""
    try:
        tool = gi.tools.show_tool(tool_id)
    except Exception as exc:
        raise ToolNotAvailable(
            f"Tool '{tool_id}' not found on {gi.base_url}. "
            "It may be disabled, removed, or the tool ID is wrong."
        ) from exc

    if not tool:
        raise ToolNotAvailable(
            f"Tool '{tool_id}' not found on {gi.base_url}."
        )


def launch_physicell(gi: GalaxyInstance, history_id: str, tool_id: str) -> str:
    """Launch the PhysiCell interactive tool. Returns the job ID."""
    check_tool_exists(gi, tool_id)
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
    gi: GalaxyInstance, job_id: str, timeout: int, poll_interval: int = 3
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
    poll_interval: int = 2,
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


def stop_interactive_tool(gi: GalaxyInstance, job_id: str) -> None:
    """Cancel the interactive tool job to stop the running container."""
    try:
        gi.jobs.cancel_job(job_id)
    except Exception:
        # Also try the entry_points API to mark it as stopped
        try:
            url = f"{gi.base_url}/api/entry_points?job_id={job_id}"
            response = gi.make_get_request(url)
            response.raise_for_status()
            for ep in response.json():
                ep_id = ep.get("id")
                if ep_id:
                    delete_url = f"{gi.base_url}/api/entry_points/{ep_id}"
                    gi.make_delete_request(delete_url)
        except Exception:
            pass
