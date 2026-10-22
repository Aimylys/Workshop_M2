"""Session de collecte automatique (~20 min) : enchaîne normal + chaque profil d'attaque,
pilote l'étiquette, et lance le collecteur et le trafic normal. Produit un dataset.csv étiqueté.

    python -m labtest.collect_session
    python -m labtest.collect_session --out data/collector/dataset.csv --repeat 1

Sous le capot, pour une seule commande à lancer :
  - démarre le trafic normal (clients fictifs légitimes) ;
  - démarre le collecteur (Prometheus -> CSV) ;
  - déroule le planning : pour chaque état, pose l'étiquette, joue le profil, revient à « normal » ;
  - « service_down » = arrêt puis redémarrage du conteneur db (injection de panne sur NOTRE conteneur).

Tout vise 127.0.0.1 (garde-fou guard.ensure_local). Rien n'est lancé hors de l'environnement local.
"""
import argparse
import subprocess
import sys
import threading
import time
from pathlib import Path

from data.collector.labels import LABEL_FILE, write_label

from .guard import ensure_local_url
from .patterns import PATTERNS

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

# (étiquette, durée s, cooldown normal s). cooldown plus long après la panne (reprise de la base).
# Intensités douces (patterns en keep-alive) : ~15 min au total, sans saturer la VM 2 cœurs.
DEFAULT_PLAN = [
    ("ddos", 90, 60),
    ("brute_force", 90, 60),
    ("sql_injection", 90, 60),
    ("port_scan", 90, 60),
    ("service_down", 90, 120),
]
WARMUP = 120        # référence « normal » initiale


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def service_down(compose_file: str, duration: float) -> dict:
    """Injection de panne : arrête le conteneur db, attend, le redémarre (notre propre service)."""
    base = ["docker", "compose", "-f", compose_file]
    subprocess.run(base + ["stop", "db"], capture_output=True, check=True)
    time.sleep(duration)
    subprocess.run(base + ["start", "db"], capture_output=True, check=True)
    return {"pattern": "service_down", "stopped_s": duration}


def run_phase(label: str, duration: float, base_url: str, compose_file: str) -> None:
    write_label(label, LABEL_FILE)
    log(f"=== {label} ({duration:.0f} s) ===")
    if label == "service_down":
        summary = service_down(compose_file, duration)
    else:
        # brute_force vise « admin » (compte inexistant) : produit la signature d'échecs de
        # connexion sans verrouiller un compte client utilisé par le trafic normal.
        summary = PATTERNS[label](base_url, duration)
    log(f"    {summary}")


def normal_phase(duration: float) -> None:
    write_label("normal", LABEL_FILE)
    log(f"--- normal ({duration:.0f} s) ---")
    time.sleep(duration)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--base", default="http://127.0.0.1:8088")
    p.add_argument("--out", default=str(ROOT / "data" / "collector" / "dataset.csv"))
    p.add_argument("--compose", default=str(ROOT / "deploy" / "docker-compose.yml"))
    p.add_argument("--prom", default="http://127.0.0.1:9090")
    p.add_argument("--repeat", type=int, default=1, help="nombre de passages sur le planning")
    p.add_argument("--users", type=int, default=6, help="clients du trafic normal")
    p.add_argument("--no-traffic", action="store_true", help="ne pas lancer le trafic normal (déjà en cours)")
    args = p.parse_args()
    ensure_local_url(args.base)

    procs = []
    if not args.no_traffic:
        procs.append(subprocess.Popen(
            [PY, str(ROOT / "data" / "traffic" / "normal_traffic.py"),
             "--url", args.base, "--users", str(args.users)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        log(f"trafic normal démarré ({args.users} clients)")
    collector = subprocess.Popen(
        [PY, str(ROOT / "data" / "collector" / "collect.py"),
         "--prom", args.prom, "--out", args.out],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(collector)
    log(f"collecteur démarré -> {args.out}")

    total = WARMUP + args.repeat * sum(d + c for _, d, c in DEFAULT_PLAN)
    log(f"durée prévue ≈ {total // 60} min {total % 60} s. Ctrl+C pour arrêter proprement.")
    try:
        normal_phase(WARMUP)
        for lap in range(1, args.repeat + 1):
            if args.repeat > 1:
                log(f"***** passage {lap}/{args.repeat} *****")
            for label, duration, cooldown in DEFAULT_PLAN:
                run_phase(label, duration, args.base, args.compose)
                normal_phase(cooldown)
        write_label("normal", LABEL_FILE)
        log("planning terminé.")
    except KeyboardInterrupt:
        log("interruption : retour à « normal » et arrêt.")
        write_label("normal", LABEL_FILE)
    finally:
        time.sleep(3)
        for proc in procs:
            proc.terminate()
        log("trafic et collecteur arrêtés.")


if __name__ == "__main__":
    main()
