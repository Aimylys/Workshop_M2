
from decimal import Decimal

from sqlalchemy import select

from database import SessionLocal
from models import User, Account

with SessionLocal.begin() as db:
    utilisateurs = [
        ("Alice Martin", "alice@example.com", Decimal("1500.00")),
        ("Bob Dupont", "bob@example.com", Decimal("750.00")),
        ("Charlie Bernard", "charlie@example.com", Decimal("2300.00")),
    ]

    for nom, email, solde in utilisateurs:
        user = db.scalar(
            select(User).where(User.email == email)
        )

        if user is None:
            user = User(name=nom, email=email)
            db.add(user)
            db.flush()

            compte = Account(
                user_id=user.id,
                balance=solde
            )
            db.add(compte)

            print(f"Compte créé : {nom} - {solde} EUR")
        else:
            print(f"Utilisateur déjà présent : {nom}")

print("Initialisation terminée !")
