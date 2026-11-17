from pathlib import Path

import pytest

import backend.config
from backend.config import (
    MissingConfigError,
    cors_allowed_origins,
    database_url,
    to_sqlalchemy_url,
)


@pytest.fixture
def no_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's real backend/.env out of these tests."""

    def skip_loading(path: Path) -> bool:
        return False

    monkeypatch.setattr(backend.config, "load_dotenv", skip_loading)


def test_postgres_urls_are_rewritten_to_the_psycopg_driver() -> None:
    assert to_sqlalchemy_url("postgresql://u:p@host/db") == "postgresql+psycopg://u:p@host/db"
    assert to_sqlalchemy_url("postgres://u:p@host/db") == "postgresql+psycopg://u:p@host/db"


def test_a_url_that_already_names_a_driver_is_left_alone() -> None:
    assert to_sqlalchemy_url("postgresql+psycopg://u@host/db") == "postgresql+psycopg://u@host/db"


def test_database_url_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, no_dotenv: None
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")

    assert database_url() == "postgresql+psycopg://u:p@host/db"


def test_a_missing_database_url_is_a_clear_error(
    monkeypatch: pytest.MonkeyPatch, no_dotenv: None
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(MissingConfigError, match="DATABASE_URL"):
        database_url()


def test_no_cors_origins_are_allowed_unless_configured(
    monkeypatch: pytest.MonkeyPatch, no_dotenv: None
) -> None:
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)

    assert cors_allowed_origins() == ()


def test_cors_origins_are_a_comma_separated_list(
    monkeypatch: pytest.MonkeyPatch, no_dotenv: None
) -> None:
    monkeypatch.setenv(
        "CORS_ALLOWED_ORIGINS", " https://hexcoach.example/ , http://localhost:5173,,"
    )

    assert cors_allowed_origins() == ("https://hexcoach.example", "http://localhost:5173")
