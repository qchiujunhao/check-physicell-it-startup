"""Verify that a running interactive tool's entry point actually serves.

The Galaxy interactive-tool proxy can register an entry point URL before (or
without) the container behind it being reachable. In that case the URL responds
with a proxy error page such as ``Proxy target missing``, a gateway error, or no
response at all. This module probes the entry point and fails only on a
persistent negative signal, retrying within a window so a one-off blip right
after startup does not flip a healthy tool to failed.

The probe is unauthenticated, so it can detect "the proxy has no working
backend" but cannot positively confirm the tool UI rendered. A pass therefore
means "not visibly broken", not "verified working".
"""

import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_PROXY_ERROR_STRINGS = (
    "proxy target missing",
    "bad gateway",
    "service unavailable",
)

_PROXY_ERROR_STATUS = {502, 503, 504}


class InteractiveToolProxyError(RuntimeError):
    """Raised when the entry point does not serve a working backend."""


def _probe(url: str, request_timeout: int) -> str | None:
    """Make one request. Return ``None`` if acceptable, else a failure message.

    A response is acceptable (``None``) when the proxy answers with anything
    other than a known proxy-error page or a 502/503/504. Auth walls and other
    4xx responses are acceptable because an unauthenticated probe cannot
    conclude from them that the backend is down. A missing response (timeout or
    connection error) and a proxy/gateway error are negative signals.
    """
    request = Request(
        url,
        headers={"User-Agent": "physicell-startup-monitor/0.1"},
    )
    try:
        with urlopen(request, timeout=request_timeout) as response:
            body = response.read(4096).decode("utf-8", "replace")
    except HTTPError as exc:
        if exc.code in _PROXY_ERROR_STATUS:
            return f"Interactive tool proxy returned HTTP {exc.code}"
        return None
    except (URLError, TimeoutError, OSError):
        return "Interactive tool entry point did not respond"

    lowered = body.lower()
    for marker in _PROXY_ERROR_STRINGS:
        if marker in lowered:
            return f"Interactive tool proxy error: {marker}"
    return None


def verify_entry_point(
    url: str,
    timeout: int = 30,
    poll_interval: int = 3,
    request_timeout: int = 15,
) -> None:
    """Probe the interactive tool entry point until it serves or the window ends.

    Passes (returns ``None``) as soon as the proxy returns an acceptable
    response. Fails only if a negative signal -- a proxy/gateway error or no
    response at all -- persists to the deadline.

    Args:
        url: The entry point URL for the running interactive tool.
        timeout: Total seconds to keep retrying before failing.
        poll_interval: Seconds to wait between attempts.
        request_timeout: Per-request timeout in seconds.

    Raises:
        InteractiveToolProxyError: The entry point never served a working
            backend within ``timeout`` seconds.
    """
    deadline = time.time() + timeout
    while True:
        outcome = _probe(url, request_timeout)
        if outcome is None:
            return
        if time.time() >= deadline:
            raise InteractiveToolProxyError(outcome)
        time.sleep(poll_interval)
