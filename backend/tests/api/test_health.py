from fastapi.testclient import TestClient

from tests.api.app_factory import make_app


def test_health_is_ok_without_a_token_when_the_database_answers() -> None:
    pings: list[None] = []

    def ping_database() -> None:
        pings.append(None)

    client = TestClient(make_app(ping_database=ping_database))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert len(pings) == 1


def test_health_is_a_503_when_the_database_is_unreachable() -> None:
    def database_down() -> None:
        raise ConnectionError("connection refused")

    client = TestClient(make_app(ping_database=database_down))

    response = client.get("/health")

    assert response.status_code == 503
