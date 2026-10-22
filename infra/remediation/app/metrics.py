from prometheus_client import Counter, Gauge, Histogram

INCIDENTS = Counter("remediation_incidents_total", "Incidents traités", ["kind", "result"])
DURATION = Histogram(
    "remediation_duration_seconds", "Durée détection -> fin de remédiation", buckets=(5, 10, 20, 30, 45, 60, 90, 120, 300)
)
ACTIVE = Gauge("remediation_active_incidents", "Incidents en cours")
LAST_RECOVERY = Gauge("remediation_last_recovery_seconds", "Durée de la dernière reprise réussie")
SERVICE_UP = Gauge("resilience_service_up", "État vérifié par l'orchestrateur (1 = rétabli)", ["service"])
BLOCKED = Gauge("remediation_blocked_ips", "Nombre d'IP bloquées")
