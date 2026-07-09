"""Post a per-run status message to Slack for every monitor run.

Unlike ``evaluate_alert.py`` (which only pages after repeated failures), this
sends one Slack message on every run regardless of outcome -- success, slow, or
fail -- using a Slack Incoming Webhook. It is best-effort: a webhook problem is
reported as a warning but does not fail the job.
"""

import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

load_dotenv()

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))

_EMOJI = {"ok": ":white_check_mark:", "slow": ":warning:", "fail": ":x:"}
_LABEL = {"ok": "OK", "slow": "SLOW", "fail": "FAIL"}


def find_latest_result() -> dict | None:
    for run_dir in sorted(OUTPUT_DIR.glob("*/"), reverse=True):
        result_path = run_dir / "result.json"
        if result_path.exists():
            return json.loads(result_path.read_text())
    return None


def github_run_url() -> str | None:
    explicit = os.getenv("GITHUB_RUN_URL", "").strip()
    if explicit:
        return explicit

    server = os.getenv("GITHUB_SERVER_URL", "").strip()
    repo = os.getenv("GITHUB_REPOSITORY", "").strip()
    run_id = os.getenv("GITHUB_RUN_ID", "").strip()
    if server and repo and run_id:
        return f"{server}/{repo}/actions/runs/{run_id}"
    return None


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def build_slack_payload(result: dict, run_url: str | None) -> dict:
    status = result.get("status") or ("ok" if result.get("success") else "fail")
    emoji = _EMOJI.get(status, ":x:")
    label = _LABEL.get(status, "FAIL")
    env = result.get("environment", "unknown")
    seconds = result.get("startup_seconds")
    expected = result.get("expected_seconds")
    tool_id = result.get("tool_id") or result.get("configured_tool_id")
    policy = result.get("tool_version_policy")
    stage = result.get("failure_stage")
    message = result.get("failure_message")

    lines = [
        f"{emoji} *PhysiCell Startup Monitor — {label}*",
        f"*Environment:* `{env}`",
    ]

    if seconds is not None:
        timing = f"{seconds:.1f}s"
        if expected and seconds > expected:
            timing += f" (expected < {expected}s)"
        lines.append(f"*Startup:* {timing}")

    if tool_id:
        tool_line = f"*Tool:* `{tool_id}`"
        if policy:
            tool_line += f" ({policy})"
        lines.append(tool_line)

    if status == "fail":
        if stage:
            lines.append(f"*Failure stage:* `{stage}`")
        if message:
            short = str(message)
            short = short[:300] + "..." if len(short) > 300 else short
            lines.append(f"*Error:* {short}")

    if run_url:
        lines.append(f"<{run_url}|View GitHub run>")

    text = f"PhysiCell Startup Monitor: {label}"
    if seconds is not None:
        text += f" ({seconds:.1f}s)"

    return {"text": text, "blocks": [_section("\n".join(lines))]}


def build_missing_result_payload(run_url: str | None) -> dict:
    lines = [
        ":x: *PhysiCell Startup Monitor — NO RESULT*",
        "The monitor did not produce a result file; it may have crashed before "
        "writing one.",
    ]
    if run_url:
        lines.append(f"<{run_url}|View GitHub run>")
    return {
        "text": "PhysiCell Startup Monitor: no result",
        "blocks": [_section("\n".join(lines))],
    }


def send_slack(url: str, payload: dict) -> None:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "physicell-startup-monitor/0.1",
        },
        method="POST",
    )
    with urlopen(request, timeout=20) as response:
        response.read()


def main() -> int:
    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if not webhook_url:
        print("SLACK_WEBHOOK_URL is not set; Slack notification skipped.")
        return 0

    run_url = github_run_url()
    result = find_latest_result()
    if result is None:
        payload = build_missing_result_payload(run_url)
    else:
        payload = build_slack_payload(result, run_url)

    try:
        send_slack(webhook_url, payload)
        print("Slack notification sent.")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        # Notification is auxiliary; do not fail the job on a Slack problem.
        print(f"::warning::Slack notification failed: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
