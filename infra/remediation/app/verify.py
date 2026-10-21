import os

import httpx


def http_check(client: httpx.Client, url: str, timeout: float):
    try:
        r = client.get(url, timeout=timeout)
        return r.status_code == 200, f"HTTP {r.status_code}"
    except Exception as e:  # noqa: BLE001
        return False, type(e).__name__


def docker_check(state: dict):
    if not state.get("present"):
        return False, "conteneur absent"
    health, status = state.get("health"), state.get("status")
    ok = health == "healthy" or (health is None and status == "running")
    return ok, f"docker {status}/{health}"


def transaction_test(cfg: dict, client: httpx.Client, timeout: float):
    """Login (optionnel) puis transaction fictive. Preuve de reprise métier."""
    try:
        base = cfg["base_url"].rstrip("/")
        headers = {}
        login = cfg.get("login")
        if login:
            body = dict(login.get("body", {}))
            pw = os.getenv(login.get("password_env", ""), "")
            if not pw:
                return False, "mot de passe du compte de test absent (variable d'environnement)"
            body[login.get("password_field", "password")] = pw
            if login.get("form"):   # OAuth2PasswordRequestForm : application/x-www-form-urlencoded
                r = client.post(base + login["path"], data=body, timeout=timeout)
            else:
                r = client.post(base + login["path"], json=body, timeout=timeout)
            if r.status_code != 200:
                return False, f"login HTTP {r.status_code}"
            token = r.json().get(login.get("token_field", "access_token"))
            if not token:
                return False, "jeton absent de la réponse de login"
            headers["Authorization"] = f"Bearer {token}"
        tx = cfg["transaction"]
        r = client.post(base + tx["path"], json=tx.get("body", {}), headers=headers, timeout=timeout)
        ok = r.status_code in tx.get("expect_status", [200, 201])
        return ok, f"transaction HTTP {r.status_code}"
    except Exception as e:  # noqa: BLE001
        return False, f"transaction : {type(e).__name__}"
