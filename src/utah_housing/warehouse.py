"""PostgreSQL publication transactions and append-only source revision evidence."""
from __future__ import annotations

from datetime import datetime, timezone
from contextlib import contextmanager
import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .parser import parse_annual, SourceError


def connection(url: str | None = None):
    url = url or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required; no implicit connection to an existing owner database.")
    return psycopg.connect(url, autocommit=True, row_factory=dict_row, connect_timeout=10)


def init_db(url: str | None = None) -> None:
    with connection(url) as db:
        db.execute(files("utah_housing").joinpath("schema.sql").read_text())


def start_run(command: str, year: int | None, synthetic: bool, url: str | None = None) -> str:
    run_id = str(uuid4())
    with connection(url) as db:
        db.execute("INSERT INTO housing_runs(run_id,command,period,status,synthetic) VALUES(%s,%s,%s,'running',%s)",
                   (run_id, command, year, synthetic))
    return run_id


def fail_run(run_id: str, error: Exception, url: str | None = None) -> None:
    with connection(url) as db:
        db.execute("UPDATE housing_runs SET status='failed',finished_at=now(),error=%s WHERE run_id=%s",
                   (f"{type(error).__name__}: {error}"[:2000], run_id))


def load_bytes(raw: bytes, year: int, source_url: str, *, synthetic: bool = False,
               retrieved_at: str | None = None, db_url: str | None = None, run_id: str | None = None) -> dict:
    init_db(db_url)
    run_id = run_id or start_run("load", year, synthetic, db_url)
    digest = hashlib.sha256(raw).hexdigest()
    try:
        with connection(db_url) as ledger:
            ledger.execute("UPDATE housing_runs SET source_sha256=%s WHERE run_id=%s", (digest, run_id))
        source = parse_annual(raw, year, require_all_counties=not synthetic)
        retrieved_at = retrieved_at or datetime.now(timezone.utc).isoformat()
        try:
            observed_at = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
            if observed_at.tzinfo is None or observed_at.utcoffset() is None:
                raise ValueError("Timezone required")
        except (AttributeError, TypeError, ValueError) as error:
            raise SourceError("retrieved_at must be a timezone-aware ISO8601 timestamp.") from error
        with connection(db_url) as db, db.transaction():
            # Serialize publication for a period; concurrent retries cannot duplicate versions.
            key = int.from_bytes(hashlib.sha256(f"utah:{year}:{synthetic}".encode()).digest()[:8], "big", signed=True)
            db.execute("SELECT pg_advisory_xact_lock(%s)", (key,))
            current = db.execute("SELECT * FROM housing_source_versions WHERE year=%s AND synthetic=%s AND active", (year, synthetic)).fetchone()
            existing = db.execute("SELECT * FROM housing_source_versions WHERE year=%s AND sha256=%s AND synthetic=%s", (year, digest, synthetic)).fetchone()
            if existing:
                if not existing["active"]:
                    raise SourceError("Previously superseded source cannot silently roll back an active revision.")
                db.execute("UPDATE housing_runs SET status='noop',finished_at=now(),source_sha256=%s,version_id=%s WHERE run_id=%s",
                           (digest, existing["version_id"], run_id))
                return {"run_id": run_id, "status": "noop", "year": year, "rows_loaded": 0, "changed_rows": 0, "sha256": digest}
            if current and observed_at <= current["retrieved_at"]:
                raise SourceError("A different source observed no later than the active source cannot supersede it.")
            previous = {row["geoid"]: row["row_data"] for row in db.execute(
                "SELECT geoid,row_data FROM housing_county_annual WHERE year=%s AND synthetic=%s", (year, synthetic))}
            changed = sum(previous.get(row["geoid"]) != row for row in source.rows)
            version_id = str(uuid4())
            if current:
                db.execute("UPDATE housing_source_versions SET active=false WHERE version_id=%s", (current["version_id"],))
            db.execute("""INSERT INTO housing_source_versions(version_id,year,basis,sha256,url,retrieved_at,raw_bytes,
                county_rows,national_rows,missing_values,synthetic,accepted_run_id)
                VALUES(%s,%s,'annual',%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (version_id, year, digest, source_url, retrieved_at, len(raw), len(source.rows), source.national_rows,
                 source.missing_value_count, synthetic, run_id))
            for row in source.rows:
                db.execute("""INSERT INTO housing_county_history(version_id,geoid,row_data) VALUES(%s,%s,%s)""",
                           (version_id, row["geoid"], Jsonb(row)))
                db.execute("""INSERT INTO housing_county_annual(year,geoid,synthetic,county_name,buildings,units,valuation_usd,row_data,source_version_id)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(year,geoid,synthetic) DO UPDATE SET county_name=excluded.county_name,
                    buildings=excluded.buildings,units=excluded.units,valuation_usd=excluded.valuation_usd,
                    row_data=excluded.row_data,source_version_id=excluded.source_version_id,updated_at=now()""",
                    (year, row["geoid"], synthetic, row["county_name"], row["buildings"], row["units"], row["valuation_usd"], Jsonb(row), version_id))
            db.execute("""UPDATE housing_runs SET status='succeeded',finished_at=now(),source_sha256=%s,
                version_id=%s,rows_loaded=%s,changed_rows=%s WHERE run_id=%s""",
                       (digest, version_id, len(source.rows), changed, run_id))
        return {"run_id": run_id, "status": "succeeded", "year": year, "rows_loaded": len(source.rows), "changed_rows": changed, "sha256": digest}
    except Exception as error:
        fail_run(run_id, error, db_url)
        raise


def json_record(record: dict) -> dict:
    return {key: (value.isoformat() if isinstance(value, datetime) else str(value) if key.endswith("_id") and value is not None else value)
            for key, value in record.items()}


def run_history(db_url: str | None = None, *, limit: int = 30, synthetic: bool = False) -> list[dict]:
    with connection(db_url) as db:
        rows = db.execute("SELECT * FROM housing_runs WHERE synthetic=%s ORDER BY started_at DESC LIMIT %s", (synthetic, limit))
        return [json_record(row) for row in rows]


def export_snapshot(db_url: str | None = None, *, synthetic: bool = False) -> dict:
    # A repeatable read snapshot keeps data, provenance and checks mutually consistent.
    with connection(db_url) as db, db.transaction():
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        rows = db.execute("""SELECT c.row_data,s.sha256 FROM housing_county_annual c
            JOIN housing_source_versions s ON s.version_id=c.source_version_id
            WHERE c.synthetic=%s ORDER BY c.year,c.geoid""", (synthetic,)).fetchall()
        sources = db.execute("SELECT * FROM housing_source_versions WHERE synthetic=%s AND active ORDER BY year", (synthetic,)).fetchall()
        history = db.execute("SELECT * FROM housing_runs WHERE synthetic=%s ORDER BY started_at DESC LIMIT 30", (synthetic,)).fetchall()
        revision_count = db.execute("SELECT count(*) AS n FROM housing_source_versions WHERE synthetic=%s", (synthetic,)).fetchone()["n"]
    annual = [{**row["row_data"], "source_sha256": row["sha256"]} for row in rows]
    checks = []
    def check(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})
    check("published_rows", bool(annual), f"{len(annual)} active county/year rows")
    check("unique_grain", len(annual) == len({(r["year"], r["geoid"]) for r in annual}), "Unique year and county FIPS")
    check("source_bindings", all(r["source_sha256"] in {s["sha256"] for s in sources} for r in annual), "Every active row binds to an accepted source SHA256")
    check("known_unit_counts", all(r["units"] is not None for r in annual), "Unknown source values remain null, never zero-filled")
    check("known_display_metrics", all(all(r[field] is not None for field in ("buildings", "units", "valuation_usd")) for r in annual),
          "Displayed totals require known buildings, units and valuation; missing values remain visible but block a passing export")
    check("component_reconciliation", all(r["units"] == sum(r[f"units_{t}"] for t in ("1", "2", "3_4", "5_plus")) for r in annual if r["units"] is not None), "Total units sum the four estimated categories, excluding reported-only duplicates")
    check("annual_only", all(r["basis"] == "annual" for r in annual), "No monthly/YTD records mixed into annual totals")
    if not synthetic:
        check("county_coverage", all(sum(r["year"] == s["year"] for r in annual) == 29 for s in sources), "29 Utah counties per published annual source")
    now = datetime.now(timezone.utc).isoformat()
    source_records = [{"url": s["url"], "sha256": s["sha256"], "retrieved_at": s["retrieved_at"].isoformat(),
                       "accepted_at": s["accepted_at"].isoformat(), "period": str(s["year"]), "basis": s["basis"],
                       "row_count": s["county_rows"], "bytes": s["raw_bytes"], "synthetic": s["synthetic"]} for s in sources]
    return {"metadata": {"generated_at": now, "title": "Utah Housing Data Platform", "mode": "warehouse_export",
                         "synthetic": synthetic, "source_urls": [s["url"] for s in source_records],
                         "periods": sorted({r["year"] for r in annual}),
                         "semantics": "New privately-owned residential units authorized by building permits; not completed homes, listings, sales or population.",
                         "validation": "Structural, source-binding and arithmetic engineering checks; not an independent Census audit.",
                         "freshness_note": "Annual reference periods shown; the retrieved source may be revised later. No real-time housing claim."},
            "annual": annual, "sources": source_records,
            "quality": {"checks": checks, "status": "passed" if all(c["passed"] for c in checks) else "needs_attention"},
            "operations": {"mode": "recorded_warehouse_runs", "runs": [json_record(row) for row in history],
                           "accepted_source_versions": revision_count, "active_sources": len(sources),
                           "note": "Actual local warehouse run ledger captured at export; this public snapshot does not launch jobs."}}


@contextmanager
def export_lock(path: Path):
    """Coordinate the full capture/write operation, not just the file rename.

    Supported execution targets are macOS/Linux and Linux Docker containers.
    Keep the zero-byte sidecar: deleting it could split concurrent lock owners
    across different inodes. Kernel locks release on process termination.
    """
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name("." + path.name + ".lock")
    with lock_path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def write_export(path: Path, db_url: str | None = None, *, synthetic: bool = False) -> dict:
    path = path.resolve()
    with export_lock(path):
        snapshot = export_snapshot(db_url, synthetic=synthetic)
        if snapshot["quality"]["status"] != "passed":
            raise SourceError("Quality checks failed; existing export was not overwritten.")
        temporary = path.with_suffix(path.suffix + "." + uuid4().hex + ".tmp")
        temporary.write_text(json.dumps(snapshot, indent=2) + "\n")
        temporary.replace(path)
        return snapshot
