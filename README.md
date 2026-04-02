# PhysiCell Startup Monitor

Monitors whether the PhysiCell interactive tool can successfully launch on [usegalaxy.org](https://usegalaxy.org). Measures startup time and captures artifacts on failure.

## How it works

1. **BioBlend** connects to Galaxy, creates/reuses a clean history, and launches the PhysiCell interactive tool
2. Polls the Galaxy API until the tool's container is running
3. **Playwright** opens the tool's entry point URL and verifies the PhysiCell UI loads
4. Records startup time and writes a JSON result file
5. On failure: captures screenshot, page HTML, and failure metadata

## Prerequisites

- Python 3.11+
- A Galaxy account with access to the PhysiCell interactive tool
- Galaxy API key (or username/password)

## Local setup

```bash
# Clone and install
git clone <repo-url>
cd check-physicell-it-startup
pip install -e .

# Install Playwright browser
playwright install chromium

# Configure credentials
cp .env.example .env
# Edit .env with your Galaxy credentials
```

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GALAXY_BASE_URL` | No | `https://usegalaxy.org` | Galaxy server URL |
| `GALAXY_API_KEY` | Yes* | — | Galaxy API key |
| `GALAXY_USERNAME` | Yes* | — | Galaxy username (alternative to API key) |
| `GALAXY_PASSWORD` | Yes* | — | Galaxy password (alternative to API key) |
| `PHYSICELL_TOOL_ID` | No | `toolshed.g2.bx.psu.edu/repos/rheiland/physicell_studio/interactive_tool_pcstudio/0.7` | Galaxy tool ID |
| `STARTUP_TIMEOUT_SECONDS` | No | `600` | Max seconds allowed for the full startup check (job, entry point, and UI) |
| `HISTORY_NAME` | No | `PhysiCell Monitor` | Galaxy history name to use |
| `OUTPUT_DIR` | No | `output` | Directory for result files |

\* Provide either `GALAXY_API_KEY` or both `GALAXY_USERNAME` and `GALAXY_PASSWORD`.

## Running locally

```bash
pytest tests/ -v
```

## Scheduled runs (GitHub Actions)

The workflow at `.github/workflows/scheduled-monitor.yml` runs every 6 hours and on manual dispatch.

Required GitHub secrets:
- `GALAXY_BASE_URL`
- `GALAXY_API_KEY`

Results and failure artifacts are uploaded as workflow artifacts (retained 30 days).

## Output format

Each run writes to `output/<timestamp>/result.json`:

```json
{
  "timestamp": "2026-04-01T12:00:00+00:00",
  "environment": "https://usegalaxy.org",
  "success": true,
  "startup_seconds": 145.3,
  "failure_stage": null,
  "failure_message": null
}
```

On failure, the directory also contains `failure.png` (screenshot) and `page.html`.

## Known limitations

- **PhysiCell tool ID**: Defaults to `toolshed.g2.bx.psu.edu/repos/rheiland/physicell_studio/interactive_tool_pcstudio/0.7`. Override `PHYSICELL_TOOL_ID` if your Galaxy instance uses a different installed revision.
- **UI verification selectors**: The check for PhysiCell content in the browser is basic (looks for "PhysiCell" text). May need refinement once the exact tool UI is known.
- **Cross-origin iframes**: If the interactive tool runs on a separate domain, browser-level content verification may be limited.
- **History cleanup**: The monitor reuses a single history and purges datasets between runs. Manual cleanup may occasionally be needed.
