import csv

import pytest

from data.collector import collect, kpis, labels


def test_kpi_names_come_from_prometheus_rules():
    names = kpis.kpi_names()
    assert "kpi:req_per_sec" in names and "kpi:api_up" in names
    assert len(names) == len(set(names))
    assert all(n.startswith("kpi:") for n in names)


def test_read_label_handles_powershell_utf16(tmp_path):
    f = tmp_path / "label.txt"
    f.write_bytes("ddos\r\n".encode("utf-16"))          # ce qu'écrit « echo ddos > label.txt »
    assert labels.read_label(f) == "ddos"
    f.write_text("  Brute_Force \n", encoding="utf-8-sig")
    assert labels.read_label(f) == "brute_force"
    assert labels.read_label(tmp_path / "absent.txt") == "normal"


def test_write_label_validates_and_keeps_history(tmp_path):
    f, hist = tmp_path / "label.txt", tmp_path / "history.csv"
    labels.write_label("sql_injection", f, hist)
    assert labels.read_label(f) == "sql_injection"
    with pytest.raises(ValueError):
        labels.write_label("ddoss", f, hist)
    rows = list(csv.reader(hist.open(encoding="utf-8")))
    assert rows[0] == ["timestamp", "iso_time", "label"] and rows[1][2] == "sql_injection"


def test_snapshot_never_invents_zeros(monkeypatch):
    prom = kpis.Prometheus("http://prometheus.invalid")
    monkeypatch.setattr(prom, "_get", lambda path, params: {"result": [
        {"metric": {"__name__": "kpi:req_per_sec"}, "value": [0, "4.5"]},
        {"metric": {"__name__": "kpi:latency_p95_seconds"}, "value": [0, "NaN"]},
    ]})
    values = prom.snapshot(["kpi:req_per_sec", "kpi:latency_p95_seconds", "kpi:api_up"])
    assert values == {"kpi:req_per_sec": 4.5, "kpi:latency_p95_seconds": None, "kpi:api_up": None}
    r = collect.row(1_700_000_000, values, list(values), "normal", 1)
    assert r[2:5] == ["4.5", "", ""]


def test_warmup_window_is_rejected(monkeypatch):
    prom = kpis.Prometheus("http://prometheus.invalid")
    monkeypatch.setattr(prom, "scalar", lambda expr, at=None: 2.0)      # 2 échantillons sur 6
    with pytest.raises(kpis.NotReady):
        prom.check_ready()
    monkeypatch.setattr(prom, "scalar", lambda expr, at=None: 6.0)
    prom.check_ready()


def test_history_drops_incomplete_windows(monkeypatch):
    prom = kpis.Prometheus("http://prometheus.invalid")

    def fake_get(path, params):
        if params["query"] == kpis.WARMUP_EXPR:
            return {"result": [{"metric": {}, "values": [[100, "6"], [105, "2"]]}]}
        return {"result": [{"metric": {"__name__": "kpi:req_per_sec"}, "values": [[100, "4"], [105, "0"]]}]}

    monkeypatch.setattr(prom, "_get", fake_get)
    assert prom.history(["kpi:req_per_sec"], 100, 105, 5) == {100: {"kpi:req_per_sec": 4.0}}


def test_prometheus_unreachable_raises():
    with pytest.raises(kpis.PrometheusError):
        kpis.Prometheus("http://127.0.0.1:1", timeout=0.5).snapshot(["kpi:req_per_sec"])


def test_dataset_resumes_episode_and_refuses_other_schema(tmp_path):
    names = ["kpi:a", "kpi:b"]
    path = tmp_path / "dataset.csv"
    f, writer, episode, last = collect.open_dataset(path, names)
    assert (episode, last) == (0, None)
    writer.writerow(collect.row(1, {"kpi:a": 1.0, "kpi:b": 2.0}, names, "ddos", 3))
    f.close()
    f, _, episode, last = collect.open_dataset(path, names)
    f.close()
    assert (episode, last) == (3, "ddos")
    with pytest.raises(SystemExit):
        collect.open_dataset(path, ["kpi:a", "kpi:c"])
