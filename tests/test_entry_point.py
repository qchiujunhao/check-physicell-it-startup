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
