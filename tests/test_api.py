
import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_accueil(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "message": "Bienvenue sur Resilience Alpha"
    }


def test_health(client, monkeypatch):
    monkeypatch.setattr("main.check_database", lambda: None)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "UP",
        "database": "UP"
    }


def test_accounts_sans_token(client):
    response = client.get("/accounts")

    assert response.status_code == 401


def test_accounts_token_invalide(client):
    response = client.get(
        "/accounts",
        headers={"Authorization": "Bearer token_invalide"}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Token invalide ou expiré"


def test_transactions_sans_token(client):
    response = client.post(
        "/transactions",
        json={
            "source_account_id": 1,
            "destination_account_id": 2,
            "amount": 100
        }
    )

    assert response.status_code == 401


def test_transactions_lecture_sans_token(client):
    response = client.get("/transactions")

    assert response.status_code == 401


def test_compte_sans_token(client):
    response = client.get("/accounts/1")

    assert response.status_code == 401
