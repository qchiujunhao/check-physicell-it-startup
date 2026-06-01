import math
import time
from collections.abc import Callable
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from config.settings import (
    GALAXY_BASE_URL,
    GALAXY_STATUSPAGE_SUMMARY_URL,
    HISTORY_NAME,
    PHYSICELL_TOOL_ID,
    PHYSICELL_TOOL_VERSION_POLICY,
    PREFLIGHT_ENABLED,
    PREFLIGHT_TIMEOUT_SECONDS,
    PURGE_REUSED_HISTORY,
    REQUIRE_UI_VERIFICATION,
    STARTUP_EXPECTED_SECONDS,
    STARTUP_TIMEOUT_SECONDS,
)
from helpers.browser import InteractiveToolProxyError, verify_physicell_ui
from helpers.galaxy_client import (
    get_galaxy_instance,
    get_interactive_tool_url,
    get_or_create_history,
    launch_physicell,
    run_preflight_checks,
    stop_interactive_tool,
    wait_for_tool_ready,
)
from helpers.results import (
    build_result,
    capture_failure_artifacts,
    capture_success_artifacts,
    write_result,
)


class SlowStartup(Exception):
    pass


def seconds_remaining(deadline: float) -> int:
    return max(1, math.ceil(deadline - time.time()))


def _time_stage(
    name: str,
    timings: dict[str, float],
    log: Callable[[str], None],
    operation: Callable[[], object],
) -> object:
    start = time.time()
    try:
        return operation()
    finally:
        elapsed = time.time() - start
        timings[name] = elapsed
        log(f"[timing] {name.replace('_', ' ')}: {elapsed:.1f}s")


def _redact_message(message: str, sensitive_values: list[str]) -> str:
    redacted = message
    for value in sensitive_values:
        if value:
            redacted = redacted.replace(value, "<interactive-tool-url>")
    return redacted


def run_physicell_monitor(
    page: Page,
    log: Callable[[str], None] = print,
) -> Path:
    """Run the end-to-end PhysiCell startup monitor and write result artifacts."""
    gi = None
    job_id = None
    startup_start = None
    startup_seconds = None
    timings: dict[str, float] = {}
    preflight = None
    selected_tool_id = PHYSICELL_TOOL_ID

    try:
        if PREFLIGHT_ENABLED:
            preflight = _time_stage(
                "preflight",
                timings,
                log,
                lambda: run_preflight_checks(
                    GALAXY_BASE_URL,
                    PHYSICELL_TOOL_ID,
                    PHYSICELL_TOOL_VERSION_POLICY,
                    GALAXY_STATUSPAGE_SUMMARY_URL,
                    PREFLIGHT_TIMEOUT_SECONDS,
                ),
            )
            selected_tool_id = preflight.get("selected_tool_id", PHYSICELL_TOOL_ID)
            status = preflight.get("status", "unknown")
            log(
                "[preflight] "
                f"status={status}, policy={PHYSICELL_TOOL_VERSION_POLICY}, "
                f"tool={selected_tool_id}"
            )

        gi = _time_stage(
            "galaxy_connection",
            timings,
            log,
            get_galaxy_instance,
        )

        history_id = _time_stage(
            "history_setup",
            timings,
            log,
            lambda: get_or_create_history(
                gi,
                HISTORY_NAME,
                purge_existing=PURGE_REUSED_HISTORY,
            ),
        )

        job_id = _time_stage(
            "tool_launch_api",
            timings,
            log,
            lambda: launch_physicell(gi, history_id, selected_tool_id),
        )

        startup_start = time.time()
        deadline = startup_start + STARTUP_TIMEOUT_SECONDS

        _time_stage(
            "job_running",
            timings,
            log,
            lambda: wait_for_tool_ready(
                gi,
                job_id,
                seconds_remaining(deadline),
            ),
        )

        tool_url = _time_stage(
            "entry_point_available",
            timings,
            log,
            lambda: get_interactive_tool_url(
                gi,
                job_id,
                timeout=seconds_remaining(deadline),
            ),
        )

        startup_seconds = time.time() - startup_start
        log(f"[timing] startup total: {startup_seconds:.1f}s")

        ui_verified = True
        ui_error = None
        try:
            _time_stage(
                "browser_verification",
                timings,
                log,
                lambda: verify_physicell_ui(page, tool_url, timeout=30_000),
            )
        except Exception as exc:
            ui_verified = False
            ui_error = _redact_message(str(exc), [tool_url])
            timings.setdefault("browser_verification", 30.0)
            log(f"[timing] browser verification failed: {ui_error}")
            if isinstance(exc, InteractiveToolProxyError):
                raise RuntimeError(
                    f"Interactive tool proxy failed: {ui_error}"
                ) from exc
            if REQUIRE_UI_VERIFICATION:
                raise RuntimeError(f"UI verification failed: {ui_error}") from exc

        capture_success_artifacts(page)

        result = build_result(
            True,
            startup_seconds,
            timings=timings,
            ui_verified=ui_verified,
            ui_required=REQUIRE_UI_VERIFICATION,
            preflight=preflight,
            configured_tool_id=PHYSICELL_TOOL_ID,
            tool_id=selected_tool_id,
            tool_version_policy=PHYSICELL_TOOL_VERSION_POLICY,
        )
        if ui_error:
            result["ui_error"] = ui_error

        result_path = write_result(result)
        log("")
        log(f"PhysiCell session available in {startup_seconds:.1f}s")
        log(f"Result written to {result_path}")

        if result["status"] == "slow":
            message = (
                f"Tool started but took {startup_seconds:.1f}s "
                f"(expected < {STARTUP_EXPECTED_SECONDS}s)"
            )
            log(message)
            raise SlowStartup(message)

        return result_path

    except SlowStartup:
        raise

    except Exception as exc:
        startup_seconds = time.time() - startup_start if startup_start else None
        from helpers.results import determine_failure_stage

        stage = determine_failure_stage(exc)
        capture_failure_artifacts(page, stage, str(exc))
        result_path = write_result(
            build_result(
                False,
                startup_seconds,
                stage,
                str(exc),
                timings=timings,
                ui_verified=False if stage == "ui_verification" else None,
                ui_required=REQUIRE_UI_VERIFICATION,
                preflight=preflight,
                configured_tool_id=PHYSICELL_TOOL_ID,
                tool_id=selected_tool_id,
                tool_version_policy=PHYSICELL_TOOL_VERSION_POLICY,
            )
        )
        log("")
        if startup_seconds is None:
            log(f"PhysiCell startup failed at stage '{stage}'")
        else:
            log(
                f"PhysiCell startup failed at stage '{stage}' "
                f"after {startup_seconds:.1f}s"
            )
        log(f"Result written to {result_path}")
        raise

    finally:
        if gi and job_id:
            log("")
            log("Stopping interactive tool session...")
            stop_interactive_tool(gi, job_id)
            log("Interactive tool session stopped.")


def main() -> int:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        try:
            run_physicell_monitor(page)
        except Exception:
            return 1
        finally:
            browser.close()

    return 0
