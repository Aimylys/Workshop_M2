"""Pilotage des profils d'attaque LOCAUX pour la console (démarrer / arrêter / état).

Chaque attaque est lancée comme sous-processus `python -m labtest.run_scenario ...` (durée
longue, arrêtée à la demande). « service_down » est l'arrêt/redémarrage du conteneur db. Tout
reste local : les profils eux-mêmes refusent toute cible hors 127.0.0.1 (labtest.guard).
"""
from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = str(ROOT / "deploy" / "docker-compose.yml")
NETWORK_PATTERNS = ("ddos", "brute_force", "sql_injection", "port_scan")
ALL_PATTERNS = NETWORK_PATTERNS + ("service_down",)


class AttackManager:
    def __init__(self, base_url="http://127.0.0.1:8088"):
        self.base_url = base_url
        self._procs: dict[str, subprocess.Popen] = {}
        self._down = False               # état « service_down » (db arrêtée)
        self._lock = threading.Lock()

    def start(self, name: str) -> dict:
        if name not in ALL_PATTERNS:
            return {"ok": False, "error": f"profil inconnu : {name}"}
        with self._lock:
            if self.running(name):
                return {"ok": True, "status": "déjà en cours", "name": name}
            if name == "service_down":
                r = subprocess.run(["docker", "compose", "-f", COMPOSE, "stop", "db"],
                                   capture_output=True, text=True)
                if r.returncode != 0:
                    return {"ok": False, "error": r.stderr.strip()[:200]}
                self._down = True
            else:
                self._procs[name] = subprocess.Popen(
                    [sys.executable, "-m", "labtest.run_scenario", name,
                     "--base", self.base_url, "--duration", "3600"],
                    cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"ok": True, "status": "lancé", "name": name}

    def stop(self, name: str) -> dict:
        with self._lock:
            if name == "service_down":
                r = subprocess.run(["docker", "compose", "-f", COMPOSE, "start", "db"],
                                   capture_output=True, text=True)
                self._down = False
                if r.returncode != 0:
                    return {"ok": False, "error": r.stderr.strip()[:200]}
            else:
                proc = self._procs.pop(name, None)
                if proc and proc.poll() is None:
                    proc.terminate()
        return {"ok": True, "status": "arrêté", "name": name}

    def running(self, name: str) -> bool:
        if name == "service_down":
            return self._down
        proc = self._procs.get(name)
        return proc is not None and proc.poll() is None

    def status(self) -> dict:
        return {name: self.running(name) for name in ALL_PATTERNS}

    def stop_all(self) -> None:
        for name in ALL_PATTERNS:
            if self.running(name):
                self.stop(name)
