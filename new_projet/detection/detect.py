"""Détection en direct : lit les KPI courants dans Prometheus et rend un verdict.

    python -m detection.detect --once          # un verdict puis sortie
    python -m detection.detect --interval 5    # en continu

Le verdict (type d'attaque + confiance + KPI déclencheurs) est la SOURCE DE DÉCISION : c'est lui
qui, en phase 7, déclenchera la remédiation. L'assistant RAG ne fait qu'expliquer ce verdict.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from data.collector.kpis import Prometheus, PrometheusError, kpi_names

from .features import vector_from_kpis
from .model import DetectionModel, Verdict

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "detection" / "models" / "detector.joblib"


class Detector:
    # Délai généreux : pendant une attaque (ex. force brute), la VM Docker est très chargée et
    # Prometheus répond plus lentement. Un délai trop court ferait croire à tort qu'il est absent
    # au moment précis où l'on veut voir l'attaque.
    def __init__(self, model_path=MODEL_PATH, prom_url="http://127.0.0.1:9090", timeout=10.0):
        self.model = DetectionModel.load(model_path)
        self.prom = Prometheus(prom_url, timeout=timeout)
        self.kpi_names = kpi_names()

    def current(self) -> tuple[Verdict, dict]:
        """Verdict sur l'instantané courant. Lève PrometheusError si Prometheus est injoignable."""
        self.prom.check_ready()
        kpis = self.prom.snapshot(self.kpi_names)
        verdict = self.model.predict(vector_from_kpis(kpis))
        return verdict, kpis


def _print(verdict: Verdict) -> None:
    t = time.strftime("%H:%M:%S")
    flag = "ATTAQUE" if verdict.is_attack else "—"
    print(f"[{t}] {verdict.label.upper():13s} conf={verdict.confidence:.0%} "
          f"dist={verdict.distance:.2f}  {flag}")
    if verdict.triggers:
        print("          déclencheurs : " +
              ", ".join(f"{k}={v} ({z:+.0f}σ)" for k, v, z in verdict.triggers))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--model", default=str(MODEL_PATH))
    p.add_argument("--prom", default="http://127.0.0.1:9090")
    p.add_argument("--interval", type=int, default=5)
    p.add_argument("--once", action="store_true")
    p.add_argument("--json", action="store_true", help="sortie JSON (une ligne par verdict)")
    args = p.parse_args()

    detector = Detector(args.model, args.prom)
    print(f"Détecteur prêt (états connus : {sorted(set(detector.model.labels))}).")
    try:
        while True:
            try:
                verdict, kpis = detector.current()
            except PrometheusError as exc:
                print(f"  ! {exc}")
            else:
                if args.json:
                    print(json.dumps(verdict.to_dict(), ensure_ascii=False))
                else:
                    _print(verdict)
            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nDétecteur arrêté.")


if __name__ == "__main__":
    main()
