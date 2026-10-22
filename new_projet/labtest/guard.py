"""Garde-fou : le harnais de test ne vise que l'environnement local du laboratoire.

Autorisé par défaut : boucle locale (127.0.0.0/8, ::1, localhost) et le sous-réseau du point
d'accès du consortium (192.168.137.0/24, hôte = 192.168.137.1).

Pour lancer les attaques DEPUIS UN AUTRE PC vers l'hôte, on désigne explicitement la ou les
cibles autorisées via la variable d'environnement LABTEST_ALLOW (IP ou CIDR, séparées par des
virgules), par exemple :  LABTEST_ALLOW=192.168.43.5
C'est une autorisation VOLONTAIRE et nominative : le défaut reste local-only, et l'Internet
public est toujours refusé.
"""
import ipaddress
import os
import socket
from urllib.parse import urlparse

BASE_NETWORKS = (ipaddress.ip_network("192.168.137.0/24"),)   # point d'accès Windows du sujet


class TargetRefused(RuntimeError):
    """Cible hors de l'environnement de laboratoire autorisé."""


def _allowed_networks() -> list:
    nets = list(BASE_NETWORKS)
    for item in os.getenv("LABTEST_ALLOW", "").replace(";", ",").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            nets.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            pass        # entrée invalide ignorée (le défaut reste sûr)
    return nets


def _is_allowed(host: str) -> bool:
    if host.lower() in ("localhost", ""):
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        # Nom d'hôte : on résout et on exige que TOUTES les adresses soient autorisées.
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror:
            return False
        return all(_is_allowed(info[4][0]) for info in infos)
    if addr.is_loopback:
        return True
    return any(addr in net for net in _allowed_networks())


def ensure_local(host: str) -> str:
    """Renvoie l'hôte s'il est autorisé ; lève TargetRefused sinon."""
    if not _is_allowed(host):
        allow = os.getenv("LABTEST_ALLOW", "") or "(aucune)"
        raise TargetRefused(
            f"cible « {host} » refusée : autorisés = 127.0.0.1, 192.168.137.0/24 et "
            f"LABTEST_ALLOW={allow}. Pour viser l'hôte depuis un autre PC, définir "
            f"LABTEST_ALLOW avec son IP (ex. LABTEST_ALLOW=192.168.43.5).")
    return host


def ensure_local_url(url: str) -> str:
    ensure_local(urlparse(url).hostname or "")
    return url
