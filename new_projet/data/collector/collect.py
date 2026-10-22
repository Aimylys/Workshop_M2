"""Collecteur de KPI : Prometheus -> CSV étiqueté, pour entraîner la détection ML.

Une ligne toutes les --interval secondes : horodatage, tous les KPI « kpi:* », l'étiquette
courante (voir labels.py) et un numéro d'épisode (incrémenté à chaque changement
d'étiquette ; il sert à séparer entraînement et test par épisode, sans fuite).

Garanties :
  - Prometheus injoignable : AUCUNE ligne n'est écrite (une ligne de zéros étiquetée
    « normal » ou « ddos » empoisonnerait le jeu de données) ; on réessaie au tick suivant.
  - KPI sans valeur (ex. latence quand aucune requête) : cellule vide, jamais un 0 inventé.
  - Étiquette inconnue dans label.txt : la ligne n'est pas écrite, avec un avertissement.
  - Fichier existant avec d'autres colonnes : refus explicite (pas de mélange de schémas).

Usage :
    python data/collector/collect.py                              # collecte en continu
    python data/collector/collect.py --out data/collector/dataset.csv --interval 5
    python data/collector/collect.py export --minutes 30 --label normal --out data/collector/dataset_normal.csv
"""
import argparse
import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from .kpis import LABELS, Prometheus, PrometheusError, column, kpi_names
    from .labels import LABEL_FILE, read_label
except ImportError:          # exécuté comme script
    from kpis import LABELS, Prometheus, PrometheusError, column, kpi_names
    from labels import LABEL_FILE, read_label

HERE = Path(__file__).resolve().parent


def header(names: list[str]) -> list[str]:
    return ["timestamp", "iso_time"] + [column(n) for n in names] + ["label", "episode"]


def fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.6g}"


def row(ts: float, values: dict, names: list[str], label: str, episode: int) -> list:
    iso = datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")
    return [int(ts), iso] + [fmt(values[n]) for n in names] + [label, episode]


def open_dataset(path: Path, names: list[str]):
    """Ouvre le CSV en ajout. Renvoie (fichier, writer, dernier_épisode, dernière_étiquette)."""
    expected = header(names)
    last_episode, last_label = 0, None
    if path.exists() and path.stat().st_size > 0:
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            existing = next(reader)
            if existing != expected:
                sys.exit(f"{path} a d'autres colonnes que les KPI actuels : utilisez un autre --out.\n"
                         f"  fichier : {existing}\n  attendu : {expected}")
            for line in reader:
                if line:
                    last_label, last_episode = line[-2], int(line[-1])
    f = path.open("a", newline="", encoding="utf-8")
    writer = csv.writer(f)
    if last_label is None:
        writer.writerow(expected)
    return f, writer, last_episode, last_label


def collect(args) -> None:
    names = kpi_names()
    prom = Prometheus(args.prom)
    path = Path(args.out)
    f, writer, episode, previous = open_dataset(path, names)
    print(f"Collecte de {len(names)} KPI -> {path} (toutes les {args.interval} s). Ctrl+C pour arrêter.")
    print(f"Étiquette pilotée par {args.label_file} (python data/collector/labels.py <état>)")
    written = 0
    last_evaluated = None
    try:
        while True:
            # Ticks alignés sur l'horloge (…:00, :05, :10…) : pas de dérive au fil des heures.
            next_tick = (time.time() // args.interval + 1) * args.interval
            time.sleep(max(0.0, next_tick - time.time()))
            label = read_label(Path(args.label_file))
            if label not in LABELS:
                print(f"  ! étiquette inconnue « {label} » dans {args.label_file} : ligne ignorée "
                      f"(valeurs possibles : {', '.join(LABELS)})")
                continue
            try:
                prom.check_ready()
                evaluated = prom.evaluated_at()
                if evaluated is not None and evaluated == last_evaluated:
                    time.sleep(1.0)                 # calcul des règles pas encore passé : on attend
                    evaluated = prom.evaluated_at()
                if evaluated is not None and evaluated == last_evaluated:
                    print("  ! KPI non recalculés depuis la dernière ligne : ligne ignorée (pas de doublon)")
                    continue
                values = prom.snapshot(names)
            except PrometheusError as exc:
                print(f"  ! {exc} — aucune ligne écrite, nouvel essai dans {args.interval} s")
                continue
            last_evaluated = evaluated
            if label != previous:
                episode += 1
                print(f"  -- épisode {episode} : {label}")
                previous = label
            writer.writerow(row(next_tick, values, names, label, episode))
            f.flush()
            written += 1
            if written % args.print_every == 0:
                short = {k: values[f"kpi:{k}"] for k in ("req_per_sec", "login_fail_per_sec",
                                                         "tx_ok_per_sec", "latency_p95_payment_seconds")
                         if f"kpi:{k}" in values}
                shown = "  ".join(f"{k}={fmt(v) or '-'}" for k, v in short.items())
                print(f"  {time.strftime('%H:%M:%S')}  {label:13s}  {shown}")
    except KeyboardInterrupt:
        print(f"\nCollecte arrêtée : {written} lignes ajoutées à {path}.")
    finally:
        f.close()


def export(args) -> None:
    """Reconstruit un CSV depuis l'historique de Prometheus, avec une étiquette unique."""
    if args.label not in LABELS:
        sys.exit(f"étiquette inconnue « {args.label} » ; valeurs possibles : {', '.join(LABELS)}")
    names = kpi_names()
    end = time.time() if args.end is None else args.end
    start = end - args.minutes * 60 if args.start is None else args.start
    try:
        rows = Prometheus(args.prom, timeout=30).history(names, start, end, args.interval)
    except PrometheusError as exc:
        sys.exit(str(exc))
    path = Path(args.out)
    f, writer, episode, _ = open_dataset(path, names)
    with f:
        for ts, values in rows.items():
            writer.writerow(row(ts, values, names, args.label, episode + 1))
    print(f"{len(rows)} lignes « {args.label} » ajoutées à {path} (épisode {episode + 1}).")


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)     # suivi visible même redirigé vers un fichier
    p = argparse.ArgumentParser(description="Collecteur de KPI Prometheus -> CSV étiqueté")
    p.add_argument("--prom", default="http://127.0.0.1:9090")
    p.add_argument("--out", default=str(HERE / "dataset.csv"))
    p.add_argument("--interval", type=int, default=5, help="secondes entre deux lignes")
    sub = p.add_subparsers(dest="mode")
    sub.add_parser("live", help="collecte en continu (mode par défaut)")
    ex = sub.add_parser("export", help="reconstruit un CSV depuis l'historique Prometheus")
    ex.add_argument("--label", required=True)
    ex.add_argument("--minutes", type=float, default=30, help="durée à exporter, jusqu'à maintenant")
    ex.add_argument("--start", type=float, help="début (horodatage Unix), prioritaire sur --minutes")
    ex.add_argument("--end", type=float, help="fin (horodatage Unix), maintenant par défaut")
    p.add_argument("--label-file", default=str(LABEL_FILE))
    p.add_argument("--print-every", type=int, default=6, help="afficher une ligne de suivi toutes les N lignes")
    args = p.parse_args()
    export(args) if args.mode == "export" else collect(args)


if __name__ == "__main__":
    main()
