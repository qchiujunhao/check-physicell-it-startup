"""Evaluate whether the latest monitor result should send an alert."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))
STATE_FILE = Path(
    os.getenv("MONITOR_ALERT_STATE_FILE", "output/monitor-alert-state.json")
)


def env_int(name: str, default: int, minimum: int = 0) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    parsed = int(value)
    if parsed < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return parsed


def env_csv(name: str, default: str) -> set[str]:
    value = os.getenv(name, default)
    return {item.strip() for item in value.split(",") if item.strip()}


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def find_latest_result() -> tuple[Path, dict] | None:
    dirs = sorted(OUTPUT_DIR.glob("*/"), reverse=True)
    for run_dir in dirs:
        result_path = run_dir / "result.json"
        if result_path.exists():
            return result_path, json.loads(result_path.read_text())
    return None


def failure_signature(result: dict) -> str:
    message = str(result.get("failure_message") or "")
    parts = [
        str(result.get("status") or ""),
        str(result.get("failure_stage") or ""),
        str(result.get("tool_id") or ""),
        message[:300],
    ]
    return "|".join(parts)


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


def evaluate_alert(
    result: dict,
    previous_state: dict,
    result_path: Path,
    failure_threshold: int,
    immediate_stages: set[str],
    count_statuses: set[str],
    repeat_every: int,
) -> tuple[dict, dict]:
    status = result.get("status", "fail")
    stage = result.get("failure_stage")
    timestamp = result.get("timestamp") or datetime.now(UTC).isoformat()
    alertable = status in count_statuses
    previous_count = int(previous_state.get("consecutive_alertable", 0))
    consecutive = previous_count + 1 if alertable else 0

    if alertable:
        incident_started_at = previous_state.get("incident_started_at") or timestamp
    else:
        incident_started_at = None

    signature = failure_signature(result)
    hard_failure = status == "fail" and stage in immediate_stages
    should_alert = False
    reason = None

    if hard_failure and previous_state.get("last_alert_signature") != signature:
        should_alert = True
        reason = "immediate_stage"
    elif alertable and consecutive >= failure_threshold:
        already_alerted = (
            previous_state.get("last_alert_incident_started_at")
            == incident_started_at
        )
        if not already_alerted:
            should_alert = True
            reason = "threshold"
        elif repeat_every and consecutive > failure_threshold:
            if consecutive % repeat_every == 0:
                should_alert = True
                reason = "repeat"

    new_state = {
        "consecutive_alertable": consecutive,
        "incident_started_at": incident_started_at,
        "last_status": status,
        "last_failure_stage": stage,
        "last_result_timestamp": timestamp,
        "last_result_path": str(result_path),
    }

    if not alertable:
        new_state["last_alert_signature"] = None
        new_state["last_alert_incident_started_at"] = None
    else:
        new_state["last_alert_signature"] = previous_state.get(
            "last_alert_signature"
        )
        new_state["last_alert_incident_started_at"] = previous_state.get(
            "last_alert_incident_started_at"
        )

    if should_alert:
        new_state["last_alerted_at"] = datetime.now(UTC).isoformat()
        new_state["last_alert_reason"] = reason
        new_state["last_alert_signature"] = signature
        new_state["last_alert_incident_started_at"] = incident_started_at
        new_state["last_alerted_consecutive"] = consecutive
    else:
        for key in (
            "last_alerted_at",
            "last_alert_reason",
            "last_alerted_consecutive",
        ):
            if key in previous_state:
                new_state[key] = previous_state[key]

    decision = {
        "should_alert": should_alert,
        "reason": reason,
        "status": status,
        "failure_stage": stage,
        "consecutive_alertable": consecutive,
        "failure_threshold": failure_threshold,
        "result_path": str(result_path),
    }
    return new_state, decision


def build_payload(result: dict, decision: dict) -> dict:
    run_url = github_run_url()
    status = decision["status"]
    stage = decision.get("failure_stage") or "none"
    consecutive = decision["consecutive_alertable"]
    message = result.get("failure_message") or "No failure message recorded."
    startup = result.get("startup_seconds")
    tool_id = result.get("tool_id") or result.get("configured_tool_id")

    text = (
        f"PhysiCell monitor alert: status={status}, stage={stage}, "
        f"consecutive={consecutive}"
    )
    if run_url:
        text += f", run={run_url}"

    return {
        "text": text,
        "status": status,
        "failure_stage": stage,
        "failure_message": str(message)[:1000],
        "startup_seconds": startup,
        "tool_id": tool_id,
        "consecutive_alertable": consecutive,
        "run_url": run_url,
        "result_path": decision["result_path"],
        "reason": decision["reason"],
    }


def send_webhook(url: str, payload: dict) -> None:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "physicell-startup-monitor/0.1",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            response.read()
    except HTTPError as exc:
        raise RuntimeError(f"Alert webhook failed with HTTP {exc.code}") from exc
    except (OSError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Alert webhook failed: {exc}") from exc


def main() -> int:
    latest = find_latest_result()
    if latest is None:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        print("No monitor result found; alert evaluation skipped.")
        return 0

    result_path, result = latest
    previous_state = load_json(STATE_FILE, {})
    failure_threshold = env_int("ALERT_FAILURE_THRESHOLD", 2, minimum=1)
    immediate_stages = env_csv(
        "ALERT_IMMEDIATE_STAGES",
        "authentication,tool_not_available",
    )
    count_statuses = env_csv("ALERT_COUNT_STATUSES", "fail,slow")
    repeat_every = env_int("ALERT_REPEAT_EVERY", 0, minimum=0)

    new_state, decision = evaluate_alert(
        result,
        previous_state,
        result_path,
        failure_threshold,
        immediate_stages,
        count_statuses,
        repeat_every,
    )

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(new_state, indent=2))

    print("Monitor alert evaluation")
    print(f"status={decision['status']}")
    print(f"failure_stage={decision.get('failure_stage') or 'none'}")
    print(f"consecutive_alertable={decision['consecutive_alertable']}")
    print(f"failure_threshold={failure_threshold}")
    print(f"should_alert={str(decision['should_alert']).lower()}")
    if decision["reason"]:
        print(f"reason={decision['reason']}")
    print(f"state_file={STATE_FILE}")

    if decision["should_alert"]:
        webhook_url = os.getenv("MONITOR_ALERT_WEBHOOK_URL", "").strip()
        payload = build_payload(result, decision)
        if webhook_url:
            send_webhook(webhook_url, payload)
            print("Alert webhook sent.")
        else:
            print("MONITOR_ALERT_WEBHOOK_URL is not set; alert was not sent.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
