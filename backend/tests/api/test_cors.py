from collections.abc import Generator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.conversations.limits import Limits
from backend.conversations.store import ConversationStore
from tests.api.tokens import fake_verifier
from tests.conversations.memory_store import InMemoryConversationStore

FRONTEND = "https://hexcoach.example"


@contextmanager
def _open_store() -> Generator[ConversationStore]:
    yield InMemoryConversationStore(Limits())


def _preflight(client: TestClient, origin: str) -> dict[str, str]:
    response = client.options(
        "/conversations",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization, content-type",
        },
    )
    return dict(response.headers)


def test_a_configured_frontend_may_call_the_api_with_its_bearer_token() -> None:
    client = TestClient(create_app(fake_verifier(), _open_store, cors_origins=(FRONTEND,)))

    headers = _preflight(client, FRONTEND)

    assert headers["access-control-allow-origin"] == FRONTEND
    assert "POST" in headers["access-control-allow-methods"]
    assert "authorization" in headers["access-control-allow-headers"].lower()


def test_other_origins_get_no_cors_permission() -> None:
    client = TestClient(create_app(fake_verifier(), _open_store, cors_origins=(FRONTEND,)))

    headers = _preflight(client, "https://evil.example")

    assert "access-control-allow-origin" not in headers
