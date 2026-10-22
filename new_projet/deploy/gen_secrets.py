"""Génère les secrets locaux de la plateforme dans deploy/secrets/ (fichiers non versionnés).

Ne remplace JAMAIS un secret existant : la base, déjà initialisée, en dépend.
Usage : python deploy/gen_secrets.py
"""
import secrets
import string
from pathlib import Path

SECRETS_DIR = Path(__file__).resolve().parent / "secrets"
ALPHABET = string.ascii_letters + string.digits

NAMES = {
    "postgres_password": 32,
    "auth_db_password": 32,
    "payment_db_password": 32,
    "jwt_secret": 64,
    "demo_password": 16,     # comptes fictifs alice / bob / charlie
    "probe_password": 24,    # compte technique de la transaction de vérification
    "grafana_admin_password": 24,
}


def main() -> None:
    SECRETS_DIR.mkdir(exist_ok=True)
    for name, length in NAMES.items():
        path = SECRETS_DIR / name
        if path.exists():
            print(f"  conservé : {name}")
            continue
        path.write_text("".join(secrets.choice(ALPHABET) for _ in range(length)), encoding="utf-8")
        print(f"  créé     : {name}")
    print(f"\nMot de passe des comptes de démo (alice, bob, charlie) : voir {SECRETS_DIR / 'demo_password'}")
    print(f"Mot de passe Grafana (utilisateur admin) : voir {SECRETS_DIR / 'grafana_admin_password'}")


if __name__ == "__main__":
    main()
