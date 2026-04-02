import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

GALAXY_BASE_URL = os.getenv("GALAXY_BASE_URL", "https://usegalaxy.org")
GALAXY_API_KEY = os.getenv("GALAXY_API_KEY", "")
GALAXY_USERNAME = os.getenv("GALAXY_USERNAME", "")
GALAXY_PASSWORD = os.getenv("GALAXY_PASSWORD", "")

PHYSICELL_TOOL_ID = os.getenv(
    "PHYSICELL_TOOL_ID",
    "toolshed.g2.bx.psu.edu/repos/rheiland/physicell_studio/interactive_tool_pcstudio/0.7",
)

STARTUP_TIMEOUT_SECONDS = int(os.getenv("STARTUP_TIMEOUT_SECONDS", "600"))
HISTORY_NAME = os.getenv("HISTORY_NAME", "PhysiCell Monitor")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))
