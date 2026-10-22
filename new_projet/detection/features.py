"""Préparation des vecteurs de KPI pour la détection.

Les KPI retenus sont ceux qui RÉAGISSENT à une attaque. On écarte volontairement les mesures
propres à la machine (mémoire, CPU de la VM Docker entière) : elles dépendent du poste et ne se
généralisent pas d'un environnement à l'autre.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# KPI utilisés pour décider (colonnes du dataset, sans le préfixe « kpi: »).
FEATURES = [
    "req_per_sec", "err_4xx_per_sec", "err_5xx_per_sec", "inprogress",
    "latency_p95_payment_seconds", "latency_p95_login_seconds",
    "login_ok_per_sec", "login_fail_per_sec",
    "tx_ok_per_sec", "tx_failed_per_sec", "db_errors_per_sec", "api_up",
    "edge_req_per_sec", "edge_connections", "edge_conn_per_sec",
    "waf_blocked_per_sec", "waf_404_per_sec", "api_cpu_cores",
]

LABEL_COL, EPISODE_COL = "label", "episode"


def load_dataset(path) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [c for c in FEATURES + [LABEL_COL, EPISODE_COL] if c not in df.columns]
    if missing:
        raise ValueError(f"colonnes absentes du dataset : {missing}")
    return df


def to_matrix(df: pd.DataFrame) -> np.ndarray:
    """Vecteurs de features. Une cellule vide = aucune mesure (ex. latence sans trafic) -> 0 :
    pour un instantané de détection, « pas de requête » équivaut à un débit nul."""
    return df[FEATURES].apply(pd.to_numeric, errors="coerce").fillna(0.0).to_numpy(dtype=float)


def vector_from_kpis(kpis: dict[str, float | None]) -> np.ndarray:
    """Instantané Prometheus {« kpi:req_per_sec »: ...} -> vecteur dans l'ordre de FEATURES."""
    row = [kpis.get(f"kpi:{name}") for name in FEATURES]
    return np.array([0.0 if v is None else float(v) for v in row], dtype=float).reshape(1, -1)
