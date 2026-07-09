import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def env_or_default(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip() or default


def env_or_empty(name: str) -> str:
    return os.getenv(name, "").strip()


def env_int(name: str, default: int, minimum: int | None = None) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    parsed = int(value)
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return parsed


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False

    raise ValueError(f"{name} must be true or false")


def env_choice(name: str, default: str, choices: set[str]) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default

    normalized = value.strip().lower()
    if normalized not in choices:
        expected = ", ".join(sorted(choices))
        raise ValueError(f"{name} must be one of: {expected}")
    return normalized


GALAXY_BASE_URL = env_or_default("GALAXY_BASE_URL", "https://usegalaxy.org")
GALAXY_API_KEY = env_or_empty("GALAXY_API_KEY")
GALAXY_USERNAME = env_or_empty("GALAXY_USERNAME")
GALAXY_PASSWORD = env_or_empty("GALAXY_PASSWORD")

PHYSICELL_TOOL_ID = env_or_default(
    "PHYSICELL_TOOL_ID",
    "toolshed.g2.bx.psu.edu/repos/rheiland/physicell_studio/interactive_tool_pcstudio/0.7",
)
PHYSICELL_TOOL_VERSION_POLICY = env_choice(
    "PHYSICELL_TOOL_VERSION_POLICY",
    "latest",
    {"latest", "pinned"},
)

PREFLIGHT_ENABLED = env_bool("PREFLIGHT_ENABLED", True)
PREFLIGHT_TIMEOUT_SECONDS = env_int("PREFLIGHT_TIMEOUT_SECONDS", 15, minimum=1)
GALAXY_STATUSPAGE_SUMMARY_URL = env_or_default(
    "GALAXY_STATUSPAGE_SUMMARY_URL",
    "https://galaxyproject.statuspage.io/api/v2/summary.json",
)

STARTUP_TIMEOUT_SECONDS = env_int("STARTUP_TIMEOUT_SECONDS", 600, minimum=1)
STARTUP_EXPECTED_SECONDS = env_int("STARTUP_EXPECTED_SECONDS", 120, minimum=1)
REQUIRE_UI_VERIFICATION = env_bool("REQUIRE_UI_VERIFICATION", True)
UI_VERIFY_TIMEOUT_SECONDS = env_int("UI_VERIFY_TIMEOUT_SECONDS", 60, minimum=1)
GALAXY_LOGIN_TIMEOUT_SECONDS = env_int("GALAXY_LOGIN_TIMEOUT_SECONDS", 30, minimum=1)
PURGE_REUSED_HISTORY = env_bool("PURGE_REUSED_HISTORY", False)
HISTORY_NAME = env_or_default("HISTORY_NAME", "PhysiCell Monitor")
OUTPUT_DIR = Path(env_or_default("OUTPUT_DIR", "output"))
