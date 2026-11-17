"""Runtime configuration read from the environment (and `backend/.env` when present)."""

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
CARDS_DATA_DIR = REPO_ROOT / "data" / "cards"
RULES_DATA_DIR = REPO_ROOT / "data" / "rules"
FAQS_DATA_DIR = REPO_ROOT / "data" / "FAQs"
GOLDEN_SET_PATH = REPO_ROOT / "data" / "golden" / "golden-set.yaml"


class MissingConfigError(RuntimeError):
    """A required setting is not configured."""


def to_sqlalchemy_url(url: str) -> str:
    """Make a Supabase/Postgres URL use the psycopg 3 driver."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def optional_env(name: str) -> str | None:
    """A setting from the environment or `backend/.env`; None when unset or blank."""
    load_dotenv(BACKEND_DIR / ".env")
    return os.environ.get(name, "").strip() or None


def supabase_url() -> str:
    """The Supabase project URL (https://<ref>.supabase.co); its JWKS verifies sign-ins."""
    url = optional_env("SUPABASE_URL")
    if url is None:
        raise MissingConfigError("SUPABASE_URL is not set (see backend/.env.example).")
    return url


def database_url() -> str:
    url = optional_env("DATABASE_URL")
    if url is None:
        raise MissingConfigError("DATABASE_URL is not set (see backend/.env.example).")
    return to_sqlalchemy_url(url)
