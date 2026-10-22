"""Hachage des mots de passe (Argon2id).

Argon2 est volontairement coûteux en mémoire : chaque calcul réserve `memory_cost` Kio.
Sans limite, N connexions simultanées réservent N fois cette mémoire et le conteneur est
tué (OOM) : une simple rafale de connexions suffirait alors à faire tomber l'authentification.
Deux garde-fous :
  - paramètres explicites recommandés par l'OWASP (19 Mio, 2 passes, 1 fil) ;
  - au plus HASH_CONCURRENCY calculs simultanés ; les suivants attendent leur tour.
Sous attaque par force brute, la latence de /login augmente (signal visible par la
détection) mais la mémoire reste bornée et le service ne tombe pas.
"""
import threading

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from common.config import env_int

_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
_slots = threading.BoundedSemaphore(env_int("HASH_CONCURRENCY", 2))

# Haché factice : on vérifie contre lui quand l'utilisateur n'existe pas, pour que le temps
# de réponse ne révèle pas si un identifiant existe (énumération de comptes).
DUMMY_HASH = _hasher.hash("compte-inexistant")


def hash_password(password: str) -> str:
    with _slots:
        return _hasher.hash(password)


def verify(password_hash: str, password: str) -> bool:
    with _slots:
        try:
            return _hasher.verify(password_hash, password)
        except (VerificationError, InvalidHashError):
            return False


def needs_rehash(password_hash: str) -> bool:
    """Vrai si le haché a été créé avec d'autres paramètres : il est recalculé à la connexion."""
    return _hasher.check_needs_rehash(password_hash)
