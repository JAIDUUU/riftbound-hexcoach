import uuid

import pytest
from fastapi.testclient import TestClient

from tests.api.accounts import FakeAccounts
from tests.api.app_factory import make_app
from tests.api.tokens import mint

ALICE = uuid.UUID("aaaaaaaa-0000-4000-8000-000000000001")


@pytest.fixture
def accounts() -> FakeAccounts:
    return FakeAccounts()


@pytest.fixture
def client(accounts: FakeAccounts) -> TestClient:
    return TestClient(make_app(delete_account=accounts.delete))


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
