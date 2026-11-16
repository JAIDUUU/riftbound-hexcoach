"""Database engine and migrations."""

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine

from backend.config import BACKEND_DIR, database_url


def make_engine() -> Engine:
    return create_engine(database_url(), pool_pre_ping=True)


def upgrade_to_head() -> None:
    """Apply every pending Alembic migration. Re-running is a no-op."""
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "src" / "backend" / "migrations"))
    command.upgrade(config, "head")
