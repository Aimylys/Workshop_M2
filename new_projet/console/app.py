"""Backend de la console de démonstration.

Relie en un seul endroit : les KPI en direct (Prometheus), le verdict de la détection
(kNN), l'explication de l'assistant RAG et la remédiation recommandée. Sert aussi les deux
pages web et pilote les attaques locales.

Lancement :
    python -m console.app            # puis http://127.0.0.1:8060
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from .attacks import ALL_PATTERNS, AttackManager

ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).resolve().parent / "static"

# Remédiation RECOMMANDÉE par état (ce que la phase 7 exécutera ; ici on l'affiche seulement).
REMEDIATION = {
    "normal": None,
    "ddos": "Bloquer l'IP source au WAF / limiter le débit, puis redémarrer l'API si la "
            "dégradation persiste. Vérifier par /health + une transaction de test.",
    "brute_force": "Bloquer l'IP source et verrouiller le compte visé (verrouillage automatique "
                   "après 10 échecs déjà actif). Vérifier qu'un compte sain se connecte encore.",
    "sql_injection": "CONFINEMENT : bloquer l'IP source, alerter, conserver les journaux. Ne PAS "
                     "se contenter de redémarrer — tentative de compromission, pas panne.",
    "port_scan": "Bloquer l'IP source et renforcer la surveillance. Pas de redémarrage nécessaire.",
    "service_down": "Redémarrer le conteneur en panne, puis vérifier /health et une transaction "
                    "de test réussie (un redémarrage seul ne prouve pas la reprise).",
    "inconnu": "État non reconnu : escalade à un analyste humain, pas d'action automatique.",
}

HISTORY_SIZE = 120            # ~6 min à un point toutes les 3 s
HISTORY_KPIS = ["req_per_sec", "edge_req_per_sec", "edge_conn_per_sec", "login_fail_per_sec",
                "waf_blocked_per_sec", "waf_404_per_sec", "tx_ok_per_sec",
                "latency_p95_payment_seconds", "inprogress"]


class State:
    def __init__(self):
        self.detector = None
        self.detector_error = None
        self.assistant = None
        self.assistant_error = None
        self.attacks = AttackManager()
        self.history = deque(maxlen=HISTORY_SIZE)
        self.rag_cache: dict[str, dict] = {}
        self.rag_pending: set[str] = set()
        self.lock = threading.Lock()


state = State()


def load_models():
    """Charge le détecteur et l'assistant RAG (tolérant : la console démarre même sans eux)."""
    try:
        from detection.detect import Detector
        state.detector = Detector()
    except Exception as exc:  # noqa: BLE001
        state.detector_error = f"{type(exc).__name__}: {exc}"
    try:
        from assistant.rag import Assistant
        state.assistant = Assistant()
    except Exception as exc:  # noqa: BLE001
        state.assistant_error = f"{type(exc).__name__}: {exc}"


def rag_for(label: str, triggers: list) -> dict | None:
    """Explication RAG en cache par état ; calcul en tâche de fond (le LLM met quelques secondes)."""
    if label in ("normal", "inconnu") or state.assistant is None:
        return None
    with state.lock:
        if label in state.rag_cache:
            return state.rag_cache[label]
        if label in state.rag_pending:
            return {"text": "Analyse de l'assistant en cours…", "sources": [], "pending": True}
        state.rag_pending.add(label)

    def work():
        result = state.assistant.explain(label, triggers)
        with state.lock:
            state.rag_cache[label] = result
            state.rag_pending.discard(label)

    threading.Thread(target=work, daemon=True).start()
    return {"text": "Analyse de l'assistant en cours…", "sources": [], "pending": True}


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_models()
    yield
    state.attacks.stop_all()


app = FastAPI(title="Resilience-Alpha — Console", lifespan=lifespan)


@app.get("/api/status")
def status():
    if state.detector is None:
        return JSONResponse({"ready": False,
                             "error": f"modèle de détection non chargé ({state.detector_error}). "
                                      "Lancer : python -m detection.index build"},
                            status_code=503)
    try:
        state.detector.prom.check_ready()
        kpis = state.detector.prom.snapshot(state.detector.kpi_names)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ready": False, "error": f"Prometheus indisponible : {exc}"},
                            status_code=503)

    from detection.features import vector_from_kpis
    verdict = state.detector.model.predict(vector_from_kpis(kpis))
    clean = {k.removeprefix("kpi:"): (None if v is None else round(float(v), 3)) for k, v in kpis.items()}

    with state.lock:
        state.history.append({"t": int(time.time()),
                              "kpis": {k: clean.get(k) for k in HISTORY_KPIS},
                              "label": verdict.label})

    return {
        "ready": True,
        "verdict": verdict.to_dict(),
        "kpis": clean,
        "remediation": REMEDIATION.get(verdict.label),
        "rag": rag_for(verdict.label, verdict.triggers),
        "attacks": state.attacks.status(),
        "assistant_available": state.assistant is not None,
    }


@app.get("/api/history")
def history():
    with state.lock:
        return {"points": list(state.history), "kpis": HISTORY_KPIS}


@app.get("/api/remediation")
def remediation(limit: int = 12):
    """Dernières étapes du journal de remédiation (si le moteur tourne)."""
    try:
        from remediation.config import JOURNAL
    except Exception:  # noqa: BLE001
        return {"available": False, "entries": []}
    if not JOURNAL.exists():
        return {"available": False, "entries": []}
    entries = []
    try:
        for line in JOURNAL.read_text(encoding="utf-8").splitlines()[-limit:]:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    except Exception:  # noqa: BLE001
        pass
    return {"available": True, "entries": entries[::-1]}


@app.get("/api/attacks")
def attacks():
    return {"patterns": list(ALL_PATTERNS), "running": state.attacks.status()}


@app.post("/api/attacks/{name}/{action}")
def attack_action(name: str, action: str):
    if action == "start":
        return state.attacks.start(name)
    if action == "stop":
        return state.attacks.stop(name)
    return JSONResponse({"ok": False, "error": "action inconnue"}, status_code=400)


@app.get("/")
def dashboard():
    return FileResponse(STATIC / "dashboard.html")


@app.get("/attacker")
def attacker():
    return FileResponse(STATIC / "attacker.html")


def main():
    import uvicorn
    print("Console : http://127.0.0.1:8060  (dashboard)  |  http://127.0.0.1:8060/attacker")
    uvicorn.run(app, host="127.0.0.1", port=8060, log_level="warning")


if __name__ == "__main__":
    main()
