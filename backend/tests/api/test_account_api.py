import uuid
from collections.abc import Generator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.conversations.limits import Limits
from backend.conversations.store import ConversationStore
from tests.api.accounts import FakeAccounts
from tests.api.coaches import unused_coach
from tests.api.tokens import fake_verifier, mint
from tests.conversations.memory_store import InMemoryConversationStore
from tests.decks.memory_store import no_decks

ALICE = uuid.UUID("aaaaaaaa-0000-4000-8000-000000000001")


@contextmanager
def _open_store() -> Generator[ConversationStore]:
    yield InMemoryConversationStore(Limits())


@pytest.fixture
def accounts() -> FakeAccounts:
    return FakeAccounts()


@pytest.fixture
def client(accounts: FakeAccounts) -> TestClient:
    return TestClient(
        create_app(
            fake_verifier(),
            _open_store,
            open_decks=no_decks,
            coach=unused_coach,
            delete_account=accounts.delete,
        )
    )


def _as(user: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {mint(user)}"}


def test_deleting_an_account_needs_a_token(client: TestClient, accounts: FakeAccounts) -> None:
    response = client.delete("/account")

    assert response.status_code == 401
    assert accounts.deleted == []


def test_a_signed_in_user_deletes_their_own_account(
    client: TestClient, accounts: FakeAccounts
) -> None:
    response = client.delete("/account", headers=_as(ALICE))

    assert response.status_code == 204
    assert accounts.deleted == [ALICE]
