"""Post a per-run status message to Slack for every monitor run.

Unlike ``evaluate_alert.py`` (which only pages after repeated failures), this
sends one Slack message on every run regardless of outcome -- success, slow, or
fail. It is best-effort: a Slack problem is reported as a warning but does not
fail the job.

Two delivery modes, preferred in this order:

* Bot token (``SLACK_BOT_TOKEN`` + ``SLACK_CHANNEL_ID``): uploads the run
  screenshot (``connected.png`` on success, ``failure.png`` on failure) with the
  status text as the file comment. This is the only mode that can attach the
  image, since Incoming Webhooks cannot upload files.
* Incoming Webhook (``SLACK_WEBHOOK_URL``): posts the status text only.
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


def find_latest_run() -> tuple[Path, dict] | None:
    for run_dir in sorted(OUTPUT_DIR.glob("*/"), reverse=True):
        result_path = run_dir / "result.json"
        if result_path.exists():
            return run_dir, json.loads(result_path.read_text())
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


def screenshot_for(run_dir: Path, result: dict) -> Path | None:
    name = "failure.png" if result.get("status") == "fail" else "connected.png"
    path = run_dir / name
    return path if path.exists() else None


def _summary_lines(result: dict, run_url: str | None) -> list[str]:
    status = result.get("status") or ("ok" if result.get("success") else "fail")
    emoji = _EMOJI.get(status, ":x:")
    label = _LABEL.get(status, "FAIL")
    seconds = result.get("startup_seconds")
    expected = result.get("expected_seconds")
    tool_id = result.get("tool_id") or result.get("configured_tool_id")
    policy = result.get("tool_version_policy")

    lines = [
        f"{emoji} *PhysiCell Startup Monitor — {label}*",
        f"*Environment:* `{result.get('environment', 'unknown')}`",
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
        if result.get("failure_stage"):
            lines.append(f"*Failure stage:* `{result['failure_stage']}`")
        message = result.get("failure_message")
        if message:
            short = str(message)
            short = short[:300] + "..." if len(short) > 300 else short
            lines.append(f"*Error:* {short}")

    if run_url:
        lines.append(f"<{run_url}|View GitHub run>")

    return lines


def _failure_mention() -> str:
    """Slack mentions to prepend on failures, e.g. ``<@U123> <@U456>``.

    Set ``SLACK_MENTION_USER_ID`` to one or more member IDs (comma- or
    space-separated) to be pinged when a run fails.
    """
    raw = os.getenv("SLACK_MENTION_USER_ID", "")
    ids = [uid.strip() for uid in raw.replace(",", " ").split() if uid.strip()]
    if not ids:
        return ""
    return " ".join(f"<@{uid}>" for uid in ids) + "\n"


def _is_failure(result: dict) -> bool:
    status = result.get("status") or ("ok" if result.get("success") else "fail")
    return status == "fail"


def summary_text(result: dict, run_url: str | None) -> str:
    prefix = _failure_mention() if _is_failure(result) else ""
    return prefix + "\n".join(_summary_lines(result, run_url))


def missing_result_text(run_url: str | None) -> str:
    lines = [
        ":x: *PhysiCell Startup Monitor — NO RESULT*",
        "The monitor did not produce a result file; it may have crashed before "
        "writing one.",
    ]
    if run_url:
        lines.append(f"<{run_url}|View GitHub run>")
    return _failure_mention() + "\n".join(lines)


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def build_slack_payload(result: dict, run_url: str | None) -> dict:
    status = result.get("status") or ("ok" if result.get("success") else "fail")
    label = _LABEL.get(status, "FAIL")
    text = f"PhysiCell Startup Monitor: {label}"
    seconds = result.get("startup_seconds")
    if seconds is not None:
        text += f" ({seconds:.1f}s)"
    return {"text": text, "blocks": [_section(summary_text(result, run_url))]}


def build_missing_result_payload(run_url: str | None) -> dict:
    return {
        "text": "PhysiCell Startup Monitor: no result",
        "blocks": [_section(missing_result_text(run_url))],
    }


def send_via_bot(
    token: str,
    channel: str,
    run: tuple[Path, dict] | None,
    run_url: str | None,
) -> None:
    from slack_sdk import WebClient

    client = WebClient(token=token)
    if run is None:
        client.chat_postMessage(channel=channel, text=missing_result_text(run_url))
        return

    run_dir, result = run
    comment = summary_text(result, run_url)
    screenshot = screenshot_for(run_dir, result)
    if screenshot is not None:
        client.files_upload_v2(
            channel=channel,
            file=str(screenshot),
            title=screenshot.name,
            initial_comment=comment,
        )
    else:
        client.chat_postMessage(channel=channel, text=comment)


def send_via_webhook(url: str, payload: dict) -> None:
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
    run = find_latest_run()
    run_url = github_run_url()

    bot_token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    channel = os.getenv("SLACK_CHANNEL_ID", "").strip()
    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "").strip()

    if bot_token and channel:
        try:
            send_via_bot(bot_token, channel, run, run_url)
            print("Slack notification sent (bot upload).")
        except Exception as exc:
            print(f"::warning::Slack bot notification failed: {exc}")
        return 0

    if webhook_url:
        if run is None:
            payload = build_missing_result_payload(run_url)
        else:
            payload = build_slack_payload(run[1], run_url)
        try:
            send_via_webhook(webhook_url, payload)
            print("Slack notification sent (webhook).")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            print(f"::warning::Slack notification failed: {exc}")
        return 0

    print("No Slack destination configured; notification skipped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
