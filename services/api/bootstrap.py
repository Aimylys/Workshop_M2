"""Initialisation non interactive et idempotente de la base de démonstration."""
import os
import sys
from decimal import Decimal

from sqlalchemy import select

from auth import hash_password, verify_password
from database import SessionLocal, engine
from models import Account, Base, User

DEMO_USERS = [
    ("Alice Martin", "alice@example.com", Decimal("1500.00")),
    ("Bob Dupont", "bob@example.com", Decimal("750.00")),
    ("Charlie Bernard", "charlie@example.com", Decimal("2300.00")),
]
DEMO_LOGIN_EMAIL = "alice@example.com"


def main() -> None:
    password = os.environ.get("DEMO_PASSWORD", "")
    if len(password) < 12:
        sys.exit("DEMO_PASSWORD absent ou trop court (12 caractères minimum)")

    Base.metadata.create_all(bind=engine)

    with SessionLocal.begin() as db:
        for nom, email, solde in DEMO_USERS:
            user = db.scalar(select(User).where(User.email == email))
            if user is None:
                user = User(name=nom, email=email)
                db.add(user)
                db.flush()
                db.add(Account(user_id=user.id, balance=solde))
                print(f"Compte créé : {nom}")
            else:
                print(f"Utilisateur déjà présent : {nom}")

        alice = db.scalar(select(User).where(User.email == DEMO_LOGIN_EMAIL))
        if alice.password_hash is None or not verify_password(password, alice.password_hash):
            alice.password_hash = hash_password(password)
            print("Mot de passe du compte de démo défini")
        else:
            print("Mot de passe du compte de démo déjà à jour")


if __name__ == "__main__":
    main()