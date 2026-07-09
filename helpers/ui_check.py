"""Authenticated, browser-based verification that the PhysiCell tool UI renders.

This logs into Galaxy in a headless browser to obtain a real session, opens the
interactive tool entry point, and waits until the noVNC session has actually
painted a frame -- i.e. the canvas contains non-uniform pixels. That confirms
the tool is genuinely usable rather than merely reachable, and it produces
genuine failures when it is not:

* a proxy/gateway error page (backend not up behind the proxy),
* an unauthenticated bounce to the Galaxy login page (session not accepted),
* a UI that never renders within the window.

Login success is confirmed programmatically via ``/api/users/current`` rather
than by scraping the login markup, so it does not depend on brittle
version-specific selectors. The readiness check is deliberately fail-closed:
only a readable 2D canvas that is large enough and has non-uniform pixels counts
as painted. A canvas that cannot be read (WebGL or cross-origin tainted) or is
too small is never treated as success -- verification keeps waiting and then
fails with diagnostics, so a broken UI is reported rather than passing silently.
On both success and failure the run directory receives a screenshot and page
HTML so the run can be inspected.
"""

import json
import time
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright

from helpers.entry_point import _PROXY_ERROR_STRINGS, InteractiveToolProxyError


class GalaxyLoginError(RuntimeError):
    """Raised when a Galaxy browser session could not be established."""


class ToolUINotReady(RuntimeError):
    """Raised when the tool UI never rendered within the window."""


# Sample every Nth pixel (stride in RGBA bytes) when checking for a painted
# frame; a rendered noVNC framebuffer has ample colour variance.
_PIXEL_STRIDE = 4 * 97

# A real noVNC framebuffer is a full desktop resolution; anything smaller than
# this on a side is a decorative or hidden canvas, not the tool surface.
_MIN_CANVAS_PX = 100

# Fail-closed: only a readable 2D canvas that is large enough AND has non-uniform
# pixels counts as painted. A canvas we cannot read (WebGL/tainted) or one that
# is too small is NOT treated as success -- we keep waiting and then fail with
# diagnostics, so a genuinely broken UI never passes silently.
_CANVAS_PAINTED_JS = """
() => {
  const canvases = Array.from(document.querySelectorAll('canvas'));
  const diag = {found: canvases.length > 0, sized: false, readable: false,
                painted: false};
  for (const c of canvases) {
    const w = c.width, h = c.height;
    if (w < __MIN__ || h < __MIN__) continue;
    diag.sized = true;
    let ctx = null;
    try { ctx = c.getContext('2d'); } catch (e) { ctx = null; }
    if (!ctx) continue;
    let data;
    try { data = ctx.getImageData(0, 0, w, h).data; }
    catch (e) { continue; }
    diag.readable = true;
    const r0 = data[0], g0 = data[1], b0 = data[2];
    for (let i = 0; i < data.length; i += __STRIDE__) {
      if (data[i] !== r0 || data[i + 1] !== g0 || data[i + 2] !== b0) {
        diag.painted = true;
        return diag;
      }
    }
  }
  return diag;
}
""".replace("__STRIDE__", str(_PIXEL_STRIDE)).replace("__MIN__", str(_MIN_CANVAS_PX))


def _proxy_error_from_text(text: str) -> str | None:
    lowered = text.lower()
    for marker in _PROXY_ERROR_STRINGS:
        if marker in lowered:
            return f"Interactive tool proxy error: {marker}"
    return None


def _looks_like_login_url(url: str) -> bool:
    return "/login" in url.split("?", 1)[0].lower()


def _is_authenticated_user(data: object) -> bool:
    return isinstance(data, dict) and bool(data.get("email"))


def _body_text(page: Page) -> str:
    try:
        return page.evaluate("() => document.body ? document.body.innerText : ''") or ""
    except PlaywrightError:
        return ""


def _confirm_authenticated(page: Page, base_url: str, timeout_ms: int) -> None:
    api_url = f"{base_url.rstrip('/')}/api/users/current"
    deadline = time.time() + timeout_ms / 1000
    last = "no response from /api/users/current"
    while time.time() < deadline:
        try:
            response = page.request.get(api_url)
            if response.ok:
                if _is_authenticated_user(response.json()):
                    return
                last = "session is still anonymous"
            else:
                last = f"HTTP {response.status} from /api/users/current"
        except PlaywrightError as exc:
            last = str(exc)
        page.wait_for_timeout(1000)
    raise GalaxyLoginError(f"Galaxy login did not establish a session: {last}")


def _login(
    page: Page,
    base_url: str,
    username: str,
    password: str,
    timeout_ms: int,
) -> None:
    login_url = f"{base_url.rstrip('/')}/login"
    page.goto(login_url, wait_until="domcontentloaded", timeout=timeout_ms)

    password_input = page.locator("input[type='password']").first
    try:
        password_input.wait_for(state="visible", timeout=timeout_ms)
    except PlaywrightError as exc:
        raise GalaxyLoginError(
            "Could not find the password field on the Galaxy login page"
        ) from exc

    username_input = None
    for selector in (
        "input[name='login']",
        "input[type='email']",
        "input[name='email']",
        "input[name='username']",
        "input[type='text']",
    ):
        candidate = page.locator(selector).first
        if candidate.count() > 0:
            username_input = candidate
            break
    if username_input is None:
        raise GalaxyLoginError(
            "Could not find the username field on the Galaxy login page"
        )

    username_input.fill(username)
    password_input.fill(password)

    submit = page.locator(
        "button[type='submit'], button:has-text('Login'), button:has-text('Sign in')"
    ).first
    if submit.count() > 0:
        submit.click()
    else:
        password_input.press("Enter")

    _confirm_authenticated(page, base_url, timeout_ms)


def _wait_for_rendered_ui(page: Page, tool_url: str, timeout_ms: int) -> None:
    page.goto(tool_url, wait_until="domcontentloaded", timeout=timeout_ms)
    deadline = time.time() + timeout_ms / 1000

    while True:
        proxy_error = _proxy_error_from_text(_body_text(page))
        if proxy_error:
            raise InteractiveToolProxyError(proxy_error)

        if _looks_like_login_url(page.url):
            raise GalaxyLoginError(
                "Interactive tool entry point redirected to a login page; "
                "the Galaxy session was not accepted"
            )

        try:
            status = page.evaluate(_CANVAS_PAINTED_JS)
        except PlaywrightError:
            status = {}

        if status.get("painted"):
            return

        if time.time() >= deadline:
            raise ToolUINotReady(
                "PhysiCell tool UI did not paint a readable frame within "
                f"{timeout_ms / 1000:.0f}s (canvas found={status.get('found')}, "
                f"sized={status.get('sized')}, readable={status.get('readable')})"
            )
        page.wait_for_timeout(2000)


def _save_artifacts(page: Page, run_dir: Path, prefix: str) -> None:
    try:
        page.screenshot(
            path=str(run_dir / f"{prefix}.png"),
            full_page=True,
            timeout=10_000,
        )
    except PlaywrightError:
        pass
    if prefix == "failure":
        try:
            (run_dir / "page.html").write_text(page.content())
        except PlaywrightError:
            pass
        try:
            (run_dir / "ui_state.json").write_text(
                json.dumps({"url": page.url}, indent=2)
            )
        except (PlaywrightError, OSError):
            pass


def verify_tool_ui(
    base_url: str,
    tool_url: str,
    username: str,
    password: str,
    run_dir: Path,
    ui_timeout: int = 60,
    login_timeout: int = 30,
) -> None:
    """Log into Galaxy and confirm the tool UI actually renders.

    Raises:
        GalaxyLoginError: The Galaxy session could not be established or was not
            accepted by the interactive-tool proxy.
        InteractiveToolProxyError: The entry point served a proxy/gateway error.
        ToolUINotReady: The tool UI never painted a frame within ``ui_timeout``.
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        try:
            _login(page, base_url, username, password, login_timeout * 1000)
            _wait_for_rendered_ui(page, tool_url, ui_timeout * 1000)
            _save_artifacts(page, run_dir, "connected")
        except Exception:
            _save_artifacts(page, run_dir, "failure")
            raise
        finally:
            context.close()
            browser.close()
