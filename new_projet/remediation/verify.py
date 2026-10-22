"""Vérification de la reprise : sonde /health PUIS transaction de test réussie.

Un conteneur qui redémarre ne prouve rien (exigence du sujet) : la preuve est qu'une vraie
opération métier aboutit de nouveau. On teste donc un virement de bout en bout avec le compte
technique « probe ».
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from . import config


def _call(method, path, body=None, token=None, timeout=5):
    url = config.BASE_URL + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if method == "POST" and path == config.VERIFY["tx_path"]:
        req.add_header("Idempotency-Key", str(uuid.uuid4()))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:  # noqa: BLE001
            return e.code, {}
    except Exception:  # noqa: BLE001
        return 0, {}


def health_ok() -> tuple[bool, dict]:
    v = config.VERIFY
    results = {}
    for path in v["health_paths"]:
        status, _ = _call("GET", path, timeout=v["http_timeout_s"])
        results[path] = status
    return all(code == 200 for code in results.values()), results


def test_transaction() -> tuple[bool, str]:
    """Login « probe » puis virement 0,01 €. Renvoie (réussi, détail)."""
    v = config.VERIFY
    secret = Path(v["probe_secret_file"])
    if not secret.exists():
        return False, "secret probe absent (deploy/secrets/probe_password)"
    password = secret.read_text(encoding="utf-8").strip()

    status, body = _call("POST", v["login_path"],
                         {"username": v["probe_user"], "password": password}, timeout=v["http_timeout_s"])
    if status != 200 or "access_token" not in body:
        return False, f"login probe HTTP {status}"
    token = body["access_token"]

    status, body = _call("POST", v["tx_path"],
                         {"source_account_id": v["tx_source"], "destination_account_id": v["tx_dest"],
                          "amount": v["tx_amount"]}, token=token, timeout=v["http_timeout_s"])
    if status == 201:
        return True, f"transaction test réussie (n°{body.get('id')})"
    return False, f"transaction test HTTP {status} ({body.get('detail', '')})"


def verify_recovery() -> tuple[bool, dict]:
    """Sonde /health puis transaction test, avec ré-essais. Renvoie (ok, détails)."""
    v = config.VERIFY
    detail = {}
    for attempt in range(1, v["retries"] + 1):
        ok_health, health = health_ok()
        detail["health"] = health
        if ok_health:
            ok_tx, tx = test_transaction()
            detail["transaction"] = tx
            if ok_tx:
                detail["attempts"] = attempt
                return True, detail
        if attempt < v["retries"]:
            time.sleep(v["retry_interval_s"])
    detail["attempts"] = v["retries"]
    return False, detail
