
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import main
from auth import create_access_token
from models import Account, Base, Transaction, User


@pytest.fixture
def environnement_test(monkeypatch):
    # Base SQLite temporaire, indépendante de PostgreSQL.
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    Base.metadata.create_all(bind=engine)

    TestSessionLocal = sessionmaker(bind=engine)

    # Rediriger les sessions de l'API vers la base de test.
    monkeypatch.setattr(main, "SessionLocal", TestSessionLocal)

    with TestSessionLocal() as db:
        alice = User(
            name="Alice Test",
            email="alice.test@example.com",
        )
        bob = User(
            name="Bob Test",
            email="bob.test@example.com",
        )

        db.add_all([alice, bob])
        db.flush()

        source = Account(
            user_id=alice.id,
            balance=Decimal("1500.00"),
        )
        destination = Account(
            user_id=bob.id,
            balance=Decimal("750.00"),
        )

        db.add_all([source, destination])
        db.commit()

        alice_id = alice.id
        source_id = source.id
        destination_id = destination.id

    token = create_access_token(alice_id)

    with TestClient(main.app) as client:
        yield {
            "client": client,
            "headers": {
                "Authorization": f"Bearer {token}"
            },
            "session_factory": TestSessionLocal,
            "source_id": source_id,
            "destination_id": destination_id,
        }

    engine.dispose()


def test_virement_bancaire(environnement_test):
    env = environnement_test

    client = env["client"]
    headers = env["headers"]

    source_id = env["source_id"]
    destination_id = env["destination_id"]

    response = client.post(
        "/transactions",
        headers=headers,
        json={
            "source_account_id": source_id,
            "destination_account_id": destination_id,
            "amount": "100.00",
        },
    )

    assert response.status_code == 200, response.text

    transaction = response.json()

    assert transaction["source_account_id"] == source_id
    assert transaction["destination_account_id"] == destination_id
    assert Decimal(str(transaction["amount"])) == Decimal("100.00")

    with env["session_factory"]() as db:
        source = db.get(Account, source_id)
        destination = db.get(Account, destination_id)

        assert source.balance == Decimal("1400.00")
        assert destination.balance == Decimal("850.00")

        transactions = db.scalars(select(Transaction)).all()

        assert len(transactions) == 1


def test_virement_solde_insuffisant(environnement_test):
    env = environnement_test

    response = env["client"].post(
        "/transactions",
        headers=env["headers"],
        json={
            "source_account_id": env["source_id"],
            "destination_account_id": env["destination_id"],
            "amount": "99999.00",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Solde insuffisant"

    with env["session_factory"]() as db:
        source = db.get(Account, env["source_id"])
        destination = db.get(Account, env["destination_id"])

        assert source.balance == Decimal("1500.00")
        assert destination.balance == Decimal("750.00")
        assert db.scalars(select(Transaction)).all() == []


def test_virement_meme_compte(environnement_test):
    env = environnement_test

    response = env["client"].post(
        "/transactions",
        headers=env["headers"],
        json={
            "source_account_id": env["source_id"],
            "destination_account_id": env["source_id"],
            "amount": "100.00",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Les comptes doivent être différents"
