"""Journaux JSON sur stdout : une ligne par événement, collectée par Promtail puis Loki (SIEM)."""
import json
import sys
from datetime import datetime, timezone

from .config import env

SERVICE = env("SERVICE_NAME", "unknown")


def log(event: str, level: str = "info", **fields) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "level": level,
        "service": SERVICE,
        "event": event,
        **fields,
    }
    sys.stdout.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def client_ip(request) -> str:
    """IP du client. uvicorn (--proxy-headers) l'a déjà extraite de X-Forwarded-For,
    posé par le proxy frontal : les services ne sont joignables que par ce proxy."""
    return request.client.host if request.client else "-"
