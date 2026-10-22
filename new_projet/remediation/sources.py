"""Identification de l'IP source d'une attaque à partir des journaux (Loki).

Les KPI sont agrégés (sans IP) : pour bloquer la bonne adresse, on interroge Loki pour trouver,
sur une courte fenêtre, l'IP la plus active correspondant au type d'attaque.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from . import config

# LogQL par type : compte par IP les lignes caractéristiques de l'attaque sur la fenêtre.
_QUERIES = {
    "ddos":        '{service="waf", event="waf_access"}',
    "port_scan":   '{service="waf", event="waf_access"} |= "\\"status\\":404"',
    "sql_injection": '{service="waf", event="waf_access"} |= "\\"status\\":403"',
    "brute_force": '{service="auth", event="login"} | json | result != "success"',
}


def _topk_ip(logql: str, window: str = "2m", timeout: float = 5.0) -> list[tuple[str, int]]:
    query = f'topk(5, sum by (ip) (count_over_time({logql} | json [{window}])))'
    url = f"{config.LOKI_URL}/loki/api/v1/query?" + urllib.parse.urlencode({"query": query})
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.load(r)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for item in data.get("data", {}).get("result", []):
        ip = item.get("metric", {}).get("ip")
        try:
            count = int(float(item["value"][1]))
        except (KeyError, IndexError, ValueError):
            count = 0
        if ip and ip != "-":
            out.append((ip, count))
    return sorted(out, key=lambda t: t[1], reverse=True)


def top_source_ip(attack_type: str, window: str = "2m") -> tuple[str | None, list]:
    """IP la plus active pour ce type d'attaque, et le détail des candidats."""
    logql = _QUERIES.get(attack_type)
    if logql is None:
        return None, []
    candidates = _topk_ip(logql, window)
    return (candidates[0][0] if candidates else None), candidates
