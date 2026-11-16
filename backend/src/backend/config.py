"""Runtime configuration read from the environment (and `backend/.env` when present)."""

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
CARDS_DATA_DIR = REPO_ROOT / "data" / "cards"


class MissingConfigError(RuntimeError):
    """A required setting is not configured."""


def to_sqlalchemy_url(url: str) -> str:
    """Make a Supabase/Postgres URL use the psycopg 3 driver."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def database_url() -> str:
    load_dotenv(BACKEND_DIR / ".env")
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise MissingConfigError("DATABASE_URL is not set (see backend/.env.example).")
    return to_sqlalchemy_url(url)
