"""Verify that a running interactive tool's entry point actually serves.

The Galaxy interactive-tool proxy can register an entry point URL before (or
without) the container behind it being reachable. In that case the URL responds
with a proxy error page such as ``Proxy target missing`` or a gateway error.
This module makes a single HTTP request to the entry point and fails only on
those definite negative signals, so a healthy-but-slow tool is not reported as
broken.
"""

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_PROXY_ERROR_STRINGS = (
    "proxy target missing",
    "bad gateway",
    "service unavailable",
)

_PROXY_ERROR_STATUS = {502, 503, 504}


class InteractiveToolProxyError(RuntimeError):
    """Raised when the entry point serves a Galaxy proxy/gateway error."""


def verify_entry_point(url: str, timeout: int = 30) -> None:
    """Fetch the interactive tool entry point and check that it serves.

    Passes (returns ``None``) unless a definite proxy/gateway failure is seen:
    a known proxy-error page body, an HTTP 502/503/504 response, or a refused
    connection. Everything else -- including redirects, auth walls, and
    timeouts -- is treated as reachable so that transient slowness does not
    produce a false failure.

    Args:
        url: The entry point URL for the running interactive tool.
        timeout: Max seconds to wait for the response.

    Raises:
        InteractiveToolProxyError: The entry point served a proxy/gateway error.
    """
    request = Request(
        url,
        headers={"User-Agent": "physicell-startup-monitor/0.1"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(4096).decode("utf-8", "replace")
    except HTTPError as exc:
        if exc.code in _PROXY_ERROR_STATUS:
            raise InteractiveToolProxyError(
                f"Interactive tool proxy returned HTTP {exc.code}"
            ) from exc
        return
    except (ConnectionResetError, ConnectionRefusedError) as exc:
        raise InteractiveToolProxyError(
            "Interactive tool proxy refused the connection"
        ) from exc
    except (URLError, TimeoutError, OSError):
        # DNS blips, timeouts, and other transient network issues are not a
        # reliable signal that the tool failed to start.
        return

    lowered = body.lower()
    for marker in _PROXY_ERROR_STRINGS:
        if marker in lowered:
            raise InteractiveToolProxyError(
                f"Interactive tool proxy error: {marker}"
            )
