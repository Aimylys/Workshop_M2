import os

os.environ["ORCH_AUTOSTART"] = "0"

import yaml
from fastapi.testclient import TestClient

from app.engine import Engine
from app.main import create_app
from app.normalize import normalize

CFG = yaml.safe_load(open(os.path.join(os.path.dirname(__file__), "..", "config.yaml")))


class FakeClock:
    def __init__(self): self.t = 1000.0
    def now(self): return self.t
    def sleep(self, s): self.t += s


class FakeDocker:
    """healthy_after : service -> nombre de redémarrages nécessaires pour redevenir healthy."""
    def __init__(self, healthy_after, present=("db", "auth", "api", "waf")):
        self.need = dict(healthy_after)
        self.restarts, self.signals, self.present = [], [], set(present)
        self.count = {}

    def state(self, service):
        if service not in self.present:
            return {"present": False}
        ok = self.count.get(service, 0) >= self.need.get(service, 0)
        return {"present": True, "status": "running", "health": "healthy" if ok else "unhealthy"}

    def restart(self, service):
        if service not in self.present:
            raise LookupError(service)
        self.restarts.append(service)
        self.count[service] = self.count.get(service, 0) + 1

    def signal(self, service, sig):
        if service not in self.present:
            raise LookupError(service)
        self.signals.append((service, sig))


class FakeHTTP:
    def get(self, url, timeout=None):
        class R: status_code = 200
        return R()


def make(healthy_after, tmp_path, **kw):
    cfg = dict(CFG)
    cfg["blocklist_file"] = str(tmp_path / "blocked.txt")
    clock = FakeClock()
    docker = FakeDocker(healthy_after, **kw)
    return Engine(cfg, docker, FakeHTTP(), clock=clock.now, sleep=clock.sleep), docker


def inc(name="ServiceDown", kind="availability", service="api", ip=None):
    return {"name": name, "kind": kind, "service": service, "source_ip": ip, "source": "test"}


def test_redemarrage_palier_1(tmp_path):
    eng, d = make({"api": 1}, tmp_path)
    r = eng.submit(inc(), background=False)
    i = eng.incidents[r["incident"]]
    assert i["status"] == "resolved" and d.restarts == ["api"]


def test_escalade_palier_2(tmp_path):
    eng, d = make({"api": 2}, tmp_path)          # il faut deux redémarrages d'api
    r = eng.submit(inc(), background=False)
    i = eng.incidents[r["incident"]]
    assert i["status"] == "resolved"
    assert d.restarts == ["api", "db", "api"]    # palier 1 puis palier 2


def test_echec_total(tmp_path):
    eng, d = make({"api": 99}, tmp_path)
    r = eng.submit(inc(), background=False)
    assert eng.incidents[r["incident"]]["status"] == "failed"
    assert "intervention humaine" in eng.incidents[r["incident"]]["note"]


def test_anomalie_sans_redemarrage_inutile(tmp_path):
    eng, d = make({}, tmp_path)                    # service sain après confinement
    r = eng.submit(inc("ml_anomaly", "anomaly", ip="192.168.137.20"), background=False)
    i = eng.incidents[r["incident"]]
    assert i["status"] == "resolved" and d.restarts == []
    assert ("waf", "HUP") in d.signals
    assert "192.168.137.20" in open(eng.cfg["blocklist_file"]).read()


def test_ip_protegee_jamais_bloquee(tmp_path):
    eng, d = make({}, tmp_path)
    eng.submit(inc("ml_anomaly", "anomaly", ip="192.168.137.1"), background=False)
    assert not os.path.exists(eng.cfg["blocklist_file"])
    assert d.signals == []


def test_compromission_jamais_resolue(tmp_path):
    eng, d = make({}, tmp_path)
    r = eng.submit(inc("sql_injection", "compromise", ip="192.168.137.20"), background=False)
    i = eng.incidents[r["incident"]]
    assert i["status"] == "contained" and d.restarts == []


def test_dedoublonnage_et_cooldown(tmp_path):
    eng, d = make({"api": 1}, tmp_path)
    eng.submit(inc(), background=False)
    r2 = eng.submit(inc(), background=False)       # juste après : délai de repos
    assert r2["accepted"] is False


def test_service_non_deploye(tmp_path):
    eng, d = make({}, tmp_path, present=("db",))
    r = eng.submit(inc(service="api"), background=False)
    assert eng.incidents[r["incident"]]["status"] == "failed"


def test_normalisation():
    am = {"alerts": [
        {"status": "firing", "labels": {"alertname": "ServiceDown", "job": "postgres"}},
        {"status": "resolved", "labels": {"alertname": "ServiceDown", "job": "api"}},
    ]}
    out = normalize(CFG, am)
    assert len(out) == 1 and out[0]["service"] == "db" and out[0]["kind"] == "availability"
    ml = normalize(CFG, {"type": "ml_anomaly", "score": 0.9, "source_ip": "not-an-ip"})
    assert ml[0]["source_ip"] is None and ml[0]["service"] == "api" and ml[0]["kind"] == "anomaly"


def test_authentification_webhook(tmp_path):
    eng, _ = make({}, tmp_path)
    client = TestClient(create_app(eng, token="secret", poll=False))
    body = {"type": "ml_anomaly"}
    assert client.post("/webhook/alert", json=body).status_code == 401
    assert client.post("/webhook/alert", json=body, headers={"Authorization": "Bearer mauvais"}).status_code == 401
    assert client.get("/health").status_code == 200
    assert client.get("/api/state").status_code == 200
    r = client.post("/webhook/alert", json=body, headers={"Authorization": "Bearer secret"})
    assert r.status_code == 200 and r.json()["received"] == 1


def test_sans_jeton_configure(tmp_path):
    eng, _ = make({}, tmp_path)
    client = TestClient(create_app(eng, token="", poll=False))
    assert client.post("/webhook/alert", json={}, headers={"Authorization": "Bearer x"}).status_code == 503
