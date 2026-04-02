import math
import time

import pytest
from playwright.sync_api import Page

from config.settings import (
    HISTORY_NAME,
    PHYSICELL_TOOL_ID,
    STARTUP_EXPECTED_SECONDS,
    STARTUP_TIMEOUT_SECONDS,
)
from helpers.browser import verify_physicell_ui
from helpers.galaxy_client import (
    get_galaxy_instance,
    get_interactive_tool_url,
    get_or_create_history,
    launch_physicell,
    stop_interactive_tool,
    wait_for_tool_ready,
)
from helpers.results import (
    build_result,
    capture_failure_artifacts,
    determine_failure_stage,
    write_result,
)


def seconds_remaining(deadline: float) -> int:
    return max(1, math.ceil(deadline - time.time()))


@pytest.mark.timeout(STARTUP_TIMEOUT_SECONDS + 120)
def test_physicell_startup(page: Page) -> None:
    """End-to-end test: launch PhysiCell on Galaxy and verify the UI loads."""
    gi = None
    job_id = None
    startup_start = None

    try:
        # Connect to Galaxy
        t0 = time.time()
        gi = get_galaxy_instance()
        print(f"\n[timing] Galaxy connection: {time.time() - t0:.1f}s")

        # Prepare a clean history
        t0 = time.time()
        history_id = get_or_create_history(gi, HISTORY_NAME)
        print(f"[timing] History setup: {time.time() - t0:.1f}s")

        # Launch the interactive tool — start startup timer here
        t0 = time.time()
        job_id = launch_physicell(gi, history_id, PHYSICELL_TOOL_ID)
        print(f"[timing] Tool launch API call: {time.time() - t0:.1f}s")

        startup_start = time.time()
        deadline = startup_start + STARTUP_TIMEOUT_SECONDS

        # Wait for the container to be running
        t0 = time.time()
        wait_for_tool_ready(gi, job_id, seconds_remaining(deadline))
        print(f"[timing] Job queued → running: {time.time() - t0:.1f}s")

        # Get the entry point URL — this is when the tool session is available
        t0 = time.time()
        tool_url = get_interactive_tool_url(
            gi, job_id, timeout=seconds_remaining(deadline)
        )
        print(f"[timing] Entry point available: {time.time() - t0:.1f}s")

        startup_seconds = time.time() - startup_start
        print(f"[timing] Total startup (running + entry point): {startup_seconds:.1f}s")

        # Verify the PhysiCell UI loads in the browser (not counted in startup time)
        t0 = time.time()
        verify_physicell_ui(
            page,
            tool_url,
            timeout=seconds_remaining(deadline) * 1000,
        )
        print(f"[timing] Browser verification: {time.time() - t0:.1f}s")

        result = build_result(True, startup_seconds)
        result_path = write_result(result)
        print(f"\nPhysiCell session available in {startup_seconds:.1f}s")
        print(f"Result written to {result_path}")

        if result["status"] == "slow":
            pytest.fail(
                f"Tool started but took {startup_seconds:.1f}s "
                f"(expected < {STARTUP_EXPECTED_SECONDS}s)"
            )

    except Exception as exc:
        startup_seconds = time.time() - startup_start if startup_start else None
        stage = determine_failure_stage(exc)
        capture_failure_artifacts(page, stage, str(exc))
        result_path = write_result(
            build_result(False, startup_seconds, stage, str(exc))
        )
        print(f"\nPhysiCell startup failed at stage '{stage}'"
              f"{f' after {startup_seconds:.1f}s' if startup_seconds else ''}")
        print(f"Result written to {result_path}")
        raise

    finally:
        # Always stop the interactive tool to free the container
        if gi and job_id:
            print("\nStopping interactive tool session...")
            stop_interactive_tool(gi, job_id)
            print("Interactive tool session stopped.")
