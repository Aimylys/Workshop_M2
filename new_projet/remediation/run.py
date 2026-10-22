"""Boucle de remédiation : interroge le détecteur et déclenche l'action quand une attaque se
confirme. C'est le pont détection -> remédiation (sans intervention humaine).

    python -m remediation.run                 # écoute en continu
    python -m remediation.run --once          # un seul cycle (test)

Anti-rebond : on n'agit que lorsque le MÊME type d'attaque est détecté DEBOUNCE fois de suite,
pour ne pas réagir à un pic isolé.
"""
from __future__ import annotations

import argparse
import time

from detection.detect import Detector
from data.collector.kpis import PrometheusError

from . import config
from .engine import RemediationEngine


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--prom", default=config.PROM_URL)
    p.add_argument("--interval", type=int, default=4)
    p.add_argument("--debounce", type=int, default=config.DEBOUNCE)
    p.add_argument("--once", action="store_true")
    args = p.parse_args()

    detector = Detector(prom_url=args.prom)
    engine = RemediationEngine()
    print(f"Remédiation active. États remédiables : {sorted(config.KIND)}. Ctrl+C pour arrêter.",
          flush=True)

    last_label, streak = None, 0
    try:
        while True:
            try:
                verdict, _ = detector.current()
            except PrometheusError as exc:
                print(f"  ! {exc}", flush=True)
                if args.once:
                    break
                time.sleep(args.interval)
                continue

            label, conf = verdict.label, verdict.confidence
            streak = streak + 1 if label == last_label else 1
            last_label = label

            flag = "ATTAQUE" if verdict.is_attack else "—"
            print(f"[{time.strftime('%H:%M:%S')}] {label:13s} conf={conf:.0%} x{streak}  {flag}", flush=True)

            if verdict.is_attack and streak >= args.debounce:
                inc = engine.handle(label, conf, verdict.triggers)
                if inc:
                    print(f"  => incident {inc['id']} : {inc['status']} — {inc.get('note','')}", flush=True)

            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nRemédiation arrêtée.", flush=True)


if __name__ == "__main__":
    main()
