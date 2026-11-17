"""Database engine and migrations."""

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text

from backend.config import BACKEND_DIR, database_url


def make_engine() -> Engine:
    return create_engine(database_url(), pool_pre_ping=True)


def ping_database(engine: Engine) -> None:
    """One trivial round trip; raises if the database can't be reached."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def upgrade_to_head() -> None:
    """Apply every pending Alembic migration. Re-running is a no-op."""
    command.upgrade(Config(str(BACKEND_DIR / "alembic.ini")), "head")
