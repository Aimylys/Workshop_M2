from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from common.tokens import issue_token


def test_transfer_validation(payment):
    ok = payment.TransferIn(source_account_id=1, destination_account_id=2, amount="12.50")
    assert ok.amount == Decimal("12.50")
    bad = [
        {"source_account_id": 1, "destination_account_id": 1, "amount": "1"},       # même compte
        {"source_account_id": 1, "destination_account_id": 2, "amount": "0"},       # montant nul
        {"source_account_id": 1, "destination_account_id": 2, "amount": "-5"},      # négatif
        {"source_account_id": 1, "destination_account_id": 2, "amount": "1.001"},   # 3 décimales
        {"source_account_id": 1, "destination_account_id": 2, "amount": "10000.01"},  # plafond
        {"source_account_id": 1, "destination_account_id": 2, "amount": "1", "extra": 1},
    ]
    for payload in bad:
        with pytest.raises(ValidationError):
            payment.TransferIn(**payload)


def test_routes_require_token(payment):
    client = TestClient(payment.app)
    assert client.get("/accounts").status_code == 401
    assert client.get("/transactions").status_code == 401
    r = client.post("/transactions", json={"source_account_id": 1, "destination_account_id": 2, "amount": "1"})
    assert r.status_code == 401
    r = client.get("/accounts", headers={"Authorization": "Bearer pas-un-jeton"})
    assert r.status_code == 401


def test_request_metrics_use_route_template(payment):
    from common.observability import REQUESTS  # noqa: PLC0415

    client = TestClient(payment.app)
    token, _ = issue_token("alice")
    # Le pool n'est pas ouvert dans ce test : la base est « indisponible ». La requête doit
    # répondre 503 proprement et être comptée sous le gabarit de route, pas sous /accounts/42.
    r = client.get("/accounts/42", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 503
    labels = {s.labels.get("route") for m in REQUESTS.collect() for s in m.samples}
    assert "/accounts/{account_id}" in labels
    assert "/accounts/42" not in labels
