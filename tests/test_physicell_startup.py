import pytest
from playwright.sync_api import Page

from config.settings import STARTUP_TIMEOUT_SECONDS
from helpers.monitor import run_physicell_monitor


@pytest.mark.integration
@pytest.mark.timeout(STARTUP_TIMEOUT_SECONDS + 120)
def test_physicell_startup(page: Page) -> None:
    """Live end-to-end check against a configured Galaxy instance."""
    run_physicell_monitor(page)
