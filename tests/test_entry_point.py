import io
from urllib.error import HTTPError, URLError

import pytest

from helpers import entry_point
from helpers.entry_point import InteractiveToolProxyError, verify_entry_point


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._body if size == -1 else self._body[:size]


def _patch_urlopen(monkeypatch, handler) -> None:
    monkeypatch.setattr(entry_point, "urlopen", lambda request, timeout: handler())


def test_verify_entry_point_passes_on_normal_page(monkeypatch) -> None:
    _patch_urlopen(monkeypatch, lambda: _FakeResponse(b"<html>PhysiCell Studio</html>"))
    verify_entry_point("http://tool.example/entry")


def test_verify_entry_point_fails_on_proxy_target_missing(monkeypatch) -> None:
    _patch_urlopen(monkeypatch, lambda: _FakeResponse(b"Proxy target missing"))
    with pytest.raises(InteractiveToolProxyError):
        verify_entry_point("http://tool.example/entry", timeout=0)


def test_verify_entry_point_fails_on_gateway_status(monkeypatch) -> None:
    def handler():
        raise HTTPError("http://tool.example/entry", 502, "Bad Gateway", {}, None)

    _patch_urlopen(monkeypatch, handler)
    with pytest.raises(InteractiveToolProxyError):
        verify_entry_point("http://tool.example/entry", timeout=0)


def test_verify_entry_point_passes_on_auth_redirect_status(monkeypatch) -> None:
    def handler():
        raise HTTPError("http://tool.example/entry", 403, "Forbidden", {}, None)

    _patch_urlopen(monkeypatch, handler)
    verify_entry_point("http://tool.example/entry", timeout=0)


def test_verify_entry_point_fails_when_no_response(monkeypatch) -> None:
    def handler():
        raise URLError("timed out")

    _patch_urlopen(monkeypatch, handler)
    with pytest.raises(InteractiveToolProxyError):
        verify_entry_point("http://tool.example/entry", timeout=0)


def test_verify_entry_point_recovers_from_transient_error(monkeypatch) -> None:
    monkeypatch.setattr(entry_point.time, "sleep", lambda _: None)
    calls = {"n": 0}

    def handler():
        calls["n"] += 1
        if calls["n"] == 1:
            raise URLError("connection reset")
        return _FakeResponse(b"<html>PhysiCell Studio</html>")

    _patch_urlopen(monkeypatch, handler)
    verify_entry_point("http://tool.example/entry", timeout=30, poll_interval=1)
    assert calls["n"] == 2


# --- how long the entry point stayed unreachable, and what was answering ---

_TOOL_URL = "https://ep1-secrettoken.interactivetool.example.org/"


class _Clock:
    """Stands in for the time module: sleeping moves the clock, nothing waits."""

    def __init__(self) -> None:
        self.now = 1000.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch) -> _Clock:
    fake = _Clock()
    monkeypatch.setattr(entry_point, "time", fake)
    return fake


def _bad_gateway(title: str = "502 Bad Gateway") -> HTTPError:
    page = f"<html><head><title>{title}</title></head><body>nginx</body></html>"
    return HTTPError(
        _TOOL_URL,
        502,
        "Bad Gateway",
        {"Server": "nginx/1.20.1"},
        io.BytesIO(page.encode()),
    )


def test_failure_says_how_long_the_entry_point_stayed_down(monkeypatch, clock) -> None:
    def handler():
        raise _bad_gateway()

    _patch_urlopen(monkeypatch, handler)

    with pytest.raises(InteractiveToolProxyError) as excinfo:
        verify_entry_point(_TOOL_URL, timeout=180, poll_interval=3)

    assert str(excinfo.value) == (
        "Interactive tool proxy returned HTTP 502 (still failing after 180s, 61 probes)"
    )


def test_single_failed_probe_is_reported_in_the_singular(monkeypatch, clock) -> None:
    def handler():
        raise _bad_gateway()

    _patch_urlopen(monkeypatch, handler)

    with pytest.raises(InteractiveToolProxyError, match=r"after 0s, 1 probe\)$"):
        verify_entry_point(_TOOL_URL, timeout=0)


def test_every_probe_is_logged_with_what_answered(monkeypatch, clock) -> None:
    answers = iter(
        [
            _bad_gateway(),
            _bad_gateway(),
            _FakeResponse(b"<html>PhysiCell Studio</html>"),
        ]
    )

    def handler():
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    _patch_urlopen(monkeypatch, handler)
    lines: list[str] = []

    verify_entry_point(_TOOL_URL, timeout=180, poll_interval=3, log=lines.append)

    assert lines == [
        "[entry point] probe 1 at +0.0s: HTTP 502, server: nginx/1.20.1, "
        'page: "502 Bad Gateway"',
        "[entry point] probe 2 at +3.0s: HTTP 502, server: nginx/1.20.1, "
        'page: "502 Bad Gateway"',
        "[entry point] probe 3 at +6.0s: HTTP 200, server: not given",
    ]


def test_unanswered_probe_is_logged_as_no_response(monkeypatch, clock) -> None:
    def handler():
        raise URLError("timed out")

    _patch_urlopen(monkeypatch, handler)
    lines: list[str] = []

    with pytest.raises(InteractiveToolProxyError, match="did not respond"):
        verify_entry_point(_TOOL_URL, timeout=0, log=lines.append)

    assert lines == [
        "[entry point] probe 1 at +0.0s: no response (URLError: timed out)"
    ]


def test_proxy_error_page_served_with_200_is_logged(monkeypatch, clock) -> None:
    _patch_urlopen(monkeypatch, lambda: _FakeResponse(b"Proxy target missing"))
    lines: list[str] = []

    with pytest.raises(InteractiveToolProxyError, match="proxy target missing"):
        verify_entry_point(_TOOL_URL, timeout=0, log=lines.append)

    assert lines == [
        "[entry point] probe 1 at +0.0s: HTTP 200, server: not given, "
        'page: "Proxy target missing"'
    ]


def test_entry_point_url_never_reaches_the_log_or_the_error(monkeypatch, clock) -> None:
    host = "ep1-secrettoken.interactivetool.example.org"
    answers = iter(
        [
            _bad_gateway(title=f"No route to {host}"),
            URLError(f"certificate is not valid for '{host}'"),
            _bad_gateway(title=f"Cannot reach {_TOOL_URL}"),
        ]
    )

    def handler():
        raise next(answers)

    _patch_urlopen(monkeypatch, handler)
    lines: list[str] = []

    with pytest.raises(InteractiveToolProxyError) as excinfo:
        verify_entry_point(_TOOL_URL, timeout=6, poll_interval=3, log=lines.append)

    assert len(lines) == 3
    assert "secrettoken" not in "\n".join(lines) + str(excinfo.value)
    assert 'page: "No route to <interactive-tool-url>"' in lines[0]
