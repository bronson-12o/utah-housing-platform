"""Actual PostgreSQL tests. TEST_DATABASE_URL must identify a disposable test database."""
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from utah_housing.parser import SourceError, synthetic_fixture
from utah_housing.warehouse import connection, init_db, load_bytes, export_snapshot, write_export

pytestmark = pytest.mark.postgres


@pytest.fixture
def warehouse(monkeypatch):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; real PostgreSQL integration not exercised.")
    from urllib.parse import urlsplit
    if not any(marker in urlsplit(url).path for marker in ("test", "fixture")):
        pytest.fail("Refusing tests against a database not explicitly named test or fixture.")
    schema = "test_" + uuid4().hex
    with connection(url) as db:
        db.execute('CREATE SCHEMA "' + schema + '"')
    # Isolation is connection-local and never changes a production table.
    from psycopg.conninfo import make_conninfo
    isolated = make_conninfo(url, options=f"-csearch_path={schema}")
    monkeypatch.setenv("DATABASE_URL", isolated)
    init_db()
    yield isolated
    with connection(url) as db:
        db.execute('DROP SCHEMA "' + schema + '" CASCADE')


def test_load_rerun_revision_failure_and_history_are_atomic(warehouse):
    raw = synthetic_fixture()
    first = load_bytes(raw, 2025, "fixture://independent-cases", synthetic=True)
    assert first["status"] == "succeeded" and first["rows_loaded"] == 2 and first["changed_rows"] == 2
    second = load_bytes(raw, 2025, "fixture://independent-cases", synthetic=True)
    assert second["status"] == "noop" and second["rows_loaded"] == 0
    revised = load_bytes(synthetic_fixture(revised=True), 2025, "fixture://revised", synthetic=True)
    assert revised["changed_rows"] == 1
    before_bad = export_snapshot(synthetic=True)
    with pytest.raises(SourceError):
        load_bytes(raw.replace(b",10,10,", b",10,-1,", 1), 2025, "fixture://malformed", synthetic=True)
    after_bad = export_snapshot(synthetic=True)
    assert after_bad["annual"] == before_bad["annual"]
    assert after_bad["sources"] == before_bad["sources"]
    assert after_bad["operations"]["runs"][0]["status"] == "failed"
    assert after_bad["operations"]["runs"][0]["source_sha256"]
    assert after_bad["operations"]["accepted_source_versions"] == 2
    assert sum(row["units"] for row in after_bad["annual"]) == 54
    with connection() as db:
        assert db.execute("SELECT count(*) AS n FROM housing_county_annual").fetchone()["n"] == 2
        assert db.execute("SELECT count(*) AS n FROM housing_county_history").fetchone()["n"] == 4
    # An old known source cannot undo a published revision through a late retry.
    with pytest.raises(SourceError, match="roll back"):
        load_bytes(raw, 2025, "fixture://stale-retry", synthetic=True)
    assert export_snapshot(synthetic=True)["annual"] == after_bad["annual"]


def test_unknown_values_gate_export_without_overwriting_last_good_file(warehouse, tmp_path):
    raw = synthetic_fixture()
    load_bytes(raw, 2025, "fixture://initial", synthetic=True)
    target = tmp_path / "snapshot.json"
    write_export(target, synthetic=True)
    before = target.read_bytes()
    missing = raw.replace(b",10,10,1000000,", b",10,,1000000,", 1)
    load_bytes(missing, 2025, "fixture://unknown", synthetic=True)
    result = export_snapshot(synthetic=True)
    assert result["quality"]["status"] == "needs_attention"
    assert result["annual"][0]["units"] is None
    with pytest.raises(SourceError, match="Quality"):
        write_export(target, synthetic=True)
    assert target.read_bytes() == before


def test_multiple_reference_years_and_synthetic_partition_are_distinct(warehouse):
    for year in (2024, 2025):
        load_bytes(synthetic_fixture(year), year, "fixture://two-years", synthetic=True)
    result = export_snapshot(synthetic=True)
    assert result["metadata"]["periods"] == [2024, 2025]
    assert len(result["annual"]) == 4
    assert result["metadata"]["synthetic"] is True
    assert export_snapshot()["annual"] == []


def test_mid_publication_database_failure_rolls_back_every_county_and_version(warehouse):
    import psycopg
    load_bytes(synthetic_fixture(), 2025, "fixture://initial", synthetic=True)
    before = export_snapshot(synthetic=True)
    with connection() as db:
        db.execute("ALTER TABLE housing_county_annual ADD CONSTRAINT deliberate_second_row_failure CHECK (geoid <> '49003') NOT VALID")
    with pytest.raises(psycopg.errors.CheckViolation):
        load_bytes(synthetic_fixture(revised=True), 2025, "fixture://deliberately-failing-publication", synthetic=True)
    after = export_snapshot(synthetic=True)
    assert after["annual"] == before["annual"]
    assert after["sources"] == before["sources"]
    assert after["operations"]["accepted_source_versions"] == 1
    assert after["operations"]["runs"][0]["status"] == "failed"
    with connection() as db:
        assert db.execute("SELECT count(*) AS n FROM housing_county_history").fetchone()["n"] == 2


def test_overlapping_retries_publish_one_version(warehouse):
    from concurrent.futures import ThreadPoolExecutor
    def load(_):
        return load_bytes(synthetic_fixture(), 2025, "fixture://overlapping-runs", synthetic=True, db_url=warehouse)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(load, range(2)))
    assert sorted(row["status"] for row in results) == ["noop", "succeeded"]
    result = export_snapshot(synthetic=True)
    assert len(result["annual"]) == 2
    assert result["operations"]["accepted_source_versions"] == 1
    assert len(result["operations"]["runs"]) == 2


def test_revision_removes_obsolete_counties_but_preserves_source_history(warehouse):
    load_bytes(synthetic_fixture(), 2025, "fixture://two-counties", synthetic=True)
    # Independent expected case: keep only the first data row, revise its
    # 5+ category from six to seven units, and remove the second county.
    reduced = b"\n".join(synthetic_fixture(revised=True).splitlines()[:3]) + b"\n"
    receipt = load_bytes(reduced, 2025, "fixture://one-county", synthetic=True)
    assert receipt["rows_loaded"] == 1
    assert receipt["changed_rows"] == 2  # One changed county and one removed.
    result = export_snapshot(synthetic=True)
    assert [row["geoid"] for row in result["annual"]] == ["49001"]
    assert result["annual"][0]["units"] == 24
    assert result["sources"][0]["row_count"] == 1
    assert result["quality"]["status"] == "passed"
    with connection() as db:
        assert db.execute("SELECT count(*) AS n FROM housing_county_history").fetchone()["n"] == 3
        assert db.execute("SELECT count(*) AS n FROM housing_source_versions WHERE active").fetchone()["n"] == 1
    assert load_bytes(reduced, 2025, "fixture://repeat", synthetic=True)["status"] == "noop"


def test_failed_replacement_restores_removed_counties_as_well_as_values(warehouse):
    import psycopg
    load_bytes(synthetic_fixture(), 2025, "fixture://initial", synthetic=True)
    before = export_snapshot(synthetic=True)
    reduced = b"\n".join(synthetic_fixture(revised=True).splitlines()[:3]) + b"\n"
    with connection() as db:
        db.execute("ALTER TABLE housing_county_annual ADD CONSTRAINT deliberate_first_row_failure CHECK (geoid <> '49001') NOT VALID")
    with pytest.raises(psycopg.errors.CheckViolation):
        load_bytes(reduced, 2025, "fixture://failed-replacement", synthetic=True)
    after = export_snapshot(synthetic=True)
    assert after["annual"] == before["annual"]
    assert after["sources"] == before["sources"]
    assert after["operations"]["runs"][0]["status"] == "failed"
    assert after["operations"]["accepted_source_versions"] == 1


def test_network_failure_is_a_visible_failed_run_without_touching_published_rows(warehouse, monkeypatch):
    from utah_housing.pipeline import backfill
    load_bytes(synthetic_fixture(), 2025, "fixture://initial", synthetic=True)
    before = export_snapshot(synthetic=True)["annual"]
    def unavailable(*args, **kwargs):
        raise ConnectionError("Synthetic network outage used only by this isolated test")
    monkeypatch.setattr("utah_housing.pipeline.fetch_annual", unavailable)
    with pytest.raises(ConnectionError):
        backfill([2025], db_url=warehouse)
    assert export_snapshot(synthetic=True)["annual"] == before
    with connection() as db:
        row = db.execute("SELECT status,error FROM housing_runs ORDER BY started_at DESC LIMIT 1").fetchone()
    assert row["status"] == "failed" and "Synthetic network outage" in row["error"]


def test_delayed_new_sha_cannot_replace_a_newer_observation(warehouse):
    initial = synthetic_fixture()
    revised = synthetic_fixture(revised=True)
    load_bytes(initial, 2025, "fixture://initial", synthetic=True, retrieved_at="2026-01-02T00:00:00Z")
    load_bytes(revised, 2025, "fixture://revised", synthetic=True, retrieved_at="2026-01-03T00:00:00Z")
    before = export_snapshot(synthetic=True)
    # Old content with different line encoding produces a previously unseen SHA.
    delayed = initial.replace(b"\n", b"\r\n")
    with pytest.raises(SourceError, match="no later"):
        load_bytes(delayed, 2025, "fixture://delayed", synthetic=True, retrieved_at="2026-01-01T00:00:00Z")
    after = export_snapshot(synthetic=True)
    assert after["annual"] == before["annual"]
    assert after["operations"]["accepted_source_versions"] == 2
    assert after["operations"]["runs"][0]["status"] == "failed"


def test_reference_retrieval_time_requires_timezone(warehouse):
    for value in ["2026-01-01T00:00:00", "not-a-date"]:
        with pytest.raises(SourceError, match="timezone-aware"):
            load_bytes(synthetic_fixture(), 2025, "fixture://bad-time", synthetic=True, retrieved_at=value)
    assert export_snapshot(synthetic=True)["annual"] == []


def test_full_export_lock_prevents_old_snapshot_from_overwriting_new_export(warehouse, tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, current_thread
    import time
    import utah_housing.warehouse as module
    load_bytes(synthetic_fixture(), 2025, "fixture://initial", synthetic=True)
    original = module.export_snapshot
    old_captured, release_old, second_started = Event(), Event(), Event()
    calls = 0
    def captured(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == 1:
            old_captured.set()
            assert release_old.wait(5)
        else:
            second_started.set()
        return result
    monkeypatch.setattr(module, "export_snapshot", captured)
    target = tmp_path / "shared.json"
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(module.write_export, target, synthetic=True)
        assert old_captured.wait(5)
        load_bytes(synthetic_fixture(revised=True), 2025, "fixture://revision", synthetic=True)
        second = pool.submit(module.write_export, target, synthetic=True)
        time.sleep(.1)
        assert not second.done() and not second_started.is_set()
        release_old.set()
        first.result(timeout=5);second.result(timeout=5)
    assert json.loads(target.read_text())["annual"][0]["units"] == 24
    assert not list(tmp_path.glob("*.tmp"))
