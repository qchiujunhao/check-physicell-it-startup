"""Verify that a running interactive tool's entry point actually serves.

The Galaxy interactive-tool proxy can register an entry point URL before (or
without) the container behind it being reachable. In that case the URL responds
with a proxy error page such as ``Proxy target missing``, a gateway error, or no
response at all. This module probes the entry point and fails only on a
persistent negative signal, retrying within a window so a tool that is still
coming up behind the proxy is not reported as broken.

Every probe is logged with what came back -- status code, ``Server`` header and
the error page's title -- so a failed run shows how long the entry point was
unreachable and which server was answering.

The probe is unauthenticated, so it can detect "the proxy has no working
backend" but cannot positively confirm the tool UI rendered. A pass therefore
means "not visibly broken", not "verified working".
"""

import re
import time
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

_PROXY_ERROR_STRINGS = (
    "proxy target missing",
    "bad gateway",
    "service unavailable",
)

_PROXY_ERROR_STATUS = {502, 503, 504}

_BODY_BYTES = 4096
_LOGGED_TEXT_CHARS = 80


class InteractiveToolProxyError(RuntimeError):
    """Raised when the entry point does not serve a working backend."""


def _printable(text: object, url: str) -> str:
    """Reduce remote text to one short line that is safe to put in the run log.

    The entry point URL carries the session's token, and the log of a public
    repository is public, so the URL and its parts are removed.
    """
    line = " ".join(str(text).split())
    parts = urlsplit(url)
    for secret in sorted(
        {url, parts.netloc, parts.hostname or "", parts.path.strip("/")},
        key=len,
        reverse=True,
    ):
        if len(secret) >= 4:
            line = line.replace(secret, "<interactive-tool-url>")
    return line[:_LOGGED_TEXT_CHARS]


def _describe(status: object, headers: object, body: str, url: str) -> str:
    """Say what answered: status code, ``Server`` header, and the page's title."""
    server = headers.get("Server") if hasattr(headers, "get") else None
    detail = (
        f"HTTP {status}, server: {_printable(server, url) if server else 'not given'}"
    )
    title = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
    text = _printable(title.group(1) if title else re.sub(r"<[^>]+>", " ", body), url)
    return f'{detail}, page: "{text}"' if text else detail


def _probe(url: str, request_timeout: int) -> tuple[str | None, str]:
    """Make one request. Return ``(failure, detail)``.

    ``failure`` is ``None`` if the response is acceptable, else a failure
    message. ``detail`` describes what came back, for the run log.

    A response is acceptable when the proxy answers with anything other than a
    known proxy-error page or a 502/503/504. Auth walls and other 4xx responses
    are acceptable because an unauthenticated probe cannot conclude from them
    that the backend is down. A missing response (timeout or connection error)
    and a proxy/gateway error are negative signals.
    """
    request = Request(
        url,
        headers={"User-Agent": "physicell-startup-monitor/0.1"},
    )
    try:
        with urlopen(request, timeout=request_timeout) as response:
            body = response.read(_BODY_BYTES).decode("utf-8", "replace")
            status = getattr(response, "status", 200)
            headers = getattr(response, "headers", None)
    except HTTPError as exc:
        try:
            error_body = exc.read(_BODY_BYTES).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - the body is only for the log
            error_body = ""
        detail = _describe(exc.code, exc.headers, error_body, url)
        if exc.code in _PROXY_ERROR_STATUS:
            return f"Interactive tool proxy returned HTTP {exc.code}", detail
        return None, detail
    except (URLError, TimeoutError, OSError) as exc:
        reason = _printable(getattr(exc, "reason", None) or exc, url)
        return (
            "Interactive tool entry point did not respond",
            f"no response ({type(exc).__name__}: {reason})",
        )

    lowered = body.lower()
    for marker in _PROXY_ERROR_STRINGS:
        if marker in lowered:
            return (
                f"Interactive tool proxy error: {marker}",
                _describe(status, headers, body, url),
            )
    return None, _describe(status, headers, "", url)


def verify_entry_point(
    url: str,
    timeout: int = 30,
    poll_interval: int = 3,
    request_timeout: int = 15,
    log: Callable[[str], None] | None = None,
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
        log: Receives one line per probe. The URL is never part of a line.

    Raises:
        InteractiveToolProxyError: The entry point never served a working
            backend within ``timeout`` seconds.
    """
    start = time.time()
    deadline = start + timeout
    probes = 0
    while True:
        failure, detail = _probe(url, request_timeout)
        probes += 1
        elapsed = time.time() - start
        if log is not None:
            log(f"[entry point] probe {probes} at +{elapsed:.1f}s: {detail}")
        if failure is None:
            return
        if time.time() >= deadline:
            count = f"{probes} probe{'' if probes == 1 else 's'}"
            raise InteractiveToolProxyError(
                f"{failure} (still failing after {elapsed:.0f}s, {count})"
            )
        time.sleep(poll_interval)
