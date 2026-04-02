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


GALAXY_BASE_URL = env_or_default("GALAXY_BASE_URL", "https://usegalaxy.org")
GALAXY_API_KEY = env_or_empty("GALAXY_API_KEY")
GALAXY_USERNAME = env_or_empty("GALAXY_USERNAME")
GALAXY_PASSWORD = env_or_empty("GALAXY_PASSWORD")

PHYSICELL_TOOL_ID = os.getenv(
    "PHYSICELL_TOOL_ID",
    "toolshed.g2.bx.psu.edu/repos/rheiland/physicell_studio/interactive_tool_pcstudio/0.7",
)

STARTUP_TIMEOUT_SECONDS = int(os.getenv("STARTUP_TIMEOUT_SECONDS", "600"))
HISTORY_NAME = os.getenv("HISTORY_NAME", "PhysiCell Monitor")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))
