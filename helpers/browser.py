import time

from playwright.sync_api import Page


def verify_physicell_ui(page: Page, tool_url: str, timeout: int = 60_000) -> None:
    """Navigate to the interactive tool URL and verify PhysiCell Studio loads.

    PhysiCell Studio is a PyQt desktop app served via noVNC (port 5800).
    Since noVNC renders to a <canvas>, we verify that the canvas exists
    and the VNC session has connected and rendered content.

    Args:
        page: Playwright page instance.
        tool_url: The entry point URL for the running interactive tool.
        timeout: Max milliseconds to wait for connection.

    Raises:
        AssertionError: If noVNC does not connect or canvas is missing.
    """
    page.goto(tool_url, wait_until="domcontentloaded", timeout=timeout)

    # Wait for a canvas element — this is the noVNC rendering surface
    canvas = page.locator("canvas").first
    canvas.wait_for(state="visible", timeout=timeout)

    # Poll for VNC connected state with short intervals
    connected = _wait_for_vnc_connected(page, timeout_ms=timeout)

    assert connected, (
        f"noVNC canvas found at {tool_url} but VNC connection was not confirmed. "
        "The desktop app may not have started inside the container."
    )

    # Take a verification screenshot for the result record
    try:
        from helpers.results import get_run_dir
        run_dir = get_run_dir()
        page.screenshot(path=str(run_dir / "connected.png"), full_page=True)
    except Exception:
        pass


def _wait_for_vnc_connected(page: Page, timeout_ms: int) -> bool:
    """Poll multiple indicators to detect noVNC connected state.

    Instead of trying strategies sequentially with large timeouts,
    check all indicators in a tight loop every 2 seconds.
    """
    deadline = time.time() + (timeout_ms / 1000)

    while time.time() < deadline:
        # Check 1: noVNC_connected CSS class
        try:
            el = page.query_selector(
                ".noVNC_connected, body.noVNC_connected, "
                "#noVNC_container.noVNC_connected"
            )
            if el:
                return True
        except Exception:
            pass

        # Check 2: Status text contains "Connected"
        try:
            for sel in ("#noVNC_status", "#noVNC_status_bar", "[id*='status']"):
                loc = page.locator(sel)
                if loc.count() > 0:
                    text = loc.first.inner_text()
                    if "connected" in text.lower():
                        return True
        except Exception:
            pass

        # Check 3: Canvas has non-trivial pixel content
        try:
            has_content = page.evaluate("""() => {
                const canvas = document.querySelector('canvas');
                if (!canvas || canvas.width < 100 || canvas.height < 100)
                    return false;
                const ctx = canvas.getContext('2d');
                if (!ctx) return false;
                const data = ctx.getImageData(10, 10, 80, 80).data;
                let nonBlank = 0;
                for (let i = 0; i < data.length; i += 4) {
                    if (data[i] > 10 || data[i+1] > 10 || data[i+2] > 10)
                        nonBlank++;
                }
                return nonBlank > 50;
            }""")
            if has_content:
                return True
        except Exception:
            pass

        page.wait_for_timeout(2000)

    return False
