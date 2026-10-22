"""Lecture de la configuration. Aucun secret n'a de valeur par défaut dans le code."""
import os
from functools import lru_cache


@lru_cache(maxsize=None)
def secret(name: str) -> str:
    """Lit le secret depuis le fichier NAME_FILE (secret Docker, déchiffré par SOPS),
    ou à défaut depuis la variable NAME. Échoue explicitement s'il est absent."""
    path = os.getenv(f"{name}_FILE")
    if path:
        with open(path, encoding="utf-8") as f:
            value = f.read().strip()
    else:
        value = os.getenv(name, "")
    if not value:
        raise RuntimeError(f"secret {name} absent (ni {name}_FILE ni {name})")
    return value


def env(name: str, default: str) -> str:
    return os.getenv(name, default)


def env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))
