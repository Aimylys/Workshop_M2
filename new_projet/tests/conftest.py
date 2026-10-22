"""Chargement des services pour les tests unitaires (sans base de données ni secrets réels)."""
import importlib
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SERVICES = ROOT / "services"

os.environ.setdefault("JWT_SECRET", "secret-de-test-uniquement-0123456789abcdef")
sys.path.insert(0, str(SERVICES))
sys.path.insert(0, str(ROOT))          # paquets data/ (collecteur) et suivants

_loaded = {}


def load_service(name: str):
    """Importe services/<name>/app/main.py. Les deux services ont un paquet « app » :
    on purge le précédent avant d'importer l'autre (chacun n'est importé qu'une fois)."""
    if name not in _loaded:
        for mod in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
            del sys.modules[mod]
        sys.path.insert(0, str(SERVICES / name))
        try:
            _loaded[name] = importlib.import_module("app.main")
        finally:
            sys.path.remove(str(SERVICES / name))
    return _loaded[name]


@pytest.fixture(scope="session")
def payment():
    return load_service("payment-api")


@pytest.fixture(scope="session")
def auth():
    return load_service("auth")
