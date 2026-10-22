"""Profils statistiques par état et KPI « significatifs » de chaque attaque.

Pour chaque étiquette, on résume chaque KPI (moyenne, écart-type, médiane, min, max) et on
mesure de combien il s'écarte de l'état « normal » (z-score robuste). Les KPI les plus
écartés sont la SIGNATURE de l'attaque. Ces profils servent à deux choses :
  - rendre la détection explicable (quels KPI ont déclenché le verdict) ;
  - construire la base de connaissance indexée par le RAG (phase 5).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .features import FEATURES, LABEL_COL

NORMAL = "normal"


def _robust_scale(normal: pd.Series) -> tuple[float, float]:
    """Centre et échelle robustes de l'état normal (médiane, écart absolu médian)."""
    med = float(normal.median())
    mad = float((normal - med).abs().median())
    scale = mad * 1.4826 if mad > 0 else (float(normal.std()) or 1.0)
    return med, (scale or 1.0)


def compute_profiles(df: pd.DataFrame) -> dict:
    """Renvoie {label: {"count", "kpis": {kpi: stats}, "signature": [(kpi, z, sens)]}}."""
    numeric = df[FEATURES].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    data = pd.concat([numeric, df[[LABEL_COL]]], axis=1)
    baselines = {kpi: _robust_scale(data.loc[data[LABEL_COL] == NORMAL, kpi])
                 for kpi in FEATURES} if (data[LABEL_COL] == NORMAL).any() else {}

    profiles = {}
    for label, group in data.groupby(LABEL_COL):
        kpis = {}
        signature = []
        for kpi in FEATURES:
            col = group[kpi]
            stats = {"mean": float(col.mean()), "std": float(col.std() or 0.0),
                     "median": float(col.median()), "min": float(col.min()), "max": float(col.max())}
            kpis[kpi] = stats
            if label != NORMAL and kpi in baselines:
                med, scale = baselines[kpi]
                z = (stats["median"] - med) / scale
                if abs(z) >= 3:                       # écart net par rapport au normal
                    signature.append((kpi, round(z, 1), "hausse" if z > 0 else "baisse"))
        signature.sort(key=lambda t: abs(t[1]), reverse=True)
        profiles[label] = {"count": int(len(group)), "kpis": kpis, "signature": signature[:6]}
    return profiles


def signature_sentence(label: str, profile: dict) -> str:
    """Phrase lisible résumant la signature d'un état (pour la base de connaissance RAG)."""
    if label == NORMAL:
        return "Trafic normal : indicateurs dans leurs plages habituelles."
    if not profile["signature"]:
        return f"État « {label} » : pas d'écart marqué mesuré sur cet échantillon."
    parts = [f"{kpi} en {sens} (≈{abs(z):.0f}σ)" for kpi, z, sens in profile["signature"]]
    return f"État « {label} » reconnaissable à : " + ", ".join(parts) + "."
