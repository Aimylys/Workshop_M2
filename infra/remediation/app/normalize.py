"""Transforme les différents formats d'alerte en incidents unifiés.
Formats acceptés :
  - Alertmanager : {"alerts": [{"status": "firing", "labels": {"alertname": ..., "job": ...}}]}
  - ML / SIEM    : {"type": "ml_anomaly", "service": "api", "source_ip": "...", "score": 0.9}
"""
import ipaddress


def _ip(value):
    try:
        return str(ipaddress.ip_address(str(value).strip()))
    except Exception:  # noqa: BLE001
        return None


def _incident(cfg, name, service, source_ip, source, score=None):
    service = cfg.get("job_to_service", {}).get(service, service) or cfg["default_target"]
    return {
        "name": name,
        "kind": cfg["incident_types"].get(name, cfg.get("default_kind", "degradation")),
        "service": service,
        "source_ip": _ip(source_ip) if source_ip else None,
        "source": source,
        "score": score,
    }


def normalize(cfg: dict, payload: dict) -> list:
    out = []
    if isinstance(payload.get("alerts"), list):  # Alertmanager
        for a in payload["alerts"]:
            if a.get("status") != "firing":
                continue
            lab = a.get("labels", {})
            out.append(
                _incident(cfg, lab.get("alertname", "unknown"), lab.get("service") or lab.get("job"),
                          lab.get("source_ip"), "alertmanager")
            )
    else:  # ML / SIEM
        out.append(
            _incident(cfg, payload.get("type", "unknown"), payload.get("service"),
                      payload.get("source_ip"), payload.get("origin", "ml"), payload.get("score"))
        )
    return out
