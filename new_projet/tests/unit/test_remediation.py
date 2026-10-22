"""Tests du moteur de remédiation (sans Docker ni console : actions simulées).

On vérifie la logique de décision et, surtout, le confinement « labo fermé » : quand l'IP source
ne peut pas être bloquée au WAF (source locale protégée), l'attaque doit être coupée à la source.
"""
import pytest

from remediation import config
from remediation.engine import RemediationEngine


@pytest.fixture
def engine(monkeypatch, tmp_path):
    # Journal dans un dossier temporaire (ne pas polluer le vrai journal).
    monkeypatch.setattr(config, "JOURNAL", tmp_path / "actions.jsonl")
    return RemediationEngine()


def test_should_act_refuse_type_inconnu(engine):
    assert engine.should_act("normal", 0.9) == (False, "type non remédiable")


def test_should_act_refuse_confiance_faible(engine):
    ok, reason = engine.should_act("ddos", 0.3)
    assert ok is False and "confiance" in reason


def test_lab_containment_quand_ip_non_bloquable(engine, monkeypatch):
    """Source locale (never_block) -> l'attaque est coupée à la source, pas au WAF."""
    import remediation.engine as eng
    # IP source = passerelle Docker protégée : le blocage WAF est « skipped ».
    monkeypatch.setattr(eng.sources, "top_source_ip", lambda t, **k: ("172.22.0.1", [("172.22.0.1", 99)]))
    monkeypatch.setattr(eng.actions, "block_ip", lambda ip: ("skipped", f"{ip} never_block"))
    stopped = []
    monkeypatch.setattr(eng.actions, "stop_local_attack", lambda label: (stopped.append(label), ("ok", "stoppée"))[1])

    inc = engine.handle("sql_injection", 0.9)
    assert stopped == ["sql_injection"]                      # attaque bien coupée à la source
    assert inc["status"] == "contained"
    steps = {s["step"]: s["status"] for s in inc["steps"]}
    assert steps["lab-containment"] == "ok"


def test_pas_de_lab_stop_si_ip_externe_bloquee(engine, monkeypatch):
    """IP externe réellement bloquée au WAF -> pas besoin de couper à la source."""
    import remediation.engine as eng
    monkeypatch.setattr(eng.sources, "top_source_ip", lambda t, **k: ("203.0.113.9", [("203.0.113.9", 50)]))
    monkeypatch.setattr(eng.actions, "block_ip", lambda ip: ("ok", f"{ip} bloquée"))
    called = []
    monkeypatch.setattr(eng.actions, "stop_local_attack", lambda label: called.append(label) or ("ok", ""))
    monkeypatch.setattr(eng.verify, "verify_recovery", lambda: (True, {"ok": True}))

    inc = engine.handle("port_scan", 0.9)
    assert called == []                                       # jamais coupé à la source
    assert inc["status"] == "contained"


def test_compromission_jamais_resolue(engine, monkeypatch):
    """Une injection est confinée, jamais déclarée « resolved » automatiquement."""
    import remediation.engine as eng
    monkeypatch.setattr(eng.sources, "top_source_ip", lambda t, **k: (None, []))
    monkeypatch.setattr(eng.actions, "stop_local_attack", lambda label: ("ok", "stoppée"))
    inc = engine.handle("sql_injection", 0.95)
    assert inc["status"] == "contained"
    assert inc["status"] != "resolved"
