"""Read-only local API. Static snapshot mode is explicit and does not pretend to run jobs."""
from __future__ import annotations

import json
from pathlib import Path
import os
import re

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .warehouse import connection, export_snapshot, run_history
from .parser import MAX_EXACT_INTEGER, UTAH_COUNTIES, complete_sum


def validate_frozen_format(result):
    """Validate exported record structure without pretending to re-audit raw Census files."""
    if not isinstance(result, dict) or not isinstance(result.get("annual"), list) or not isinstance(result.get("metadata"), dict):
        raise ValueError("Missing annual rows or metadata.")
    quality = result.get("quality")
    if not isinstance(quality, dict) or quality.get("status") not in ("passed", "needs_attention"):
        raise ValueError("Missing structured quality status.")
    if not isinstance(result.get("operations", {}), dict):
        raise ValueError("Captured operations must be an object.")
    if not isinstance(result.get("operations", {}).get("runs", []), list) or not all(
            isinstance(run, dict) for run in result.get("operations", {}).get("runs", [])):
        raise ValueError("Captured run history must be an array of objects.")
    if not isinstance(quality.get("checks", []), list):
        raise ValueError("Quality checks must be an array.")
    if not isinstance(result.get("sources"), list):
        raise ValueError("Sources must be an array.")
    bindings = set()
    for source in result["sources"]:
        if (not isinstance(source, dict) or source.get("basis") != "annual"
                or not isinstance(source.get("url"), str) or not source["url"]
                or not isinstance(source.get("retrieved_at"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", str(source.get("sha256", "")))
                or not re.fullmatch(r"\d{4}", str(source.get("period", "")))):
            raise ValueError("Invalid source record structure.")
        bindings.add((source["sha256"], str(source["period"])))
    seen = set()
    for row in result["annual"]:
        if not isinstance(row, dict):
            raise ValueError("Annual rows must be objects.")
        if (type(row.get("year")) is not int or not 2000 <= row["year"] <= 2100
                or row.get("state_fips") != "49" or not isinstance(row.get("county_fips"), str)
                or row["county_fips"] not in UTAH_COUNTIES
                or row.get("geoid") != "49" + row["county_fips"]
                or not isinstance(row.get("county_name"), str) or not row["county_name"]
                or not isinstance(row.get("source_sha256"), str)
                or (row["source_sha256"], str(row["year"])) not in bindings):
            raise ValueError("Invalid county identity, period or source binding.")
        grain = (row["year"], row["geoid"])
        if grain in seen:
            raise ValueError("Duplicate county/year rows in frozen export.")
        seen.add(grain)
        for field in ("buildings", "units", "valuation_usd", "units_1", "units_2", "units_3_4", "units_5_plus"):
            if field not in row:
                raise ValueError("Missing displayed metric field.")
            value = row[field]
            if value is not None and (type(value) is not int or not 0 <= value <= MAX_EXACT_INTEGER):
                raise ValueError("Invalid exact metric integer.")
            if quality["status"] == "passed" and value is None:
                raise ValueError("A passing frozen export cannot have unknown displayed metrics.")
        components = complete_sum([row[field] for field in ("units_1", "units_2", "units_3_4", "units_5_plus")])
        if components is not None and row["units"] is not None and components != row["units"]:
            raise ValueError("Frozen unit components do not reconcile to the declared total.")
    for year in {row["year"] for row in result["annual"]}:
        for field in ("buildings", "units", "valuation_usd", "units_1", "units_2", "units_3_4", "units_5_plus"):
            complete_sum([row[field] for row in result["annual"] if row["year"] == year])


def create_app(*, web_root: Path | None = None, snapshot_path: Path | None = None,
               db_url: str | None = None, synthetic: bool = False) -> FastAPI:
    web_root = web_root or Path(os.getenv("HOUSING_WEB_ROOT", "web"))
    app = FastAPI(title="Utah Housing Data Platform", version="0.1.0")
    mode = "frozen_snapshot" if snapshot_path else "postgresql_warehouse"

    @app.get("/health")
    def health():
        return {"status": "alive", "mode": mode}

    def data():
        if snapshot_path:
            try:
                result = json.loads(snapshot_path.read_text())
                validate_frozen_format(result)
                result["metadata"]["serving_mode"] = "frozen_snapshot"
                return result
            except (OSError, ValueError) as error:
                raise HTTPException(503, "Configured frozen snapshot is unavailable or invalid.") from error
        try:
            result = export_snapshot(db_url, synthetic=synthetic)
            result["metadata"]["serving_mode"] = mode
            return result
        except Exception as error:
            raise HTTPException(503, "Warehouse unavailable; no silent fallback to frozen data.") from error

    @app.get("/health/ready")
    def ready():
        snapshot = data()
        if not snapshot["annual"] or snapshot.get("quality", {}).get("status") != "passed":
            raise HTTPException(503, "No quality-passed published data is available.")
        return {"status": "ready", "mode": mode, "rows": len(snapshot["annual"]),
                "reference_years": snapshot["metadata"].get("periods", []),
                "synthetic": bool(snapshot["metadata"].get("synthetic", synthetic))}

    @app.get("/api/housing")
    @app.get("/data/housing.json")
    def housing():
        return data()

    @app.get("/api/runs")
    def runs():
        if snapshot_path:
            return {"mode": mode, "runs": data().get("operations", {}).get("runs", []),
                    "note": "Captured run history; no jobs are launched by this demo."}
        try:
            return {"mode": mode, "runs": run_history(db_url, synthetic=synthetic)}
        except Exception as error:
            raise HTTPException(503, "Warehouse run history is unavailable.") from error

    @app.get("/api/sources")
    def sources():
        return {"mode": mode, "sources": data().get("sources", [])}

    if web_root.exists():
        app.mount("/", StaticFiles(directory=str(web_root), html=True), name="dashboard")
    return app
