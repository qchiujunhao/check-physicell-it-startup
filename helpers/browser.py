from playwright.sync_api import Page, expect


# Selectors/text patterns that indicate PhysiCell UI has loaded.
# Adjust these as needed once the real tool UI is known.
PHYSICELL_READY_INDICATORS = [
    "PhysiCell",
    "physicell",
]


def verify_physicell_ui(page: Page, tool_url: str, timeout: int = 60_000) -> None:
    """Navigate to the interactive tool URL and verify PhysiCell UI loads.

    Args:
        page: Playwright page instance.
        tool_url: The entry point URL for the running interactive tool.
        timeout: Max milliseconds to wait for UI indicators.

    Raises:
        AssertionError: If the UI does not show expected PhysiCell content.
    """
    page.goto(tool_url, wait_until="domcontentloaded", timeout=timeout)

    # Wait for the page to stabilize — interactive tools may redirect
    page.wait_for_load_state("networkidle", timeout=timeout)

    # Check if content is in an iframe
    frames = page.frames
    target_frame = page
    for frame in frames:
        try:
            content = frame.content()
            if any(ind.lower() in content.lower() for ind in PHYSICELL_READY_INDICATORS):
                target_frame = frame
                break
        except Exception:
            continue

    # Verify that at least one indicator is present in page/frame content
    content = target_frame.content()
    found = any(ind.lower() in content.lower() for ind in PHYSICELL_READY_INDICATORS)

    if not found:
        # Try waiting a bit longer for dynamic content
        page.wait_for_timeout(5000)
        content = target_frame.content()
        found = any(ind.lower() in content.lower() for ind in PHYSICELL_READY_INDICATORS)

    assert found, (
        f"PhysiCell UI not detected at {tool_url}. "
        f"Looked for: {PHYSICELL_READY_INDICATORS}"
    )
