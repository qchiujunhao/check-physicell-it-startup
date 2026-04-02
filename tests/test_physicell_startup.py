import math
import time

import pytest
from playwright.sync_api import Page

from config.settings import (
    HISTORY_NAME,
    PHYSICELL_TOOL_ID,
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
        gi = get_galaxy_instance()

        # Prepare a clean history
        history_id = get_or_create_history(gi, HISTORY_NAME)

        # Launch the interactive tool — start timing here
        job_id = launch_physicell(gi, history_id, PHYSICELL_TOOL_ID)
        startup_start = time.time()
        deadline = startup_start + STARTUP_TIMEOUT_SECONDS

        # Wait for the container to be running
        wait_for_tool_ready(gi, job_id, seconds_remaining(deadline))

        # Get the entry point URL
        tool_url = get_interactive_tool_url(
            gi, job_id, timeout=seconds_remaining(deadline)
        )

        # Verify the PhysiCell UI loads in the browser
        verify_physicell_ui(
            page,
            tool_url,
            timeout=seconds_remaining(deadline) * 1000,
        )

        startup_seconds = time.time() - startup_start
        result_path = write_result(build_result(True, startup_seconds))
        print(f"\nPhysiCell session available in {startup_seconds:.1f}s")
        print(f"Result written to {result_path}")

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
