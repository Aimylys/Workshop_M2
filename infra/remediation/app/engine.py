import json
import os
import threading
import time
from collections import deque

import httpx

from . import metrics
from .verify import docker_check, http_check, transaction_test


class Engine:
    def __init__(self, cfg, docker, http=None, clock=time.time, sleep=time.sleep):
        self.cfg = cfg
        self.docker = docker
        self.http = http or httpx.Client()
        self.clock, self.sleep = clock, sleep
        self.lock = threading.Lock()
        self.events = deque(maxlen=1000)
        self.incidents = {}
        self.active = {}
        self.cooldown = {}
        self.states = {}
        self._n = 0

    # ---------- journal ----------
    def _event(self, **kw):
        ev = {"ts": round(self.clock(), 3), **kw}
        with self.lock:
            self.events.append(ev)
        print(json.dumps({"level": "info", "service": "orchestrator", **ev}, ensure_ascii=False), flush=True)

    def _step(self, inc, step, status, detail=""):
        s = {"ts": round(self.clock(), 3), "step": step, "status": status, "detail": detail}
        inc["steps"].append(s)
        self._event(incident=inc["id"], **{k: v for k, v in s.items() if k != "ts"})

    # ---------- vérifications ----------
    def _check_service(self, name):
        """Retourne (ok, detail, present)."""
        svc = self.cfg["services"].get(name, {})
        st = self.docker.state(name)
        if not st.get("present"):
            return False, "non déployé", False
        ok, detail = True, []
        for c in svc.get("checks", ["docker"]):
            if c == "docker":
                o, d = docker_check(st)
            elif c == "http":
                o, d = http_check(self.http, svc["http"], self.cfg["verify"]["http_timeout_s"])
            else:
                continue
            ok = ok and o
            detail.append(d)
        return ok, ", ".join(detail), True

    def _check_all(self, target):
        v = self.cfg["verify"]
        names = [target] + [s for s in v.get("platform_services", []) if s != target]
        results, ok = {}, True
        for n in names:
            o, d, present = self._check_service(n)
            if not present and n != target and v.get("ignore_absent", True):
                continue
            results[n] = d
            ok = ok and o
        tx = v.get("transaction_test", {})
        business = None
        if ok and tx.get("enabled"):
            business, d = transaction_test(tx, self.http, v["http_timeout_s"] * 2)
            results["transaction_test"] = d
            ok = ok and business
        return ok, results, business

    def _verify(self, target, timeout):
        deadline = self.clock() + timeout
        while True:
            ok, results, business = self._check_all(target)
            if ok or self.clock() >= deadline:
                return ok, results, business
            self.sleep(self.cfg["poll_interval_s"])

    def refresh_states(self):
        for name in self.cfg["services"]:
            try:
                ok, detail, present = self._check_service(name)
            except Exception as e:  # noqa: BLE001
                ok, detail, present = False, type(e).__name__, False
            prev = self.states.get(name)
            since = prev["since"] if prev and prev["up"] == ok else round(self.clock(), 3)
            self.states[name] = {"up": ok, "present": present, "detail": detail, "since": since}
            metrics.SERVICE_UP.labels(service=name).set(1 if ok else 0)

    # ---------- confinement ----------
    def block_ip(self, ip):
        if ip in self.cfg.get("never_block", []):
            return "skipped", f"{ip} protégée (never_block)"
        path = self.cfg["blocklist_file"]
        try:
            lines = open(path).read().split() if os.path.exists(path) else []
            if ip in lines:
                return "ok", f"{ip} déjà bloquée"
            if len(lines) >= self.cfg.get("max_blocked", 50):
                return "failed", "liste de blocage pleine"
            with open(path, "a") as f:
                f.write(ip + "\n")
            metrics.BLOCKED.set(len(lines) + 1)
        except Exception as e:  # noqa: BLE001
            return "failed", f"écriture de la liste impossible : {type(e).__name__}"
        try:
            self.docker.signal(self.cfg["waf_service"], "HUP")
            return "ok", f"{ip} ajoutée à la liste, WAF rechargé"
        except Exception as e:  # noqa: BLE001
            return "failed", f"{ip} ajoutée à la liste, rechargement du WAF impossible : {e}"

    # ---------- cycle de vie d'un incident ----------
    def submit(self, inc_data, background=True):
        target = inc_data["service"]
        with self.lock:
            if target in self.active:
                reason = f"incident déjà en cours ({self.active[target]})"
            elif self.clock() < self.cooldown.get(target, 0):
                reason = "délai de repos après une remédiation (anti-boucle)"
            else:
                reason = None
                self._n += 1
                inc = {
                    "id": f"INC-{int(self.clock())}-{self._n}",
                    **inc_data,
                    "status": "running",
                    "started": round(self.clock(), 3),
                    "steps": [],
                }
                self.incidents[inc["id"]] = inc
                self.active[target] = inc["id"]
                metrics.ACTIVE.set(len(self.active))
        if reason:
            self._event(step="ignored", status="skipped", detail=f"{inc_data['name']} sur {target} : {reason}")
            return {"accepted": False, "reason": reason, "service": target}
        if background:
            threading.Thread(target=self._safe_run, args=(inc,), daemon=True).start()
        else:
            self._safe_run(inc)
        return {"accepted": True, "incident": inc["id"], "service": target}

    def _safe_run(self, inc):
        try:
            self.run(inc)
        except Exception as e:  # noqa: BLE001
            self._step(inc, "error", "failed", f"{type(e).__name__}: {e}")
            self._finish(inc, "failed", "erreur interne : intervention humaine requise")

    def _finish(self, inc, status, note, business=None):
        now = self.clock()
        inc.update(status=status, ended=round(now, 3), duration_s=round(now - inc["started"], 1), note=note,
                   business_verified=business)
        metrics.INCIDENTS.labels(kind=inc["kind"], result=status).inc()
        metrics.DURATION.observe(now - inc["started"])
        if status == "resolved":
            metrics.LAST_RECOVERY.set(now - inc["started"])
        with self.lock:
            self.active.pop(inc["service"], None)
            self.cooldown[inc["service"]] = now + self.cfg["cooldown_s"]
            metrics.ACTIVE.set(len(self.active))
        self._step(inc, "closed", status, note)

    def run(self, inc):
        v, kind, target = self.cfg["verify"], inc["kind"], inc["service"]
        self._step(inc, "detected", "ok", f"{inc['name']} ({kind}) sur {target}, source : {inc['source']}")

        # 1. Confinement
        if inc.get("source_ip") and kind in ("degradation", "anomaly", "compromise"):
            s, d = self.block_ip(inc["source_ip"])
            self._step(inc, "containment", s, d)

        # 2. Compromission : on confine, on ne déclare PAS le problème corrigé
        if kind == "compromise":
            ok, res, business = self._verify(target, v["initial_timeout_s"])
            self._step(inc, "verification", "ok" if ok else "failed", json.dumps(res, ensure_ascii=False))
            self._finish(inc, "contained",
                         "source confinée ; analyse des journaux, rotation des secrets et contrôle d'intégrité "
                         "à réaliser par un humain", business)
            return

        # 3. Le service est-il déjà revenu à la normale ? (évite un redémarrage inutile)
        ok, res, business = self._verify(target, v["initial_timeout_s"])
        self._step(inc, "verification", "ok" if ok else "failed", json.dumps(res, ensure_ascii=False))
        if ok:
            self._finish(inc, "resolved", "service rétabli sans redémarrage", business)
            return

        # 4. Redémarrage par paliers
        levels = self.cfg["services"].get(target, {}).get("escalation", [[target]])
        for i, chain in enumerate(levels, 1):
            self._step(inc, "remediation", "running", f"palier {i}/{len(levels)} : redémarrage de {chain}")
            failed = False
            for s in chain:
                try:
                    self.docker.restart(s)
                    self._step(inc, "restart", "ok", s)
                except Exception as e:  # noqa: BLE001
                    self._step(inc, "restart", "failed", f"{s} : {e}")
                    failed = True
                    break
            if failed:
                continue
            ok, res, business = self._verify(target, v["after_restart_timeout_s"])
            self._step(inc, "verification", "ok" if ok else "failed", json.dumps(res, ensure_ascii=False))
            if ok:
                self._finish(inc, "resolved", f"rétabli au palier {i}", business)
                return

        self._finish(inc, "failed", "tous les paliers ont échoué : intervention humaine requise")
