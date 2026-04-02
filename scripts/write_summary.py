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

    success = result.get("success", False)
    status = "Pass" if success else "FAIL"
    emoji = "white_check_mark" if success else "x"
    seconds = result.get("startup_seconds")
    stage = result.get("failure_stage")
    message = result.get("failure_message")
    env = result.get("environment", "unknown")
    timestamp = result.get("timestamp", "unknown")

    print(f"## :{emoji}: PhysiCell Startup Monitor — {status}")
    print("")
    print(f"| Field | Value |")
    print(f"|---|---|")
    print(f"| **Environment** | `{env}` |")
    print(f"| **Timestamp** | {timestamp} |")
    print(f"| **Status** | {'Passed' if success else 'Failed'} |")
    if seconds is not None:
        print(f"| **Startup Time** | {seconds:.1f}s |")
    if stage:
        print(f"| **Failure Stage** | `{stage}` |")
    if message:
        # Truncate long messages for readability
        short = message[:300] + "..." if len(message) > 300 else message
        # Escape pipe characters for markdown table
        short = short.replace("|", "\\|").replace("\n", " ")
        print(f"| **Error** | {short} |")


if __name__ == "__main__":
    main()
