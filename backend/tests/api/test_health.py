from collections.abc import Generator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.conversations.limits import Limits
from backend.conversations.store import ConversationStore
from tests.api.coaches import unused_coach
from tests.api.tokens import fake_verifier
from tests.conversations.memory_store import InMemoryConversationStore
from tests.decks.memory_store import no_decks


@contextmanager
def _open_store() -> Generator[ConversationStore]:
    yield InMemoryConversationStore(Limits())


def test_health_is_ok_without_a_token_when_the_database_answers() -> None:
    pings: list[None] = []

    def ping_database() -> None:
        pings.append(None)

    client = TestClient(
        create_app(
            fake_verifier(),
            _open_store,
            open_decks=no_decks,
            coach=unused_coach,
            ping_database=ping_database,
        )
    )

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert len(pings) == 1


def test_health_is_a_503_when_the_database_is_unreachable() -> None:
    def database_down() -> None:
        raise ConnectionError("connection refused")

    client = TestClient(
        create_app(
            fake_verifier(),
            _open_store,
            open_decks=no_decks,
            coach=unused_coach,
            ping_database=database_down,
        )
    )

    response = client.get("/health")

    assert response.status_code == 503
