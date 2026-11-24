import json

from fastapi.testclient import TestClient

from utah_housing.api import create_app
from utah_housing.parser import parse_annual, synthetic_fixture


def frozen_fixture():
    parsed = parse_annual(synthetic_fixture(), 2025, require_all_counties=False)
    return {"metadata": {"periods": [2025], "synthetic": True},
            "annual": [{**row, "source_sha256": parsed.sha256} for row in parsed.rows],
            "sources": [{"url": "fixture://synthetic", "sha256": parsed.sha256,
                         "retrieved_at": "2026-01-01T00:00:00+00:00", "period": "2025", "basis": "annual"}],
            "quality": {"status": "passed"}, "operations": {"runs": [{"status": "noop"}]}}


def test_snapshot_mode_is_explicit_and_has_no_write_routes(tmp_path):
    snapshot = tmp_path / "housing.json"
    snapshot.write_text(json.dumps(frozen_fixture()))
    client = TestClient(create_app(web_root=tmp_path, snapshot_path=snapshot))
    assert client.get("/health").json()["mode"] == "frozen_snapshot"
    assert client.get("/health/ready").json()["synthetic"] is True
    assert client.get("/data/housing.json").json()["metadata"]["serving_mode"] == "frozen_snapshot"
    assert client.get("/api/runs").json()["mode"] == "frozen_snapshot"
    assert client.post("/api/runs").status_code == 405


def test_invalid_snapshot_never_claims_ready(tmp_path):
    snapshot = tmp_path / "bad.json"
    snapshot.write_text("<html>bad data</html>")
    client = TestClient(create_app(web_root=tmp_path, snapshot_path=snapshot))
    assert client.get("/health").status_code == 200
    assert client.get("/health/ready").status_code == 503


def test_frozen_snapshot_root_and_nested_shapes_are_guarded(tmp_path):
    snapshot = tmp_path / "bad-shape.json"
    for payload in [[], None, "text", {"metadata": {}, "annual": [1], "quality": {}},
                    {"metadata": {}, "annual": [], "quality": [], "operations": {}}]:
        snapshot.write_text(json.dumps(payload))
        client = TestClient(create_app(web_root=tmp_path, snapshot_path=snapshot))
        assert client.get("/api/housing").status_code == 503
        assert client.get("/health/ready").status_code == 503


def test_passing_status_cannot_make_malformed_county_or_source_records_ready(tmp_path):
    snapshot = tmp_path / "bad-record.json"
    cases = []
    bad = frozen_fixture();bad["annual"] = [{}];cases.append(bad)
    bad = frozen_fixture();bad["sources"] = [123];cases.append(bad)
    bad = frozen_fixture();bad["annual"][0]["units"] = True;cases.append(bad)
    bad = frozen_fixture();bad["annual"][0]["units"] = None;cases.append(bad)
    bad = frozen_fixture();bad["annual"][0]["units"] = 999;cases.append(bad)
    bad = frozen_fixture();bad["annual"][0]["year"] = 2024;cases.append(bad)
    bad = frozen_fixture();bad["annual"][0]["county_fips"] = [];cases.append(bad)
    bad = frozen_fixture();bad["annual"][0]["source_sha256"] = {};cases.append(bad)
    bad = frozen_fixture();bad["operations"]["runs"] = 123;cases.append(bad)
    bad = frozen_fixture();bad["annual"].append(bad["annual"][0]);cases.append(bad)
    for payload in cases:
        snapshot.write_text(json.dumps(payload))
        client = TestClient(create_app(web_root=tmp_path, snapshot_path=snapshot))
        assert client.get("/api/housing").status_code == 503
        assert client.get("/health/ready").status_code == 503


def test_missing_warehouse_cannot_silently_fall_back(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    (tmp_path / "data").mkdir()
    (tmp_path / "data/housing.json").write_text('{"annual":[{"fake":true}]}')
    client = TestClient(create_app(web_root=tmp_path))
    assert client.get("/data/housing.json").status_code == 503
    assert client.get("/api/housing").status_code == 503
