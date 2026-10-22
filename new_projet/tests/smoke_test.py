"""Test de bout en bout sur la plateforme lancée (docker compose up).

Usage : python tests/smoke_test.py [--url http://127.0.0.1:8088]
Ne dépend que de la bibliothèque standard. Code de sortie 0 si tout passe.
"""
import argparse
import json
import random
import sys
import urllib.error
import urllib.request
import uuid
from decimal import Decimal
from pathlib import Path

SECRETS = Path(__file__).resolve().parent.parent / "deploy" / "secrets"
failures = 0


def call(base, method, path, body=None, token=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw and r.headers.get_content_type() == "application/json" else raw)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw


def check(name, condition, detail=""):
    global failures
    print(f"  [{'OK ' if condition else 'KO '}] {name}" + (f"  ({detail})" if detail and not condition else ""))
    if not condition:
        failures += 1


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8088")
    base = p.parse_args().url.rstrip("/")
    demo_pw = (SECRETS / "demo_password").read_text(encoding="utf-8").strip()

    print(f"Test de bout en bout sur {base}")
    s, _ = call(base, "GET", "/")
    check("frontal web servi", s == 200, s)
    for svc in ("auth", "pay"):
        s, b = call(base, "GET", f"/api/{svc}/health")
        check(f"santé {svc}", s == 200 and b.get("status") == "up", (s, b))

    s, _ = call(base, "POST", "/api/auth/login", {"username": "alice", "password": "mauvais"})
    check("mauvais mot de passe refusé (401)", s == 401, s)
    s, _ = call(base, "POST", "/api/auth/login", {"username": "inconnu", "password": "x"})
    check("utilisateur inconnu refusé (401)", s == 401, s)
    s, b = call(base, "POST", "/api/auth/login", {"username": "alice", "password": demo_pw})
    check("connexion d'alice", s == 200 and "access_token" in b, (s, b))
    if s != 200:
        sys.exit(1)
    token = b["access_token"]

    s, _ = call(base, "GET", "/api/pay/accounts")
    check("comptes sans jeton refusés (401)", s == 401, s)
    s, accounts = call(base, "GET", "/api/pay/accounts", token=token)
    check("liste des comptes d'alice", s == 200 and [a["id"] for a in accounts] == [1], (s, accounts))

    # Virement vers le compte de collecte n°5, que le trafic normal ne touche jamais, avec un
    # montant unique : le contrôle reste juste même si le générateur de trafic tourne.
    key = str(uuid.uuid4())
    amount = f"0.{random.randint(10, 99)}"
    transfer = {"source_account_id": 1, "destination_account_id": 5, "amount": amount}
    s1, tx1 = call(base, "POST", "/api/pay/transactions", transfer, token, {"Idempotency-Key": key})
    check("virement accepté (201)", s1 == 201, (s1, tx1))
    s2, tx2 = call(base, "POST", "/api/pay/transactions", transfer, token, {"Idempotency-Key": key})
    check("virement rejoué : même transaction renvoyée", s2 == 201 and tx1.get("id") == tx2.get("id"), (s2, tx2))
    _, history = call(base, "GET", "/api/pay/transactions", token=token)
    recent = [t for t in history if t["destination_account_id"] == 5 and t["id"] >= tx1.get("id", 0)
              and Decimal(t["amount"]) == Decimal(amount)]
    check("une seule écriture malgré le rejeu (pas de double débit)", len(recent) == 1, recent)

    s, _ = call(base, "POST", "/api/pay/transactions",
                {"source_account_id": 2, "destination_account_id": 1, "amount": "1.00"}, token)
    check("débit du compte d'un autre refusé (403)", s == 403, s)
    s, _ = call(base, "POST", "/api/pay/transactions",
                {"source_account_id": 1, "destination_account_id": 2, "amount": "10000.00"}, token)
    check("solde insuffisant refusé (409)", s == 409, s)
    s, _ = call(base, "POST", "/api/pay/transactions",
                {"source_account_id": 1, "destination_account_id": 999, "amount": "1.00"}, token)
    check("compte destinataire inconnu (404)", s == 404, s)

    s, _ = call(base, "GET", "/api/pay/metrics")
    check("métriques NON exposées par le frontal", s == 404, s)

    print("\nRésultat :", "SUCCÈS" if failures == 0 else f"{failures} échec(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
