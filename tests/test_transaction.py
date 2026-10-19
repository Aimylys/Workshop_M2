
import json
import sys
import urllib.error
import urllib.request
from decimal import Decimal

BASE_URL = "http://127.0.0.1:8000"


def api_request(path, method="GET", payload=None):
    data = None
    headers = {}

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        BASE_URL + path,
        data=data,
        headers=headers,
        method=method
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def main():
    health = api_request("/health")
    assert health["status"] == "UP"
    assert health["database"] == "UP"
    print("OK - API et PostgreSQL disponibles")

    accounts = api_request("/accounts")
    assert len(accounts) >= 2

    source = accounts[0]
    destination = accounts[1]

    amount = Decimal("1.00")
    source_before = Decimal(str(source["balance"]))
    destination_before = Decimal(str(destination["balance"]))

    if source_before < amount:
        raise RuntimeError("Solde insuffisant pour le test")

    transaction = api_request(
        "/transactions",
        method="POST",
        payload={
            "source_account_id": source["id"],
            "destination_account_id": destination["id"],
            "amount": str(amount)
        }
    )

    assert Decimal(str(transaction["amount"])) == amount

    source_after = api_request(f"/accounts/{source['id']}")
    destination_after = api_request(f"/accounts/{destination['id']}")

    assert Decimal(str(source_after["balance"])) == source_before - amount
    assert Decimal(str(destination_after["balance"])) == destination_before + amount

    print("OK - Transaction bancaire effectuée")
    print("OK - Débit et crédit vérifiés")
    print("TEST DE RESILIENCE REUSSI")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ECHEC DU TEST : {error}", file=sys.stderr)
        sys.exit(1)
