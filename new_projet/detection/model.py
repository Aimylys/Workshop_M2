"""Le « modèle » de détection : standardisation + k plus proches voisins sur les KPI étiquetés.

NearestNeighbors ne fait pas d'apprentissage au sens d'un réseau entraîné : il mémorise les
exemples étiquetés. La décision est le vote majoritaire des k voisins les plus proches de
l'instantané courant. On y ajoute un seuil de distance : un état trop éloigné de tout ce qui a
été observé est signalé « inconnu » plutôt que classé de force.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

import joblib
import numpy as np
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

from .features import FEATURES


@dataclass
class Verdict:
    label: str
    confidence: float          # part des k voisins d'accord (0..1)
    distance: float            # distance moyenne aux voisins (sur KPI standardisés)
    is_attack: bool
    triggers: list             # KPI qui expliquent le verdict : [(kpi, valeur, écart_normal)]
    neighbors: dict            # répartition des votes {label: n}

    def to_dict(self) -> dict:
        return asdict(self)


class DetectionModel:
    def __init__(self, scaler, nn, labels, feature_names, distance_cutoff, normal_means):
        self.scaler = scaler
        self.nn = nn
        self.labels = np.asarray(labels)
        self.features = feature_names
        self.distance_cutoff = distance_cutoff
        self.normal_means = normal_means      # moyenne « normale » par KPI (pour les déclencheurs)

    # ---------- entraînement (mémorisation) ----------
    @classmethod
    def fit(cls, X: np.ndarray, y: np.ndarray, k: int = 15, cutoff_factor: float = 3.0) -> "DetectionModel":
        scaler = StandardScaler().fit(X)
        Xs = scaler.transform(X)
        k = min(k, len(X))
        nn = NearestNeighbors(n_neighbors=k).fit(Xs)
        # Seuil « inconnu » : un état n'est déclaré inconnu que s'il est TRÈS au-delà de la
        # dispersion observée (99e centile des distances intra-échantillon × cutoff_factor).
        # Facteur généreux : un faux « inconnu » empêcherait la remédiation de se déclencher,
        # ce qui est pire qu'une étiquette d'attaque légèrement imprécise.
        dists, _ = nn.kneighbors(Xs)
        cutoff = float(np.quantile(dists.mean(axis=1), 0.99) * cutoff_factor)
        normal_means = X[y == "normal"].mean(axis=0) if (y == "normal").any() else X.mean(axis=0)
        return cls(scaler, nn, y, list(FEATURES), cutoff, normal_means)

    # ---------- décision ----------
    def predict(self, x: np.ndarray) -> Verdict:
        xs = self.scaler.transform(x)
        dists, idx = self.nn.kneighbors(xs)
        votes_labels = self.labels[idx[0]]
        counts: dict[str, int] = {}
        for lab in votes_labels:
            counts[lab] = counts.get(lab, 0) + 1
        winner = max(counts, key=counts.get)
        confidence = counts[winner] / len(votes_labels)
        mean_dist = float(dists[0].mean())
        if mean_dist > self.distance_cutoff:
            winner, confidence = "inconnu", 0.0
        triggers = self._triggers(x[0]) if winner not in ("normal", "inconnu") else []
        return Verdict(label=winner, confidence=round(confidence, 2), distance=round(mean_dist, 2),
                       is_attack=winner not in ("normal", "inconnu"), triggers=triggers,
                       neighbors=counts)

    def _triggers(self, vec: np.ndarray, top: int = 4) -> list:
        """KPI qui s'écartent le plus de la normale (en nombre d'écarts-types), pour l'explication."""
        scale = self.scaler.scale_
        deviations = []
        for i, name in enumerate(self.features):
            z = (vec[i] - self.normal_means[i]) / (scale[i] or 1.0)
            if abs(z) >= 2:
                deviations.append((name, round(float(vec[i]), 3), round(float(z), 1)))
        deviations.sort(key=lambda t: abs(t[2]), reverse=True)
        return deviations[:top]

    # ---------- persistance ----------
    def save(self, path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"scaler": self.scaler, "nn": self.nn, "labels": self.labels,
                     "features": self.features, "cutoff": self.distance_cutoff,
                     "normal_means": self.normal_means}, path)

    @classmethod
    def load(cls, path) -> "DetectionModel":
        d = joblib.load(path)
        return cls(d["scaler"], d["nn"], d["labels"], d["features"], d["cutoff"], d["normal_means"])
