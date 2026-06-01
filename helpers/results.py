import json
from datetime import UTC, datetime
from pathlib import Path

from playwright.sync_api import Page

from config.settings import GALAXY_BASE_URL, OUTPUT_DIR, STARTUP_EXPECTED_SECONDS


def build_result(
    success: bool,
    startup_seconds: float | None,
    failure_stage: str | None = None,
    failure_message: str | None = None,
    timings: dict[str, float] | None = None,
    ui_verified: bool | None = None,
    ui_required: bool | None = None,
    preflight: dict | None = None,
    configured_tool_id: str | None = None,
    tool_id: str | None = None,
    tool_version_policy: str | None = None,
) -> dict:
    # Determine status: "ok", "slow", or "fail"
    if not success:
        status = "fail"
    elif startup_seconds is not None and startup_seconds > STARTUP_EXPECTED_SECONDS:
        status = "slow"
    else:
        status = "ok"

    result = {
        "timestamp": datetime.now(UTC).isoformat(),
        "environment": GALAXY_BASE_URL,
        "status": status,
        "success": success,
        "startup_seconds": (
            round(startup_seconds, 2) if startup_seconds is not None else None
        ),
        "expected_seconds": STARTUP_EXPECTED_SECONDS,
        "failure_stage": failure_stage,
        "failure_message": failure_message,
    }

    if configured_tool_id is not None:
        result["configured_tool_id"] = configured_tool_id
    if tool_id is not None:
        result["tool_id"] = tool_id
    if tool_version_policy is not None:
        result["tool_version_policy"] = tool_version_policy
    if timings is not None:
        result["timings"] = {
            name: round(seconds, 2) for name, seconds in timings.items()
        }
    if ui_verified is not None:
        result["ui_verified"] = ui_verified
    if ui_required is not None:
        result["ui_required"] = ui_required
    if preflight is not None:
        result["preflight"] = preflight

    return result


_current_run_dir: Path | None = None


def get_run_dir() -> Path:
    """Get or create a timestamped directory for this run's output.

    Returns the same directory within a single run.
    """
    global _current_run_dir
    if _current_run_dir is None:
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        _current_run_dir = OUTPUT_DIR / ts
    _current_run_dir.mkdir(parents=True, exist_ok=True)
    return _current_run_dir


def write_result(result: dict) -> Path:
    """Write result JSON to a timestamped directory."""
    run_dir = get_run_dir()
    path = run_dir / "result.json"
    path.write_text(json.dumps(result, indent=2))
    return path


def capture_success_artifacts(page: Page | None) -> Path:
    """Save artifacts from a successful monitor run."""
    run_dir = get_run_dir()

    if page is not None:
        try:
            page.screenshot(
                path=str(run_dir / "connected.png"),
                full_page=True,
                timeout=10_000,
            )
        except Exception:
            pass

    return run_dir


def capture_failure_artifacts(
    page: Page | None,
    stage: str,
    message: str,
) -> Path:
    """Save screenshot and page HTML on failure. Returns the run directory."""
    run_dir = get_run_dir()
    metadata = {
        "timestamp": datetime.now(UTC).isoformat(),
        "stage": stage,
        "message": message,
    }
    (run_dir / "failure.json").write_text(json.dumps(metadata, indent=2))

    if page is not None:
        try:
            page.screenshot(
                path=str(run_dir / "failure.png"),
                full_page=True,
                timeout=10_000,
            )
        except Exception:
            pass
        try:
            html = page.content()
            (run_dir / "page.html").write_text(html)
        except Exception:
            pass

    return run_dir


def determine_failure_stage(exc: Exception) -> str:
    """Best-effort classification of which stage failed."""
    from helpers.galaxy_client import (
        EntryPointTimeout,
        ToolNotAvailable,
        ToolStartupFailed,
        ToolStartupTimeout,
    )

    # Custom exception types
    if isinstance(exc, ToolNotAvailable):
        return "tool_not_available"
    if isinstance(exc, ToolStartupTimeout):
        return "job_timeout"
    if isinstance(exc, ToolStartupFailed):
        return "job_error"
    if isinstance(exc, EntryPointTimeout):
        return "entry_point"

    msg = str(exc).lower()

    # Connection / Galaxy down
    if isinstance(exc, (ConnectionError, OSError)):
        return "galaxy_unreachable"
    if "connection" in msg or "unreachable" in msg or "resolve" in msg:
        return "galaxy_unreachable"

    # Auth issues
    if "401" in msg or "403" in msg or "auth" in msg or "credential" in msg:
        return "authentication"

    # Quota / rate limit
    if "quota" in msg or "limit" in msg or "429" in msg:
        return "quota_exceeded"

    # Entry point
    if (
        "entry point" in msg
        or "entry_point" in msg
        or "proxy target missing" in msg
        or "interactive tool proxy" in msg
    ):
        return "entry_point"

    # Tool launch
    if "tool" in msg and ("not found" in msg or "disabled" in msg):
        return "tool_not_available"

    # History
    if "history" in msg:
        return "history"

    # UI verification
    if (
        "ui verification" in msg
        or "meaningful content" in msg
        or "browser" in msg
        or "novnc" in msg
        or "canvas" in msg
        or "vnc" in msg
    ):
        return "ui_verification"

    return "unknown"
