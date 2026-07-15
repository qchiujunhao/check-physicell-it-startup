# PhysiCell Startup Monitor

This repository monitors whether the PhysiCell interactive tool can start on a
Galaxy server, currently defaulting to [usegalaxy.org](https://usegalaxy.org).
The monitor launches the interactive tool through the Galaxy API, waits for the
job and entry point to become available, logs into Galaxy in a headless browser
and confirms the tool UI actually renders, and records timing and failure
artifacts.

## Monitoring Strategy

The monitor uses two layers:

1. A cheap public preflight check records the Galaxy Statuspage rollup,
   `GALAXY_BASE_URL/api/version`, and the configured PhysiCell tool metadata.
   This gives context for failures without submitting a Galaxy job.
2. A full synthetic startup check launches the interactive tool, waits for the
   Galaxy job and interactive-tool entry point, does a cheap unauthenticated
   HTTP gate to fail fast on an obviously down backend, then logs into Galaxy in
   a headless browser and waits until the tool UI actually renders before
   stopping the job.

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
8. HTTP gate: fetch the entry point unauthenticated and fail fast on a proxy or
   gateway error, or no response at all.
9. UI verification: log into Galaxy in a headless browser, open the entry point,
   and wait until the noVNC session paints a frame (the canvas has non-uniform
   pixels).
10. Write `output/<timestamp>/result.json`, a screenshot, and failure artifacts.
11. Stop the interactive tool job so the container is not left running.

UI verification is what makes a pass mean "genuinely usable" rather than merely
"reachable". It requires a real Galaxy session, so `GALAXY_USERNAME` and
`GALAXY_PASSWORD` must be set (an API key alone cannot create the browser
session the interactive-tool proxy needs). It produces real failures too: a
proxy/gateway error (`entry_point`), an unauthenticated bounce to the login page
(`authentication`), or a UI that never renders (`ui_verification`). Set
`REQUIRE_UI_VERIFICATION=false` to treat UI verification as diagnostic only.

> The Galaxy login markup and the tool's readiness signal can vary by version.
> Login success is confirmed via `/api/users/current` and readiness by sampling
> canvas pixels, and every run saves a screenshot and page HTML, so the first
> live run can be inspected and the readiness check tuned in
> [`helpers/ui_check.py`](helpers/ui_check.py) if a specific instance needs it.

## Requirements

- Python 3.11 or newer
- A Galaxy account with access to the PhysiCell interactive tool
- A Galaxy API key (to launch) and a Galaxy username and password (for the
  authenticated UI verification)
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

The command exits with a non-zero status when startup fails, including when the
entry point serves a proxy/gateway error or when UI verification fails while
required. Runs slower than `STARTUP_EXPECTED_SECONDS` are labeled `slow` in the
result but exit `0`, so queue-driven slowness on a shared public cluster does
not read as an outage.

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
| `GALAXY_API_KEY` | Yes* | | Galaxy API key, used to launch and manage the job. |
| `GALAXY_USERNAME` | Yes† | | Galaxy username. Used as an API-key alternative for launch, and required for authenticated UI verification. |
| `GALAXY_PASSWORD` | Yes† | | Galaxy password. Required for authenticated UI verification. |
| `PHYSICELL_TOOL_ID` | No | `toolshed.g2.bx.psu.edu/repos/rheiland/physicell_studio/interactive_tool_pcstudio/0.7` | Tool ID used as the configured version anchor. |
| `PHYSICELL_TOOL_VERSION_POLICY` | No | `latest` | `latest` launches the newest installed version reported by Galaxy metadata. `pinned` launches `PHYSICELL_TOOL_ID` exactly. |
| `PREFLIGHT_ENABLED` | No | `true` | Whether to record public statuspage, API version, and tool metadata before launch. |
| `PREFLIGHT_TIMEOUT_SECONDS` | No | `15` | Timeout for each public preflight HTTP request. |
| `GALAXY_STATUSPAGE_SUMMARY_URL` | No | `https://galaxyproject.statuspage.io/api/v2/summary.json` | Statuspage summary API used for broad Galaxy service context. |
| `STARTUP_TIMEOUT_SECONDS` | No | `600` | Maximum time allowed for job startup and entry point availability. |
| `STARTUP_EXPECTED_SECONDS` | No | `120` | Startup time threshold. Runs slower than this are labeled `slow` in the result but do not fail the monitor command. |
| `REQUIRE_UI_VERIFICATION` | No | `true` | Whether a UI verification failure should fail the monitor run. Set `false` to treat it as diagnostic only. |
| `UI_VERIFY_TIMEOUT_SECONDS` | No | `60` | Max seconds to wait for the tool UI to render a frame. |
| `GALAXY_LOGIN_TIMEOUT_SECONDS` | No | `30` | Max seconds to establish the browser login session. |
| `PURGE_REUSED_HISTORY` | No | `false` | Whether to purge datasets in an existing monitor history before launch. Disabled by default to avoid deleting data unexpectedly. |
| `HISTORY_NAME` | No | `PhysiCell Monitor` | Galaxy history name used for monitor runs. |
| `CLEANUP_MIN_AGE_MINUTES` | No | `60` | Scheduled cleanup only cancels jobs older than this, so it never kills an in-flight monitor run. |
| `OUTPUT_DIR` | No | `output` | Directory where result files and artifacts are written. |

\* Provide `GALAXY_API_KEY`, or `GALAXY_USERNAME` and `GALAXY_PASSWORD`, to
launch the tool.

† `GALAXY_USERNAME` and `GALAXY_PASSWORD` are required for authenticated UI
verification unless `REQUIRE_UI_VERIFICATION=false`.

## GitHub Actions

`.github/workflows/scheduled-monitor.yml` runs the monitor every 6 hours and on
manual dispatch. Configure these repository secrets:

- `GALAXY_BASE_URL`
- `GALAXY_API_KEY`
- `GALAXY_USERNAME` and `GALAXY_PASSWORD` for authenticated UI verification.
- `SLACK_BOT_TOKEN` and `SLACK_CHANNEL_ID` to post a per-run Slack message with
  the run screenshot (see below), or `SLACK_WEBHOOK_URL` for a text-only message.
- `MONITOR_ALERT_WEBHOOK_URL` only if you also want threshold escalation alerts.

The workflow uploads the `output/` directory as a workflow artifact and writes a
summary with status, timing, UI verification state, and artifact paths.

The scheduled workflow runs at minute 17 instead of exactly on the hour to avoid
the busiest GitHub Actions scheduling window. It also restores and saves
`.monitor-state/alert-state.json` through the GitHub Actions cache so alerts can
be based on consecutive runs rather than a single failure.

### Scheduled cleanup

Each run stops its own interactive-tool job in a `finally` block, but a hard
crash before that point can leave a running container behind or let datasets
accumulate in the monitor history. `.github/workflows/cleanup.yml` runs
`scripts/cleanup.py` daily at 03:30 UTC (and on manual dispatch) to sweep up
those leaks. It is scoped strictly to `HISTORY_NAME`, so it never touches other
histories, and it only cancels jobs older than `CLEANUP_MIN_AGE_MINUTES`
(default 60), so it cannot kill a monitor run that is still in flight. The
cleanup needs only `GALAXY_BASE_URL` and `GALAXY_API_KEY`. Run it locally with
`python scripts/cleanup.py`.

### Slack notifications

There are two independent Slack paths:

- **Per-run notification** (`scripts/notify_slack.py`) posts one message on
  every run — `ok`, `slow`, or `fail`.
- **Escalation alert** (`scripts/evaluate_alert.py`) pages only after repeated
  failures. It is off unless `MONITOR_ALERT_WEBHOOK_URL` is set. Leave it unset
  to avoid receiving two messages for the same failure.

The per-run notification has two delivery modes, preferred in this order:

- **Bot token (recommended)** — set `SLACK_BOT_TOKEN` and `SLACK_CHANNEL_ID`. It
  uploads the run screenshot (`connected.png` on success, `failure.png` on
  failure) with the status as the file comment. This is the only mode that can
  attach the image, because Incoming Webhooks cannot upload files.
- **Incoming Webhook** — set `SLACK_WEBHOOK_URL`. Text-only; no screenshot. Used
  as a fallback only when no bot token is set.

To set up the bot token: create a Slack app, add the **`chat:write`** and
**`files:write`** bot scopes, install it to the workspace, and copy the bot
token (`xoxb-…`). Invite the bot to the target channel (`/invite @yourbot`) and
copy the channel ID (channel details → bottom of the About tab). Save them as
the `SLACK_BOT_TOKEN` and `SLACK_CHANNEL_ID` repository secrets. Do not commit
them. Locally, set both in `.env` and run `python scripts/notify_slack.py` after
a monitor run to test it.

To be `@`-mentioned only when a run fails, set `SLACK_MENTION_USER_ID` to your
Slack member ID (profile → More → Copy member ID; it starts with `U`). Use a
comma- or space-separated list to mention several people. It is not secret, so
set it as a repository **variable**. Successful and slow runs are not mentioned,
and mentioned users must be members of the channel to actually be notified.

Optional repository variables:

| Variable | Default | Description |
|---|---|---|
| `PHYSICELL_TOOL_VERSION_POLICY` | `latest` | Override the tool-version policy used by the scheduled monitor. |
| `SLACK_MENTION_USER_ID` | | Slack member ID(s) (`U…`, comma/space-separated) to `@`-mention when a run fails. Empty disables mentions. |
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
    connected.png      # UI screenshot on success, when available
    failure.png        # UI screenshot on failure, when available
    page.html          # failure page HTML, when available
    ui_state.json      # failure page URL, when available
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
    "entry_point_verification": 0.41,
    "ui_verification": 12.7
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
  missing`, a bad gateway, or a service-unavailable page.
- `ui_verification`: the browser reached the tool but the UI never rendered a
  frame within `UI_VERIFY_TIMEOUT_SECONDS`.
- `quota_exceeded`: Galaxy quota or rate limits blocked the run.
- `unknown`: the failure did not match a known category.

## Troubleshooting

- If the monitor fails at `authentication`, verify `GALAXY_API_KEY` and, for UI
  verification, `GALAXY_USERNAME` / `GALAXY_PASSWORD` in GitHub Actions secrets
  or the local `.env` file. An `authentication` failure during UI verification
  means the browser login did not establish a session or the entry point bounced
  to a login page; inspect `failure.png` and `ui_state.json`.
- If it fails at `tool_not_available`, confirm the installed PhysiCell tool ID on
  the target Galaxy instance and override `PHYSICELL_TOOL_ID` if needed.
- If it fails at `entry_point`, the entry point either never appeared or served
  a proxy/gateway error, which usually means the container did not come up
  behind the Galaxy proxy. Check `failure.json` and the Galaxy job logs.
  Increase `STARTUP_TIMEOUT_SECONDS` only after confirming the job was still
  starting rather than erroring.
- If it fails at `ui_verification`, the tool was reached but did not render a
  frame in time. Inspect `failure.png` and `page.html`. If a specific instance
  serves the UI in a way the canvas check does not detect, raise
  `UI_VERIFY_TIMEOUT_SECONDS`, adjust the readiness check in
  [`helpers/ui_check.py`](helpers/ui_check.py), or set
  `REQUIRE_UI_VERIFICATION=false` to treat it as diagnostic.
- If histories are accumulating datasets, set `PURGE_REUSED_HISTORY=true` only
  for a history dedicated to this monitor.
