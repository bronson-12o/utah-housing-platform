import json
import pytest

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


@pytest.mark.parametrize("case", ["failed_check", "malformed_check", "string_check_status", "synthetic_string",
                                 "wrong_periods", "boolean_period", "truncated_real", "duplicate_source", "unused_source"])
def test_frozen_readiness_rejects_contradictory_quality_and_scope(tmp_path, case):
    payload = frozen_fixture()
    if case == "failed_check":
        payload["quality"]["checks"] = [{"name": "source_bindings", "passed": False, "detail": "failed"}]
    elif case == "malformed_check":
        payload["quality"]["checks"] = ["passed"]
    elif case == "string_check_status":
        payload["quality"]["checks"] = [{"name": "coverage", "passed": "false", "detail": "failed"}]
    elif case == "synthetic_string":
        payload["metadata"]["synthetic"] = "false"
    elif case == "wrong_periods":
        payload["metadata"]["periods"] = [2024]
    elif case == "boolean_period":
        payload["metadata"]["periods"] = [True]
    elif case == "truncated_real":
        payload["metadata"]["synthetic"] = False
    elif case == "duplicate_source":
        payload["sources"].append(dict(payload["sources"][0]))
    elif case == "unused_source":
        payload["sources"].append({**payload["sources"][0], "period": "2024"})
    path = tmp_path / "contradictory.json"
    path.write_text(json.dumps(payload))
    client = TestClient(create_app(web_root=tmp_path, snapshot_path=path))
    assert client.get("/health").status_code == 200
    assert client.get("/health/ready").status_code == 503
    assert client.get("/data/housing.json").status_code == 503


def test_honest_needs_attention_snapshot_remains_readable_but_not_ready(tmp_path):
    payload = frozen_fixture()
    payload["quality"] = {"status": "needs_attention", "checks": [
        {"name": "review", "passed": False, "detail": "Requires source review"}]}
    path = tmp_path / "needs-attention.json"
    path.write_text(json.dumps(payload))
    client = TestClient(create_app(web_root=tmp_path, snapshot_path=path))
    assert client.get("/api/housing").status_code == 200
    assert client.get("/health/ready").status_code == 503


@pytest.mark.parametrize(("location", "field", "value"), [
    ("annual", "basis", "monthly"), ("annual", "basis", None),
    ("sources", "year", 1900), ("sources", "year", "2025"), ("sources", "year", True),
    ("sources", "county_rows", 1), ("sources", "county_rows", -1), ("sources", "county_rows", True),
    ("sources", "row_count", 1), ("sources", "row_count", "2"),
])
def test_optional_annual_fields_cannot_explicitly_contradict_published_rows(tmp_path, location, field, value):
    payload = frozen_fixture()
    payload[location][0][field] = value
    path = tmp_path / "contradictory-fields.json"
    path.write_text(json.dumps(payload))
    client = TestClient(create_app(web_root=tmp_path, snapshot_path=path))
    assert client.get("/health/ready").status_code == 503
    assert client.get("/data/housing.json").status_code == 503


def test_matching_optional_annual_fields_and_period_only_sources_remain_supported(tmp_path):
    payload = frozen_fixture()
    # All three optional source fields can be omitted by the public contract.
    payload["annual"][0].pop("basis")
    path = tmp_path / "compatible-fields.json"
    path.write_text(json.dumps(payload))
    client = TestClient(create_app(web_root=tmp_path, snapshot_path=path))
    assert client.get("/health/ready").status_code == 200
    payload["sources"][0].update(year=2025, county_rows=2, row_count=2)
    payload["annual"][0]["basis"] = "annual"
    path.write_text(json.dumps(payload))
    assert client.get("/health/ready").status_code == 200
