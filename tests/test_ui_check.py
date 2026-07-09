from helpers.entry_point import InteractiveToolProxyError
from helpers.results import determine_failure_stage
from helpers.ui_check import (
    GalaxyLoginError,
    ToolUINotReady,
    _is_authenticated_user,
    _looks_like_login_url,
    _proxy_error_from_text,
)


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
