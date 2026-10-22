
from database import engine
from models import Base

print("Création des tables PostgreSQL...")

Base.metadata.create_all(bind=engine)

print("Tables créées avec succès !")