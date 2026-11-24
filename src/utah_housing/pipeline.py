"""Bounded public downloads, raw fingerprints and repeatable warehouse publication."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import urllib.request
from uuid import uuid4

from .parser import SourceError
from .warehouse import init_db, start_run, fail_run, load_bytes, write_export

BASE_URL = "https://www2.census.gov/econ/bps/County/"


def years(value: str) -> list[int]:
    try:
        if ":" in value:
            first, last = map(int, value.split(":"))
            result = list(range(first, last + 1))
        else:
            result = [int(item) for item in value.split(",")]
    except ValueError as error:
        raise SourceError("Years must be 2021:2025 or a comma-separated list.") from error
    if not result or len(result) > 30 or any(not 2000 <= y <= 2100 for y in result):
        raise SourceError("Select between one and thirty annual reference years.")
    return sorted(set(result))


def fetch_annual(year: int, data_dir: Path | None = None) -> dict:
    data_dir = data_dir or Path(os.getenv("HOUSING_DATA_DIR", "data"))
    if not 2000 <= year <= 2100:
        raise SourceError("Unsupported annual reference year.")
    url = f"{BASE_URL}co{year}a.txt"
    request = urllib.request.Request(url, headers={"User-Agent": "UtahHousingPlatform/0.1 (educational public Census BPS analysis)"})
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read(8_000_001)
        content_type = response.headers.get("Content-Type", "")
        if response.status != 200:
            raise SourceError("Source download did not return HTTP 200.")
    if len(raw) > 8_000_000:
        raise SourceError("Annual source exceeds the bounded download size.")
    if "html" in content_type.lower() or raw.lstrip().startswith(b"<"):
        raise SourceError("Source returned HTML instead of the declared annual CSV.")
    digest = hashlib.sha256(raw).hexdigest()
    destination = data_dir / "raw" / f"co{year}a-{digest}.txt"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_bytes() != raw:
            raise SourceError("Cached source fingerprint collision or local corruption.")
    else:
        temporary = destination.with_suffix("." + uuid4().hex + ".download")
        temporary.write_bytes(raw)
        temporary.replace(destination)
    record = {"url": url, "sha256": digest, "retrieved_at": datetime.now(timezone.utc).isoformat(),
              "year": year, "basis": "annual", "bytes": len(raw), "path": str(destination)}
    metadata = destination.with_suffix(".json")
    temporary = metadata.with_suffix("." + uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(record, indent=2) + "\n")
    temporary.replace(metadata)
    return record


def backfill(selected_years: list[int], *, data_dir: Path | None = None,
             output: Path | None = None, db_url: str | None = None) -> dict:
    init_db(db_url)
    results = []
    for year in selected_years:
        run_id = start_run("backfill", year, False, db_url)
        try:
            source = fetch_annual(year, data_dir)
        except Exception as error:
            fail_run(run_id, error, db_url)
            raise
        results.append(load_bytes(Path(source["path"]).read_bytes(), year, source["url"],
                                  retrieved_at=source["retrieved_at"], db_url=db_url, run_id=run_id))
    report = {"status": "succeeded", "results": results}
    if output:
        snapshot = write_export(output, db_url)
        report["export"] = str(output)
        report["exported_rows"] = len(snapshot["annual"])
    return report
