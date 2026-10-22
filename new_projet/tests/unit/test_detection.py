"""Tests du pipeline de détection sur un jeu de données synthétique (indépendant de la collecte)."""
import numpy as np
import pandas as pd
import pytest

from detection import features, profiles
from detection.model import DetectionModel


def _synthetic(rng, n=60):
    """Trois états bien séparés : normal, ddos (req/s et inprogress ↑), brute_force (login_fail ↑)."""
    rows = []
    for ep, (label, over) in enumerate([
        ("normal", {}),
        ("ddos", {"req_per_sec": 90, "inprogress": 60, "edge_req_per_sec": 95}),
        ("brute_force", {"login_fail_per_sec": 25, "latency_p95_login_seconds": 3}),
    ], start=1):
        for _ in range(n):
            row = {f: abs(rng.normal(2, 0.5)) for f in features.FEATURES}
            row["api_up"] = 1.0
            row.update({k: v + rng.normal(0, v * 0.1) for k, v in over.items()})
            row["label"], row["episode"] = label, ep
            rows.append(row)
    return pd.DataFrame(rows)


def _snapshot(**over):
    """Instantané complet (tous les KPI présents, comme Prometheus) : base 2.0 + écarts."""
    kpis = {f"kpi:{f}": 2.0 for f in features.FEATURES}
    kpis["kpi:api_up"] = 1.0
    for k, v in over.items():
        kpis[f"kpi:{k}"] = v
    return features.vector_from_kpis(kpis)


def test_fit_predict_separates_states():
    df = _synthetic(np.random.default_rng(0))
    model = DetectionModel.fit(features.to_matrix(df), df["label"].to_numpy(), k=15)

    v = model.predict(_snapshot(req_per_sec=92, inprogress=61, edge_req_per_sec=96))
    assert v.label == "ddos" and v.is_attack and v.confidence > 0.6
    assert any(k == "req_per_sec" for k, _, _ in v.triggers)

    assert model.predict(_snapshot()).label == "normal"


def test_far_sample_is_unknown():
    df = _synthetic(np.random.default_rng(1))
    model = DetectionModel.fit(features.to_matrix(df), df["label"].to_numpy(), k=15)
    weird = np.full((1, len(features.FEATURES)), 5000.0)
    assert model.predict(weird).label == "inconnu"


def test_profiles_signature_points_to_right_kpis():
    df = _synthetic(np.random.default_rng(2))
    profs = profiles.compute_profiles(df)
    assert set(profs) == {"normal", "ddos", "brute_force"}
    ddos_sig = {kpi for kpi, _, _ in profs["ddos"]["signature"]}
    assert "req_per_sec" in ddos_sig or "edge_req_per_sec" in ddos_sig
    assert any("login_fail" in kpi for kpi, _, _ in profs["brute_force"]["signature"])


def test_save_load_roundtrip(tmp_path):
    df = _synthetic(np.random.default_rng(3))
    model = DetectionModel.fit(features.to_matrix(df), df["label"].to_numpy(), k=10)
    path = tmp_path / "m.joblib"
    model.save(path)
    reloaded = DetectionModel.load(path)
    sample = _snapshot(login_fail_per_sec=26, latency_p95_login_seconds=3)
    assert reloaded.predict(sample).label == model.predict(sample).label == "brute_force"


def test_missing_kpi_becomes_zero():
    vec = features.vector_from_kpis({"kpi:req_per_sec": 5.0, "kpi:latency_p95_payment_seconds": None})
    assert vec.shape == (1, len(features.FEATURES))
    assert vec[0][features.FEATURES.index("req_per_sec")] == 5.0
    assert vec[0][features.FEATURES.index("inprogress")] == 0.0
