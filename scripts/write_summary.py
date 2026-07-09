"""Generate a GitHub Actions job summary from the latest run result."""

import json
from pathlib import Path

OUTPUT_DIR = Path("output")


def find_latest_result() -> dict | None:
    """Find the most recent result.json in output/."""
    results = sorted(OUTPUT_DIR.glob("*/result.json"), reverse=True)
    if not results:
        return None
    return json.loads(results[0].read_text())


def find_screenshot(success: bool) -> Path | None:
    """Find the most recent screenshot for the latest run."""
    dirs = sorted(OUTPUT_DIR.glob("*/"), reverse=True)
    for d in dirs:
        names = ["connected.png"] if success else ["failure.png"]
        for name in names:
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
    timings = result.get("timings", {})
    ui_verified = result.get("ui_verified")
    ui_required = result.get("ui_required")
    tool_id = result.get("tool_id")
    tool_policy = result.get("tool_version_policy")
    preflight = result.get("preflight", {})
    screenshot = find_screenshot(status != "fail")

    emoji_map = {"ok": "white_check_mark", "slow": "warning", "fail": "x"}
    label_map = {"ok": "OK", "slow": "SLOW", "fail": "FAIL"}
    emoji = emoji_map.get(status, "x")
    label = label_map.get(status, "FAIL")

    print(f"## :{emoji}: PhysiCell Startup Monitor - {label}")
    print("")
    print("| Field | Value |")
    print("|---|---|")
    print(f"| **Environment** | `{env}` |")
    if tool_id:
        tool_display = f"`{tool_id}`"
        if tool_policy:
            tool_display += f" ({tool_policy})"
        print(f"| **Tool** | {tool_display} |")
    print(f"| **Timestamp** | {timestamp} |")
    print(f"| **Status** | {label} |")
    if preflight:
        print(f"| **Preflight** | {preflight.get('status', 'unknown')} |")
        galaxy_version = preflight.get("galaxy_version", {})
        version_major = galaxy_version.get("version_major")
        version_minor = galaxy_version.get("version_minor")
        if version_major or version_minor:
            print(f"| **Galaxy Version** | `{version_major}.{version_minor}` |")
        statuspage = preflight.get("statuspage", {})
        if statuspage.get("description"):
            description = str(statuspage["description"]).replace("|", "\\|")
            print(f"| **Galaxy Statuspage** | {description} |")
    if seconds is not None:
        time_display = f"{seconds:.1f}s"
        if expected and seconds > expected:
            time_display += f" (expected < {expected}s)"
        print(f"| **Startup Time** | {time_display} |")
    if ui_verified is not None:
        ui_display = "verified" if ui_verified else "not verified"
        if ui_required is not None:
            ui_display += f" ({'required' if ui_required else 'optional'})"
        print(f"| **UI Verification** | {ui_display} |")
    if screenshot:
        print(f"| **Screenshot Artifact** | `{screenshot}` |")
    if stage:
        print(f"| **Failure Stage** | `{stage}` |")
    if message:
        short = message[:300] + "..." if len(message) > 300 else message
        short = short.replace("|", "\\|").replace("\n", " ")
        print(f"| **Error** | {short} |")

    if timings:
        print("")
        print("### Timings")
        print("")
        print("| Stage | Seconds |")
        print("|---|---:|")
        for name, value in timings.items():
            label = name.replace("_", " ").title()
            print(f"| {label} | {value:.1f} |")


if __name__ == "__main__":
    main()
