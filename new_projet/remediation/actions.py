"""Actions correctives — UNIQUEMENT des opérations prédéfinies sur des cibles connues.

  - block_ip      : ajoute une IP à la liste de blocage du WAF et recharge le WAF à chaud.
  - restart_service : redémarre un conteneur d'une LISTE BLANCHE.

Aucune commande arbitraire : l'IP est validée (vraie adresse IP, hors never_block) et le service
doit appartenir à config.RESTARTABLE. La remédiation ne peut donc pas devenir elle-même une faille.
"""
from __future__ import annotations

import ipaddress
import json
import subprocess
import urllib.request

from . import config

_NEVER = [ipaddress.ip_network(c) for c in config.NEVER_BLOCK_CIDRS]


def _compose(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "compose", "-f", config.COMPOSE_FILE, *args],
                          capture_output=True, text=True, timeout=90)


def _is_never_block(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True          # entrée invalide : on refuse de l'utiliser
    return any(addr in net for net in _NEVER)


def list_blocked() -> list[str]:
    r = _compose("exec", "-T", config.WAF_SERVICE, "cat", config.BLOCKLIST_IN_WAF)
    if r.returncode != 0:
        return []
    return [ln.strip() for ln in r.stdout.splitlines()
            if ln.strip() and not ln.startswith("#")]


def block_ip(ip: str) -> tuple[str, str]:
    """Renvoie (statut, détail). statut ∈ {ok, skipped, failed}."""
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        return "failed", f"adresse invalide : {ip!r}"
    if _is_never_block(ip):
        return "skipped", f"{ip} protégée (never_block)"
    blocked = list_blocked()
    if ip in blocked:
        return "ok", f"{ip} déjà bloquée"
    if len(blocked) >= config.MAX_BLOCKED:
        return "failed", "liste de blocage pleine"
    # grep -qxF : correspondance de ligne exacte ; ip déjà validée comme vraie adresse.
    cmd = (f"grep -qxF '{ip}' {config.BLOCKLIST_IN_WAF} || "
           f"(echo '{ip}' >> {config.BLOCKLIST_IN_WAF} && nginx -s reload)")
    r = _compose("exec", "-T", config.WAF_SERVICE, "sh", "-c", cmd)
    if r.returncode != 0:
        return "failed", f"échec du blocage : {r.stderr.strip()[:200]}"
    return "ok", f"{ip} ajoutée à la liste de blocage du WAF (rechargé)"


def unblock_ip(ip: str) -> tuple[str, str]:
    """Retire une IP de la liste (utile pour réinitialiser après une démo)."""
    cmd = f"sed -i '\\#^{ip}$#d' {config.BLOCKLIST_IN_WAF} && nginx -s reload"
    r = _compose("exec", "-T", config.WAF_SERVICE, "sh", "-c", cmd)
    return ("ok", f"{ip} débloquée") if r.returncode == 0 else ("failed", r.stderr.strip()[:200])


def stop_local_attack(label: str) -> tuple[str, str]:
    """Labo fermé : arrête l'attaque à sa SOURCE via la console (l'« attaquant » est notre propre
    harnais de test). N'agit QUE sur un profil d'attaque prédéfini — jamais une cible arbitraire —
    et seulement sur la console locale. Idempotent : stopper une attaque déjà arrêtée renvoie ok."""
    if label not in config.LAB_STOP_PATTERNS:
        return "skipped", f"« {label} » n'est pas un profil d'attaque local"
    url = f"{config.CONSOLE_URL}/api/attacks/{label}/stop"
    try:
        req = urllib.request.Request(url, method="POST")
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.load(r)
    except Exception as exc:  # noqa: BLE001
        return "failed", f"console injoignable ({config.CONSOLE_URL}) : {type(exc).__name__}"
    if data.get("ok"):
        return "ok", f"attaque « {label} » stoppée à la source (harnais de test du labo)"
    return "failed", str(data.get("error", "réponse inattendue"))[:150]


def restart_service(name: str) -> tuple[str, str]:
    if name not in config.RESTARTABLE:
        return "failed", f"service « {name} » hors liste blanche"
    r = _compose("restart", name)
    if r.returncode != 0:
        return "failed", f"redémarrage impossible : {r.stderr.strip()[:200]}"
    return "ok", f"conteneur {name} redémarré"
