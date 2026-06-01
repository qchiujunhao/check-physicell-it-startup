# PhysiCell Startup Monitor

This repository monitors whether the PhysiCell interactive tool can start on a
Galaxy server, currently defaulting to [usegalaxy.org](https://usegalaxy.org).
The monitor launches the interactive tool through the Galaxy API, waits for the
job and entry point to become available, opens the session in Chromium through
Playwright, and records timing and failure artifacts.

## Monitoring Strategy

The monitor uses two layers:

1. A cheap public preflight check records the Galaxy Statuspage rollup,
   `GALAXY_BASE_URL/api/version`, and the configured PhysiCell tool metadata.
   This gives context for failures without submitting a Galaxy job.
2. A full synthetic startup check launches the interactive tool, waits for the
   Galaxy job and interactive-tool entry point, verifies that the browser can
   load the session, and then stops the job.

By default, the monitor uses the latest installed PhysiCell Studio version
reported by Galaxy's tool metadata. Set `PHYSICELL_TOOL_VERSION_POLICY=pinned`
to launch exactly the version in `PHYSICELL_TOOL_ID`.

## What The Monitor Checks

1. Record public preflight status and resolve the tool version to launch.
2. Connect to Galaxy with a configured API key or username/password.
3. Find or create the configured monitor history.
4. Verify the selected PhysiCell tool ID is available.
5. Launch the interactive tool.
6. Wait for the Galaxy job to reach `running`.
7. Wait for the interactive tool entry point URL.
8. Open the entry point in Chromium and verify that the UI loaded.
9. Write `output/<timestamp>/result.json` and screenshot artifacts.
10. Stop the interactive tool job so the container is not left running.

By default, UI verification is required. Set `REQUIRE_UI_VERIFICATION=false` if
the environment should treat browser verification as diagnostic only.

## Requirements

- Python 3.11 or newer
- A Galaxy account with access to the PhysiCell interactive tool
- A Galaxy API key, or a Galaxy username and password
- Chromium installed through Playwright

## Local Setup

```bash
git clone <repo-url>
cd check-physicell-it-startup
python -m pip install -e ".[test]"
playwright install chromium
cp .env.example .env
```

Edit `.env` with Galaxy credentials before running the live monitor.

## Run The Monitor

```bash
check-physicell-startup
```

The command exits with a non-zero status when startup fails, UI verification
fails while required, or startup is slower than `STARTUP_EXPECTED_SECONDS`.

## Run Tests

Fast unit tests do not contact Galaxy:

```bash
pytest
```

The live end-to-end pytest check is marked as `integration` and is excluded from
default test runs:

```bash
pytest -m integration tests/test_physicell_startup.py
```

For routine development, prefer `pytest`. Use the monitor command for scheduled
production checks.

## Environment Variables

| Variable | Required | Default | Description |
|---|---:|---|---|
| `GALAXY_BASE_URL` | No | `https://usegalaxy.org` | Galaxy server URL. |
| `GALAXY_API_KEY` | Yes* | | Galaxy API key. |
| `GALAXY_USERNAME` | Yes* | | Galaxy username, used only when no API key is set. |
| `GALAXY_PASSWORD` | Yes* | | Galaxy password, used only when no API key is set. |
| `PHYSICELL_TOOL_ID` | No | `toolshed.g2.bx.psu.edu/repos/rheiland/physicell_studio/interactive_tool_pcstudio/0.7` | Tool ID used as the configured version anchor. |
| `PHYSICELL_TOOL_VERSION_POLICY` | No | `latest` | `latest` launches the newest installed version reported by Galaxy metadata. `pinned` launches `PHYSICELL_TOOL_ID` exactly. |
| `PREFLIGHT_ENABLED` | No | `true` | Whether to record public statuspage, API version, and tool metadata before launch. |
| `PREFLIGHT_TIMEOUT_SECONDS` | No | `15` | Timeout for each public preflight HTTP request. |
| `GALAXY_STATUSPAGE_SUMMARY_URL` | No | `https://galaxyproject.statuspage.io/api/v2/summary.json` | Statuspage summary API used for broad Galaxy service context. |
| `STARTUP_TIMEOUT_SECONDS` | No | `600` | Maximum time allowed for job startup and entry point availability. |
| `STARTUP_EXPECTED_SECONDS` | No | `120` | Startup time threshold. Runs slower than this are reported as `slow` and fail the monitor command. |
| `REQUIRE_UI_VERIFICATION` | No | `true` | Whether browser UI verification failure should fail the monitor run. |
| `PURGE_REUSED_HISTORY` | No | `false` | Whether to purge datasets in an existing monitor history before launch. Disabled by default to avoid deleting data unexpectedly. |
| `HISTORY_NAME` | No | `PhysiCell Monitor` | Galaxy history name used for monitor runs. |
| `OUTPUT_DIR` | No | `output` | Directory where result files and artifacts are written. |

\* Provide either `GALAXY_API_KEY` or both `GALAXY_USERNAME` and
`GALAXY_PASSWORD`.

## GitHub Actions

`.github/workflows/scheduled-monitor.yml` runs the monitor every 6 hours and on
manual dispatch. Configure these repository secrets:

- `GALAXY_BASE_URL`
- `GALAXY_API_KEY`
- `MONITOR_ALERT_WEBHOOK_URL` if alerts should be sent to a webhook.

The workflow uploads the `output/` directory as a workflow artifact and writes a
summary with status, timing, UI verification state, and artifact paths.

The scheduled workflow runs at minute 17 instead of exactly on the hour to avoid
the busiest GitHub Actions scheduling window. It also restores and saves
`.monitor-state/alert-state.json` through the GitHub Actions cache so alerts can
be based on consecutive runs rather than a single failure.

Optional repository variables:

| Variable | Default | Description |
|---|---|---|
| `PHYSICELL_TOOL_VERSION_POLICY` | `latest` | Override the tool-version policy used by the scheduled monitor. |
| `ALERT_FAILURE_THRESHOLD` | `2` | Number of consecutive `fail` or `slow` results before sending a threshold alert. |
| `ALERT_IMMEDIATE_STAGES` | `authentication,tool_not_available` | Comma-separated failure stages that alert immediately on a new signature. |
| `ALERT_COUNT_STATUSES` | `fail,slow` | Result statuses that count toward the consecutive alert threshold. |
| `ALERT_REPEAT_EVERY` | `0` | Send reminder alerts every N additional alertable runs. `0` disables reminders. |

`.github/workflows/ci.yml` runs fast unit tests on pull requests and pushes to
`main`. CI does not run the live Galaxy monitor.

## Output

Each run writes a timestamped directory under `output/`:

```text
output/
  20260529T120000Z/
    result.json
    connected.png      # success screenshot, when available
    failure.png        # failure screenshot, when available
    page.html          # failure page HTML, when available
    failure.json       # failure stage metadata, when available
```

Example `result.json`:

```json
{
  "timestamp": "2026-05-29T12:00:00+00:00",
  "environment": "https://usegalaxy.org",
  "status": "ok",
  "success": true,
  "configured_tool_id": "toolshed.g2.bx.psu.edu/repos/rheiland/physicell_studio/interactive_tool_pcstudio/0.7",
  "tool_id": "toolshed.g2.bx.psu.edu/repos/rheiland/physicell_studio/interactive_tool_pcstudio/0.11",
  "tool_version_policy": "latest",
  "startup_seconds": 91.42,
  "expected_seconds": 120,
  "failure_stage": null,
  "failure_message": null,
  "timings": {
    "galaxy_connection": 0.54,
    "history_setup": 1.21,
    "tool_launch_api": 2.33,
    "job_running": 74.15,
    "entry_point_available": 9.62,
    "browser_verification": 3.57
  },
  "ui_verified": true,
  "ui_required": true,
  "preflight": {
    "status": "ok",
    "galaxy_version": {
      "version_major": "26.0",
      "version_minor": "1.dev1"
    }
  }
}
```

## Failure Stages

- `galaxy_unreachable`: Galaxy could not be reached or resolved.
- `authentication`: credentials are missing, invalid, or unauthorized.
- `tool_not_available`: the configured PhysiCell tool ID is not installed or enabled.
- `history`: creating or reusing the Galaxy history failed.
- `job_timeout`: the interactive tool job did not reach `running` in time.
- `job_error`: the Galaxy job entered a terminal error state.
- `entry_point`: the interactive tool entry point did not become available or
  the Galaxy interactive-tool proxy returned an error such as `Proxy target
  missing`.
- `ui_verification`: Chromium could not verify a loaded noVNC or tool UI.
- `quota_exceeded`: Galaxy quota or rate limits blocked the run.
- `unknown`: the failure did not match a known category.

## Troubleshooting

- If the monitor fails at `authentication`, verify the API key in GitHub
  Actions secrets or the local `.env` file.
- If it fails at `tool_not_available`, confirm the installed PhysiCell tool ID on
  the target Galaxy instance and override `PHYSICELL_TOOL_ID` if needed.
- If it fails at `entry_point`, the job may be running before the interactive
  endpoint is ready. Increase `STARTUP_TIMEOUT_SECONDS` only after checking
  Galaxy job logs and artifacts.
- If it fails at `ui_verification`, inspect `failure.png` and `page.html`.
  If cross-origin or noVNC behavior prevents browser inspection but the endpoint
  is otherwise acceptable, set `REQUIRE_UI_VERIFICATION=false`.
- If histories are accumulating datasets, set `PURGE_REUSED_HISTORY=true` only
  for a history dedicated to this monitor.
