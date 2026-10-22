"""Indexation : construit le modèle de détection à partir du dataset étiqueté, et exporte les
profils de KPI (pour l'explication et pour la base de connaissance du RAG).

    python -m detection.index build      --dataset data/collector/dataset.csv
    python -m detection.index evaluate   --dataset data/collector/dataset.csv

« evaluate » mesure honnêtement la détection : on entraîne sur certains ÉPISODES et on teste sur
d'autres, jamais vus (séparation par épisode = pas de fuite entre lignes voisines d'une même
attaque).
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np

from .features import EPISODE_COL, LABEL_COL, FEATURES, load_dataset, to_matrix
from .model import DetectionModel
from .profiles import compute_profiles, signature_sentence

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "detection" / "models" / "detector.joblib"
PROFILES_JSON = ROOT / "detection" / "models" / "profiles.json"
KNOWLEDGE_MD = ROOT / "assistant" / "knowledge" / "profiles.md"


def build(args) -> None:
    df = load_dataset(args.dataset)
    X, y = to_matrix(df), df[LABEL_COL].to_numpy()
    counts = Counter(y)
    print(f"{len(df)} lignes, {len(counts)} états : " +
          ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    model = DetectionModel.fit(X, y, k=args.k)
    model.save(args.model)
    print(f"modèle enregistré -> {args.model} (k={min(args.k, len(df))}, "
          f"seuil inconnu={model.distance_cutoff:.2f})")

    profiles = compute_profiles(df)
    PROFILES_JSON.parent.mkdir(parents=True, exist_ok=True)
    PROFILES_JSON.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")
    write_knowledge(profiles)
    print(f"profils -> {PROFILES_JSON}\nconnaissance RAG -> {KNOWLEDGE_MD}")
    for label, prof in profiles.items():
        print(f"  {label:14s} {signature_sentence(label, prof)}")


def write_knowledge(profiles: dict) -> None:
    """Fiche texte par état (signature chiffrée observée) pour l'index RAG."""
    KNOWLEDGE_MD.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Profils de KPI observés par état\n",
             "_Généré par `detection.index` à partir du jeu de données réel. "
             "Chaque fiche décrit la signature mesurée d'un état._\n"]
    for label, prof in profiles.items():
        lines.append(f"\n## État : {label}\n")
        lines.append(f"- Mesures : {prof['count']}")
        lines.append(f"- Signature : {signature_sentence(label, prof)}")
        if prof["signature"]:
            lines.append("- KPI déclencheurs (écart à la normale) :")
            for kpi, z, sens in prof["signature"]:
                stat = prof["kpis"][kpi]
                lines.append(f"  - `{kpi}` en {sens} (≈{abs(z):.0f}σ) : "
                             f"médiane {stat['median']:.3g} (normal ≈ voir état normal)")
        key = ("req_per_sec", "login_fail_per_sec", "waf_blocked_per_sec", "waf_404_per_sec",
               "tx_ok_per_sec", "api_up", "latency_p95_payment_seconds", "edge_conn_per_sec")
        lines.append("- Repères : " + ", ".join(
            f"{k}≈{prof['kpis'][k]['median']:.3g}" for k in key if k in prof["kpis"]))
    KNOWLEDGE_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def evaluate(args) -> None:
    from sklearn.metrics import classification_report, confusion_matrix

    df = load_dataset(args.dataset)
    episodes = sorted(df[EPISODE_COL].unique())
    if len(episodes) < 2:
        raise SystemExit("évaluation impossible : il faut au moins 2 épisodes "
                         "(relancer une collecte avec plusieurs passages, --repeat).")
    y_true, y_pred = [], []
    for test_ep in episodes:
        train = df[df[EPISODE_COL] != test_ep]
        test = df[df[EPISODE_COL] == test_ep]
        if train[LABEL_COL].nunique() < 2:
            continue
        model = DetectionModel.fit(to_matrix(train), train[LABEL_COL].to_numpy(), k=args.k)
        for vec, truth in zip(to_matrix(test), test[LABEL_COL].to_numpy()):
            y_pred.append(model.predict(vec.reshape(1, -1)).label)
            y_true.append(truth)
    labels = sorted(set(y_true) | set(y_pred))
    print("Évaluation par épisode (train sur les autres épisodes, test sur chacun) :\n")
    print(classification_report(y_true, y_pred, labels=labels, zero_division=0))
    print("Matrice de confusion (lignes = vrai, colonnes = prédit) :")
    print("            " + "  ".join(f"{l[:7]:>7s}" for l in labels))
    for row, l in zip(confusion_matrix(y_true, y_pred, labels=labels), labels):
        print(f"{l[:11]:11s} " + "  ".join(f"{n:7d}" for n in row))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("mode", choices=["build", "evaluate"])
    p.add_argument("--dataset", default=str(ROOT / "data" / "collector" / "dataset.csv"))
    p.add_argument("--model", default=str(MODEL_PATH))
    p.add_argument("--k", type=int, default=15)
    args = p.parse_args()
    (build if args.mode == "build" else evaluate)(args)


if __name__ == "__main__":
    main()
