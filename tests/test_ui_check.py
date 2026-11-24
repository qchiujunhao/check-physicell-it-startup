from pathlib import Path

import pytest
from playwright.sync_api import Error as PlaywrightError

from helpers.entry_point import InteractiveToolProxyError
from helpers.results import determine_failure_stage
from helpers.ui_check import (
    GalaxyLoginError,
    GalaxyPageLoadError,
    ToolUINotReady,
    _is_authenticated_user,
    _looks_like_login_url,
    _open_login_page,
    _proxy_error_from_text,
    _save_artifacts,
    _wait_for_rendered_ui,
)

# The exact error the scheduled monitor hit when the login page stalled.
_LOGIN_TIMEOUT_MESSAGE = (
    "Page.goto: Timeout 30000ms exceeded.\n"
    "Call log:\n"
    '  - navigating to "https://usegalaxy.org/login", '
    'waiting until "domcontentloaded"\n'
)


class _FakeSession:
    def __init__(self, page: "_FakePage") -> None:
        self._page = page

    def send(self, method: str) -> None:
        self._page.events.append(f"cdp:{method}")

    def detach(self) -> None:
        pass


class _FakePage:
    url = "about:blank"

    def __init__(self, context: "_FakeContext", goto_error: Exception | None) -> None:
        self.context = context
        self.events: list[str] = []
        self._goto_error = goto_error

    def goto(self, url: str, **_: object) -> None:
        self.events.append(f"goto:{url}")
        if self._goto_error is not None:
            raise self._goto_error

    def screenshot(self, **_: object) -> None:
        self.events.append("screenshot")

    def content(self) -> str:
        self.events.append("content")
        return "<html></html>"


class _FakeContext:
    def __init__(self, goto_error: Exception | None, cdp_works: bool = True) -> None:
        self.closed = False
        self._cdp_works = cdp_works
        self.page = _FakePage(self, goto_error)

    def new_page(self) -> _FakePage:
        return self.page

    def new_cdp_session(self, page: _FakePage) -> _FakeSession:
        if not self._cdp_works:
            raise PlaywrightError("CDP session is not available")
        return _FakeSession(page)

    def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    """Hands out one context per attempt; ``outcomes`` is its goto error or None."""

    def __init__(self, outcomes: list[Exception | None]) -> None:
        self._outcomes = outcomes
        self.contexts: list[_FakeContext] = []

    def new_context(self, **_: object) -> _FakeContext:
        context = _FakeContext(self._outcomes[len(self.contexts)])
        self.contexts.append(context)
        return context


def test_proxy_error_from_text_detects_known_pages() -> None:
    assert _proxy_error_from_text("Proxy target missing") is not None
    assert _proxy_error_from_text("502 Bad Gateway") is not None
    assert _proxy_error_from_text("<html>PhysiCell Studio</html>") is None


def test_looks_like_login_url() -> None:
    assert _looks_like_login_url("https://usegalaxy.org/login?redirect=/x") is True
    assert _looks_like_login_url("https://usegalaxy.org/login/start") is True
    assert _looks_like_login_url("https://tool.usegalaxy.org/ep/abc") is False


def test_is_authenticated_user() -> None:
    assert _is_authenticated_user({"email": "user@example.org"}) is True
    assert _is_authenticated_user({"email": ""}) is False
    assert _is_authenticated_user({"id": "x"}) is False
    assert _is_authenticated_user(None) is False


def test_determine_failure_stage_maps_ui_exceptions() -> None:
    assert (
        determine_failure_stage(GalaxyLoginError("session not accepted"))
        == "authentication"
    )
    assert (
        determine_failure_stage(ToolUINotReady("did not render")) == "ui_verification"
    )
    assert (
        determine_failure_stage(
            InteractiveToolProxyError("Interactive tool proxy error: target missing")
        )
        == "entry_point"
    )


def test_page_load_error_is_not_reported_as_authentication() -> None:
    # The message mentions "login", which the keyword fallback would otherwise
    # map to "authentication" even though no credentials were submitted.
    exc = GalaxyPageLoadError(
        "Galaxy login page did not load in 3 attempt(s) of 30s each: "
        "Page.goto: Timeout 30000ms exceeded."
    )

    assert determine_failure_stage(exc) == "galaxy_unreachable"


def test_open_login_page_retries_in_a_fresh_context(tmp_path: Path) -> None:
    browser = _FakeBrowser([PlaywrightError(_LOGIN_TIMEOUT_MESSAGE), None])
    logs: list[str] = []

    context, page = _open_login_page(
        browser,
        "https://usegalaxy.org/",
        30_000,
        tmp_path,
        retry_pause=0,
        log=logs.append,
    )

    stalled, loaded = browser.contexts
    assert (context, page) == (loaded, loaded.page)
    assert stalled.closed is True
    assert loaded.closed is False
    assert loaded.page.events == ["goto:https://usegalaxy.org/login"]
    assert len(logs) == 1
    assert "attempt 1/3 failed" in logs[0]
    assert "Timeout 30000ms exceeded" in logs[0]
    assert "\n" not in logs[0]
    # A recovered load is not a failure, so it leaves no failure artifacts.
    assert list(tmp_path.iterdir()) == []


def test_open_login_page_gives_up_with_page_load_error(tmp_path: Path) -> None:
    browser = _FakeBrowser([PlaywrightError(_LOGIN_TIMEOUT_MESSAGE)] * 3)

    with pytest.raises(GalaxyPageLoadError) as excinfo:
        _open_login_page(
            browser,
            "https://usegalaxy.org",
            30_000,
            tmp_path,
            retry_pause=0,
            log=lambda _: None,
        )

    message = str(excinfo.value)
    assert "3 attempt(s) of 30s each" in message
    assert "Timeout 30000ms exceeded" in message
    assert "Call log" not in message
    assert len(browser.contexts) == 3
    assert all(context.closed for context in browser.contexts)
    # Only the final attempt is captured, and only after the load was stopped.
    assert [c.page.events for c in browser.contexts[:2]] == [
        ["goto:https://usegalaxy.org/login"]
    ] * 2
    assert browser.contexts[2].page.events == [
        "goto:https://usegalaxy.org/login",
        "cdp:Page.stopLoading",
        "screenshot",
        "content",
    ]
    assert (tmp_path / "page.html").read_text() == "<html></html>"
    assert (tmp_path / "ui_state.json").exists()
    assert determine_failure_stage(excinfo.value) == "galaxy_unreachable"


def test_open_login_page_honours_a_single_attempt(tmp_path: Path) -> None:
    browser = _FakeBrowser([PlaywrightError(_LOGIN_TIMEOUT_MESSAGE)])

    with pytest.raises(GalaxyPageLoadError, match=r"1 attempt\(s\)"):
        _open_login_page(
            browser,
            "https://usegalaxy.org",
            30_000,
            tmp_path,
            attempts=1,
            retry_pause=0,
        )

    assert len(browser.contexts) == 1


def test_failure_artifacts_skip_html_when_loading_cannot_be_stopped(
    tmp_path: Path,
) -> None:
    # page.content() takes no timeout and blocks on a stalled navigation, so it
    # must not be called unless the load was stopped first.
    context = _FakeContext(None, cdp_works=False)

    _save_artifacts(context.page, tmp_path, "failure")

    assert context.page.events == ["screenshot"]
    assert not (tmp_path / "page.html").exists()
    assert (tmp_path / "ui_state.json").exists()


def test_success_artifacts_do_not_stop_the_live_page(tmp_path: Path) -> None:
    context = _FakeContext(None)

    _save_artifacts(context.page, tmp_path, "connected")

    assert context.page.events == ["screenshot"]


def test_tool_page_load_error_is_reported_as_ui_not_ready() -> None:
    tool_url = "https://abc123.interactivetool.usegalaxy.org/"
    context = _FakeContext(
        PlaywrightError(
            "Page.goto: Timeout 60000ms exceeded.\n"
            f'Call log:\n  - navigating to "{tool_url}"\n'
        )
    )

    with pytest.raises(ToolUINotReady) as excinfo:
        _wait_for_rendered_ui(context.page, tool_url, 60_000)

    message = str(excinfo.value)
    assert "did not load within 60s" in message
    assert "Timeout 60000ms exceeded" in message
    assert tool_url not in message
    assert determine_failure_stage(excinfo.value) == "ui_verification"
