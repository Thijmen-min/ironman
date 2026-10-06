"""Runtime configuration, read from environment / .env in the project root."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


DATA_DIR = Path(os.getenv("HW_DATA_DIR", PROJECT_ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "healthwatcher.db"
STATIC_DIR = Path(__file__).resolve().parent / "static"

# Shared with the Garmin MCP server (garmin-mcp-auth writes here too).
GARMIN_TOKENS = os.path.expanduser(os.getenv("GARMINTOKENS", "~/.garminconnect"))

HOST = os.getenv("HW_HOST", "127.0.0.1")
PORT = _int("HW_PORT", 8765)
SYNC_INTERVAL_MIN = _int("HW_SYNC_INTERVAL_MIN", 20)
BACKFILL_DAYS = _int("HW_BACKFILL_DAYS", 120)
# Days for which minute-level HR / stress / body-battery curves are kept.
INTRADAY_DAYS = _int("HW_INTRADAY_DAYS", 14)

STRAVA_CLIENT_ID = os.getenv("STRAVA_CLIENT_ID", "").strip()
STRAVA_CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET", "").strip()
STRAVA_REDIRECT_URI = f"http://localhost:{PORT}/strava/callback"
