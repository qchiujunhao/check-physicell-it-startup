import json
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import Page

from config.settings import GALAXY_BASE_URL, OUTPUT_DIR


def build_result(
    success: bool,
    startup_seconds: float | None,
    failure_stage: str | None = None,
    failure_message: str | None = None,
) -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": GALAXY_BASE_URL,
        "success": success,
        "startup_seconds": round(startup_seconds, 2) if startup_seconds is not None else None,
        "failure_stage": failure_stage,
        "failure_message": failure_message,
    }


_current_run_dir: Path | None = None


def get_run_dir() -> Path:
    """Get or create a timestamped directory for this run's output.

    Returns the same directory within a single run.
    """
    global _current_run_dir
    if _current_run_dir is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        _current_run_dir = OUTPUT_DIR / ts
    _current_run_dir.mkdir(parents=True, exist_ok=True)
    return _current_run_dir


def write_result(result: dict) -> Path:
    """Write result JSON to a timestamped directory."""
    run_dir = get_run_dir()
    path = run_dir / "result.json"
    path.write_text(json.dumps(result, indent=2))
    return path


def capture_failure_artifacts(
    page: Page | None,
    stage: str,
    message: str,
) -> Path:
    """Save screenshot and page HTML on failure. Returns the run directory."""
    run_dir = get_run_dir()

    if page is not None:
        try:
            page.screenshot(path=str(run_dir / "failure.png"), full_page=True)
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
        ToolStartupFailed,
        ToolStartupTimeout,
    )

    name = type(exc).__name__
    if isinstance(exc, ToolStartupTimeout):
        return "job_timeout"
    if isinstance(exc, ToolStartupFailed):
        return "job_error"
    if isinstance(exc, EntryPointTimeout):
        return "entry_point"
    if "entry point" in str(exc).lower() or "entry_point" in str(exc).lower():
        return "entry_point"
    if "login" in str(exc).lower() or "auth" in str(exc).lower():
        return "authentication"
    if "history" in str(exc).lower():
        return "history"
    if "verify" in str(exc).lower() or "physicell" in str(exc).lower():
        return "ui_verification"
    return "unknown"
