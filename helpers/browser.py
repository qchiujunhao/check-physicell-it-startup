import time

from playwright.sync_api import Page


def verify_physicell_ui(page: Page, tool_url: str, timeout: int = 30_000) -> None:
    """Navigate to the interactive tool URL and check if something loads.

    This is a best-effort check. The tool session is served via noVNC
    which may use a <canvas>, an <iframe>, or other structures depending
    on the version. We try to detect any sign of a loaded page.

    Args:
        page: Playwright page instance.
        tool_url: The entry point URL for the running interactive tool.
        timeout: Max milliseconds to wait.

    Raises:
        Exception: If the page fails to load or shows no content.
    """
    page.goto(tool_url, wait_until="domcontentloaded", timeout=timeout)

    deadline = time.time() + (timeout / 1000)

    while time.time() < deadline:
        # Check for any meaningful page content
        if _page_has_content(page):
            return

        page.wait_for_timeout(2000)

    raise RuntimeError(
        f"Page at {tool_url} loaded but no meaningful content detected "
        f"within {timeout / 1000:.0f}s"
    )


def _page_has_content(page: Page) -> bool:
    """Check if the page has loaded meaningful content."""

    # Check 1: Canvas element (noVNC)
    try:
        canvas = page.query_selector("canvas")
        if canvas and canvas.is_visible():
            return True
    except Exception:
        pass

    # Check 2: iframe (some Galaxy tool wrappers)
    try:
        iframe = page.query_selector("iframe")
        if iframe:
            return True
    except Exception:
        pass

    # Check 3: noVNC connected class
    try:
        el = page.query_selector(".noVNC_connected, #noVNC_container")
        if el:
            return True
    except Exception:
        pass

    # Check 4: Page body has substantial content (not just a blank/error page)
    try:
        body_text = page.evaluate("() => document.body?.innerText?.trim() || ''")
        # Ignore near-empty pages or generic error pages
        if len(body_text) > 100:
            return True
    except Exception:
        pass

    return False
