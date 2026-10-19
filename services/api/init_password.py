
from getpass import getpass

from sqlalchemy import select

from auth import hash_password
from database import SessionLocal
from models import User

password = getpass("Choisis un mot de passe pour Alice : ")

if len(password) < 12:
    raise ValueError("Le mot de passe doit contenir au moins 12 caractères")

with SessionLocal.begin() as db:
    alice = db.scalar(
        select(User).where(User.email == "alice@example.com")
    )

    if alice is None:
        raise ValueError("Alice est introuvable dans PostgreSQL")

    alice.password_hash = hash_password(password)

print("Mot de passe d'Alice enregistré avec succès")
