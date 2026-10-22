"""Moteur de remédiation : du verdict à l'action vérifiée et journalisée.

Pour chaque incident :
  1. confinement      : bloquer l'IP source (si identifiable dans les journaux) ;
  2. selon la nature  :
       - compromise (injection) : CONFINEMENT seul, jamais déclaré « résolu » (analyse humaine) ;
       - availability (panne/DDoS) : vérifier ; si non rétabli, redémarrer par paliers, re-vérifier ;
       - abuse / recon : confinement + vérification ;
  3. vérification      : /health + transaction de test réussie ;
  4. journal           : chaque étape est tracée (JSONL) ; idempotent et anti-boucle (cooldown).
"""
from __future__ import annotations

import json
import threading
import time

from . import actions, config, sources, verify


class RemediationEngine:
    def __init__(self):
        self.cooldown: dict[str, float] = {}
        self.incidents: list[dict] = []
        self.lock = threading.Lock()
        config.JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        self._n = 0

    # ---------- journal ----------
    def _log(self, inc: dict, step: str, status: str, detail: str = "") -> None:
        entry = {"ts": round(time.time(), 3), "step": step, "status": status, "detail": detail}
        inc["steps"].append(entry)
        line = json.dumps({"incident": inc["id"], "type": inc["type"], **entry}, ensure_ascii=False)
        print(f"[remediation] {line}", flush=True)
        with open(config.JOURNAL, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _finish(self, inc: dict, status: str, note: str) -> dict:
        inc.update(status=status, note=note, ended=round(time.time(), 3))
        self._log(inc, "closed", status, note)
        with self.lock:
            self.cooldown[inc["type"]] = time.time() + config.COOLDOWN_S
        return inc

    # ---------- décision ----------
    def should_act(self, label: str, confidence: float) -> tuple[bool, str]:
        if label not in config.KIND:
            return False, "type non remédiable"
        if confidence < config.CONF_MIN:
            return False, f"confiance insuffisante ({confidence:.0%})"
        if time.time() < self.cooldown.get(label, 0):
            return False, "délai de repos (anti-boucle)"
        return True, ""

    def handle(self, label: str, confidence: float, triggers=None) -> dict | None:
        ok, reason = self.should_act(label, confidence)
        if not ok:
            return None
        with self.lock:
            self._n += 1
            inc = {"id": f"INC-{int(time.time())}-{self._n}", "type": label,
                   "kind": config.KIND[label], "confidence": confidence,
                   "started": round(time.time(), 3), "steps": [], "status": "running"}
            self.incidents.append(inc)
        self._log(inc, "detected", "ok", f"{label} (confiance {confidence:.0%})")
        try:
            return self._run(inc)
        except Exception as exc:  # noqa: BLE001
            self._log(inc, "error", "failed", f"{type(exc).__name__}: {exc}")
            return self._finish(inc, "failed", "erreur interne : intervention humaine requise")

    # ---------- déroulé ----------
    def _contain(self, inc: dict) -> None:
        """Bloque l'IP source identifiée dans les journaux (si applicable)."""
        if inc["type"] == "service_down":
            return                                   # une panne n'a pas d'IP source
        ip, candidates = sources.top_source_ip(inc["type"])
        if not ip:
            self._log(inc, "containment", "skipped", "aucune IP source identifiée dans les journaux")
            return
        status, detail = actions.block_ip(ip)
        self._log(inc, "containment", status, f"{detail} (candidats: {candidates[:3]})")

    def _restart_and_verify(self, inc: dict) -> bool:
        """Redémarre les services cibles par paliers jusqu'à reprise vérifiée."""
        # Contrôle rapide : le service est-il déjà revenu ? (évite un redémarrage inutile)
        ok_health, _ = verify.health_ok()
        if ok_health and verify.test_transaction()[0]:
            self._log(inc, "verification", "ok", "service déjà rétabli, aucun redémarrage nécessaire")
            return True
        for svc in config.RESTART_TARGET.get(inc["type"], []):
            status, d = actions.restart_service(svc)
            self._log(inc, "restart", status, d)
            if status != "ok":
                continue
            time.sleep(config.VERIFY["after_restart_wait_s"])
            ok, detail = verify.verify_recovery()
            self._log(inc, "verification", "ok" if ok else "failed", json.dumps(detail, ensure_ascii=False))
            if ok:
                return True
        return False

    def _run(self, inc: dict) -> dict:
        kind = inc["kind"]

        # 1. Confinement systématique (sauf panne).
        self._contain(inc)

        # 2. Compromission : on confine, on NE déclare PAS résolu (analyse humaine).
        if kind == "compromise":
            return self._finish(inc, "contained",
                                "source confinée ; injection arrêtée au WAF. Analyse des journaux et "
                                "contrôle d'intégrité à réaliser par un humain (pas de reprise automatique).")

        # 3. Disponibilité : vérifier, redémarrer par paliers si besoin.
        if kind == "availability":
            if self._restart_and_verify(inc):
                return self._finish(inc, "resolved", "service rétabli et transaction de test réussie.")
            return self._finish(inc, "failed", "reprise non vérifiée : intervention humaine requise.")

        # 4. Abus / reconnaissance : confinement + vérification que le métier fonctionne toujours.
        ok, detail = verify.verify_recovery()
        self._log(inc, "verification", "ok" if ok else "failed", json.dumps(detail, ensure_ascii=False))
        note = ("source confinée ; le service de paiement fonctionne toujours."
                if ok else "source confinée ; vérification métier en échec, à surveiller.")
        return self._finish(inc, "contained", note)

    def recent(self, limit: int = 20) -> list:
        with self.lock:
            return self.incidents[-limit:][::-1]
