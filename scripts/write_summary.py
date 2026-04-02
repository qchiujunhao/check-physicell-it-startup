"""Generate a GitHub Actions job summary from the latest run result."""

import json
import sys
from pathlib import Path

OUTPUT_DIR = Path("output")


def find_latest_result() -> dict | None:
    """Find the most recent result.json in output/."""
    results = sorted(OUTPUT_DIR.glob("*/result.json"), reverse=True)
    if not results:
        return None
    return json.loads(results[0].read_text())


def find_screenshot(success: bool) -> Path | None:
    """Find the most recent screenshot."""
    dirs = sorted(OUTPUT_DIR.glob("*/"), reverse=True)
    for d in dirs:
        name = "connected.png" if success else "failure.png"
        path = d / name
        if path.exists():
            return path
    return None


def main() -> None:
    result = find_latest_result()
    if not result:
        print("## PhysiCell Startup Monitor")
        print("")
        print("> No result file found.")
        return

    status = result.get("status", "fail" if not result.get("success") else "ok")
    seconds = result.get("startup_seconds")
    expected = result.get("expected_seconds")
    stage = result.get("failure_stage")
    message = result.get("failure_message")
    env = result.get("environment", "unknown")
    timestamp = result.get("timestamp", "unknown")

    emoji_map = {"ok": "white_check_mark", "slow": "warning", "fail": "x"}
    label_map = {"ok": "OK", "slow": "SLOW", "fail": "FAIL"}
    emoji = emoji_map.get(status, "x")
    label = label_map.get(status, "FAIL")

    print(f"## :{emoji}: PhysiCell Startup Monitor — {label}")
    print("")
    print(f"| Field | Value |")
    print(f"|---|---|")
    print(f"| **Environment** | `{env}` |")
    print(f"| **Timestamp** | {timestamp} |")
    print(f"| **Status** | {label} |")
    if seconds is not None:
        time_display = f"{seconds:.1f}s"
        if expected and seconds > expected:
            time_display += f" (expected < {expected}s)"
        print(f"| **Startup Time** | {time_display} |")
    if stage:
        print(f"| **Failure Stage** | `{stage}` |")
    if message:
        short = message[:300] + "..." if len(message) > 300 else message
        short = short.replace("|", "\\|").replace("\n", " ")
        print(f"| **Error** | {short} |")


if __name__ == "__main__":
    main()
