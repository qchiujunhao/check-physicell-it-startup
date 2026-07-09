# PhysiCell Startup Monitor

This repository monitors whether the PhysiCell interactive tool can start on a
Galaxy server, currently defaulting to [usegalaxy.org](https://usegalaxy.org).
The monitor launches the interactive tool through the Galaxy API, waits for the
job and entry point to become available, makes one HTTP request to the entry
point to confirm the proxy is actually serving the container, and records timing
and failure artifacts.

## Monitoring Strategy

The monitor uses two layers:

1. A cheap public preflight check records the Galaxy Statuspage rollup,
   `GALAXY_BASE_URL/api/version`, and the configured PhysiCell tool metadata.
   This gives context for failures without submitting a Galaxy job.
2. A full synthetic startup check launches the interactive tool, waits for the
   Galaxy job and interactive-tool entry point, fetches the entry point over
   HTTP to confirm the proxy is not returning an error page, and then stops the
   job.

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
8. Fetch the entry point over HTTP and confirm it does not return a Galaxy
   proxy/gateway error page.
9. Write `output/<timestamp>/result.json` and failure artifacts.
10. Stop the interactive tool job so the container is not left running.

The entry point check is deliberately conservative: it fails only on a definite
negative signal (a known proxy-error page, an HTTP 502/503/504 response, or a
refused connection). Redirects, auth walls, and timeouts are treated as
reachable so that a healthy-but-slow tool is not reported as broken.

## Requirements

- Python 3.11 or newer
- A Galaxy account with access to the PhysiCell interactive tool
- A Galaxy API key, or a Galaxy username and password

## Local Setup

```bash
git clone <repo-url>
cd check-physicell-it-startup
python -m pip install -e ".[test]"
cp .env.example .env
```

Edit `.env` with Galaxy credentials before running the live monitor.

## Run The Monitor

```bash
check-physicell-startup
```

The command exits with a non-zero status only when startup fails, including
when the entry point serves a proxy/gateway error. Runs slower than
`STARTUP_EXPECTED_SECONDS` are labeled `slow` in the result but exit `0`, so
queue-driven slowness on a shared public cluster does not read as an outage.

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
| `STARTUP_EXPECTED_SECONDS` | No | `120` | Startup time threshold. Runs slower than this are labeled `slow` in the result but do not fail the monitor command. |
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
- `SLACK_WEBHOOK_URL` to post a per-run Slack message (see below).
- `MONITOR_ALERT_WEBHOOK_URL` only if you also want threshold escalation alerts.

The workflow uploads the `output/` directory as a workflow artifact and writes a
summary with status, timing, and artifact paths.

The scheduled workflow runs at minute 17 instead of exactly on the hour to avoid
the busiest GitHub Actions scheduling window. It also restores and saves
`.monitor-state/alert-state.json` through the GitHub Actions cache so alerts can
be based on consecutive runs rather than a single failure.

### Slack notifications

There are two independent Slack paths:

- **Per-run notification** (`scripts/notify_slack.py`) posts one message on
  every run — `ok`, `slow`, or `fail`. Enable it by setting the
  `SLACK_WEBHOOK_URL` secret.
- **Escalation alert** (`scripts/evaluate_alert.py`) pages only after repeated
  failures. It is off unless `MONITOR_ALERT_WEBHOOK_URL` is set. Leave it unset
  to avoid receiving two messages for the same failure.

To create the webhook: in Slack, add the **Incoming Webhooks** app (or create a
Slack app with Incoming Webhooks enabled), activate webhooks, add one for the
target channel, and copy the generated URL. Save it as the `SLACK_WEBHOOK_URL`
repository secret. Do not commit the URL. Locally, set `SLACK_WEBHOOK_URL` in
`.env` and run `python scripts/notify_slack.py` after a monitor run to test it.

Optional repository variables:

| Variable | Default | Description |
|---|---|---|
| `PHYSICELL_TOOL_VERSION_POLICY` | `latest` | Override the tool-version policy used by the scheduled monitor. |
| `ALERT_FAILURE_THRESHOLD` | `2` | Number of consecutive `fail` or `slow` results before sending a threshold alert. |
| `ALERT_IMMEDIATE_STAGES` | `authentication,tool_not_available` | Comma-separated failure stages that alert immediately on a new signature. |
| `ALERT_COUNT_STATUSES` | `fail` | Result statuses that count toward the consecutive alert threshold. Add `slow` to also page on slow startups. |
| `ALERT_REPEAT_EVERY` | `0` | Send reminder alerts every N additional alertable runs. `0` disables reminders. |

`.github/workflows/ci.yml` runs fast unit tests on pull requests and pushes to
`main`. CI does not run the live Galaxy monitor.

## Output

Each run writes a timestamped directory under `output/`:

```text
output/
  20260529T120000Z/
    result.json
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
    "entry_point_verification": 0.41
  },
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
  missing`, a bad gateway, or a service-unavailable page.
- `quota_exceeded`: Galaxy quota or rate limits blocked the run.
- `unknown`: the failure did not match a known category.

## Troubleshooting

- If the monitor fails at `authentication`, verify the API key in GitHub
  Actions secrets or the local `.env` file.
- If it fails at `tool_not_available`, confirm the installed PhysiCell tool ID on
  the target Galaxy instance and override `PHYSICELL_TOOL_ID` if needed.
- If it fails at `entry_point`, the entry point either never appeared or served
  a proxy/gateway error, which usually means the container did not come up
  behind the Galaxy proxy. Check `failure.json` and the Galaxy job logs.
  Increase `STARTUP_TIMEOUT_SECONDS` only after confirming the job was still
  starting rather than erroring.
- If histories are accumulating datasets, set `PURGE_REUSED_HISTORY=true` only
  for a history dedicated to this monitor.
