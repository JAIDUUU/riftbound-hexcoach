import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from backend.db import make_engine, ping_database


def test_pinging_an_unreachable_database_raises() -> None:
    # Port 1 on loopback: refused at once, so this never reaches a real database.
    engine = create_engine("postgresql+psycopg://nobody@127.0.0.1:1/none")

    with pytest.raises(OperationalError):
        ping_database(engine)


@pytest.mark.integration
def test_pinging_the_configured_database_succeeds(migrated_database: None) -> None:
    engine = make_engine()
    try:
        ping_database(engine)
    finally:
        engine.dispose()
