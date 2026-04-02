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
    wait_for_tool_ready,
)
from helpers.results import (
    build_result,
    capture_failure_artifacts,
    determine_failure_stage,
    write_result,
)


@pytest.mark.timeout(STARTUP_TIMEOUT_SECONDS + 120)
def test_physicell_startup(page: Page) -> None:
    """End-to-end test: launch PhysiCell on Galaxy and verify the UI loads."""
    start = time.time()

    try:
        # Connect to Galaxy
        gi = get_galaxy_instance()

        # Prepare a clean history
        history_id = get_or_create_history(gi, HISTORY_NAME)

        # Launch the interactive tool
        job_id = launch_physicell(gi, history_id, PHYSICELL_TOOL_ID)

        # Wait for the container to be running
        wait_for_tool_ready(gi, job_id, STARTUP_TIMEOUT_SECONDS)

        # Get the entry point URL
        tool_url = get_interactive_tool_url(gi, job_id)

        # Verify the PhysiCell UI loads in the browser
        verify_physicell_ui(page, tool_url)

        elapsed = time.time() - start
        result_path = write_result(build_result(True, elapsed))
        print(f"\nPhysiCell started successfully in {elapsed:.1f}s")
        print(f"Result written to {result_path}")

    except Exception as exc:
        elapsed = time.time() - start
        stage = determine_failure_stage(exc)
        capture_failure_artifacts(page, stage, str(exc))
        result_path = write_result(
            build_result(False, elapsed, stage, str(exc))
        )
        print(f"\nPhysiCell startup failed at stage '{stage}' after {elapsed:.1f}s")
        print(f"Result written to {result_path}")
        raise
