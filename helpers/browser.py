from playwright.sync_api import Page


def verify_physicell_ui(page: Page, tool_url: str, timeout: int = 60_000) -> None:
    """Navigate to the interactive tool URL and verify PhysiCell Studio loads.

    PhysiCell Studio is a PyQt desktop app served via noVNC (port 5800).
    The browser shows a noVNC client that connects to the VNC session.
    Since noVNC renders to a <canvas>, we verify:
      1. The noVNC page loaded (canvas element exists)
      2. The VNC connection is established (connected status)

    Args:
        page: Playwright page instance.
        tool_url: The entry point URL for the running interactive tool.
        timeout: Max milliseconds to wait for connection.

    Raises:
        AssertionError: If noVNC does not connect or canvas is missing.
    """
    page.goto(tool_url, wait_until="domcontentloaded", timeout=timeout)
    page.wait_for_load_state("networkidle", timeout=timeout)

    # noVNC uses a <canvas> element for rendering the remote desktop
    canvas = page.locator("canvas").first
    canvas.wait_for(state="visible", timeout=timeout)

    # Wait for noVNC to establish the VNC connection.
    # noVNC typically shows connection status in a bar or sets body/container
    # classes. The exact indicators depend on the noVNC version:
    #   - Modern noVNC: #noVNC_status shows "Connected"
    #   - Or: body gains class "noVNC_connected"
    #   - Or: the status bar disappears when connected
    # We try multiple strategies.
    connected = _wait_for_vnc_connected(page, timeout)

    assert connected, (
        f"noVNC canvas found at {tool_url} but VNC connection was not confirmed. "
        "The desktop app may not have started inside the container."
    )

    # Take a verification screenshot (always, for the result record)
    try:
        from helpers.results import get_run_dir
        run_dir = get_run_dir()
        page.screenshot(path=str(run_dir / "connected.png"), full_page=True)
    except Exception:
        pass


def _wait_for_vnc_connected(page: Page, timeout: int) -> bool:
    """Try multiple strategies to detect noVNC connected state."""
    half_timeout = timeout // 2

    # Strategy 1: Look for noVNC_connected class on body or container
    try:
        page.wait_for_selector(
            ".noVNC_connected, body.noVNC_connected, #noVNC_container.noVNC_connected",
            state="attached",
            timeout=half_timeout,
        )
        return True
    except Exception:
        pass

    # Strategy 2: Look for status text "Connected"
    try:
        status = page.locator("#noVNC_status, #noVNC_status_bar, [id*='status']")
        if status.count() > 0:
            text = status.first.inner_text()
            if "connected" in text.lower():
                return True
    except Exception:
        pass

    # Strategy 3: Check that the canvas has non-zero dimensions
    # (indicates something is being rendered)
    try:
        canvas = page.locator("canvas").first
        box = canvas.bounding_box()
        if box and box["width"] > 100 and box["height"] > 100:
            return True
    except Exception:
        pass

    # Strategy 4: Wait a bit and check canvas pixel data via JS
    # A blank/black canvas means VNC hasn't rendered yet
    try:
        page.wait_for_timeout(5000)
        has_content = page.evaluate("""() => {
            const canvas = document.querySelector('canvas');
            if (!canvas) return false;
            const ctx = canvas.getContext('2d');
            if (!ctx) return false;
            const w = Math.min(canvas.width, 100);
            const h = Math.min(canvas.height, 100);
            const data = ctx.getImageData(10, 10, w, h).data;
            // Check if there are non-black, non-transparent pixels
            let nonBlank = 0;
            for (let i = 0; i < data.length; i += 4) {
                if (data[i] > 10 || data[i+1] > 10 || data[i+2] > 10) {
                    nonBlank++;
                }
            }
            return nonBlank > 50;
        }""")
        if has_content:
            return True
    except Exception:
        pass

    return False
