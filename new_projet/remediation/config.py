"""Configuration de la remédiation : cibles autorisées, actions par type, seuils.

Tout est explicite et borné : aucune action n'est possible hors de ce qui est déclaré ici.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = str(ROOT / "deploy" / "docker-compose.yml")
JOURNAL = ROOT / "remediation" / "journal" / "actions.jsonl"

PROM_URL = "http://127.0.0.1:9090"
LOKI_URL = "http://127.0.0.1:3100"
BASE_URL = "http://127.0.0.1:8088"          # point d'entrée (le WAF)
CONSOLE_URL = "http://127.0.0.1:8060"       # console (pilote les attaques du harnais de test)

# --- Confinement « labo fermé » ---
# En production, une attaque réseau est bloquée par son IP au WAF (ci-dessous). Mais dans le labo
# fermé, l'attaque part de notre PROPRE harnais de test : son IP source est la passerelle Docker
# locale, donc protégée (never_block) et jamais bloquée. On la stoppe alors à la SOURCE, via la
# console (seuls ces profils prédéfinis, jamais une action arbitraire).
LAB_STOP_PATTERNS = ("ddos", "brute_force", "sql_injection", "port_scan")

# --- Blocage d'IP (liste lue par le WAF, rechargée à chaud) ---
WAF_SERVICE = "waf"
BLOCKLIST_IN_WAF = "/etc/modsecurity.d/blocklist/blocked_ips.txt"
MAX_BLOCKED = 100
# Jamais bloquées : boucle locale, passerelles Docker (par où passe la vérification), hôte.
NEVER_BLOCK_CIDRS = ["127.0.0.0/8", "::1/128", "172.16.0.0/12", "192.168.137.1/32"]

# --- Redémarrage : SEULS ces services peuvent être redémarrés ---
RESTARTABLE = ("db", "payment-api", "auth", "frontend", "waf")

# --- Correspondance type d'attaque -> nature de l'incident ---
#   availability : service indisponible/dégradé  -> on peut déclarer « résolu » après vérif
#   abuse        : abus applicatif (force brute)  -> confinement + vérif
#   recon        : reconnaissance                 -> confinement, pas de redémarrage
#   compromise   : compromission (injection)      -> CONFINEMENT uniquement, jamais « résolu »
#                                                     automatiquement (analyse humaine requise)
KIND = {
    "ddos": "availability",
    "brute_force": "abuse",
    "port_scan": "recon",
    "sql_injection": "compromise",
    "service_down": "availability",
}

# Service visé par un redémarrage selon le type (availability uniquement).
# service_down = la base ; un DDoS persistant = l'API.
RESTART_TARGET = {"service_down": ["db", "payment-api"], "ddos": ["payment-api"]}

# --- Anti-boucle et anti-rebond ---
DEBOUNCE = 2          # nb de détections consécutives du même type avant d'agir
COOLDOWN_S = 90       # délai minimal entre deux remédiations du même type
CONF_MIN = 0.6        # confiance minimale du verdict pour agir

# --- Vérification de la reprise ---
VERIFY = {
    "health_paths": ["/api/pay/health", "/api/auth/health"],
    "http_timeout_s": 5,
    "after_restart_wait_s": 8,      # laisser le service repartir avant de vérifier
    "retries": 6,                    # ré-essais de la vérification (à retries intervalle)
    "retry_interval_s": 3,
    # Transaction de test (preuve de reprise métier) : le compte technique « probe »
    # vire 0,01 € vers le compte de collecte « bank ». Réussite = service réellement rétabli.
    "login_path": "/api/auth/login",
    "tx_path": "/api/pay/transactions",
    "probe_user": "probe",
    "probe_secret_file": str(ROOT / "deploy" / "secrets" / "probe_password"),
    "tx_source": 4,
    "tx_dest": 5,
    "tx_amount": "0.01",
}
