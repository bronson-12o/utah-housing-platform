"""Local Dagster OSS assets run the actual source/warehouse/export implementation."""
from pathlib import Path
import os

from dagster import Definitions, MetadataValue, ScheduleDefinition, DefaultScheduleStatus, asset, asset_check, AssetCheckResult, define_asset_job

from .pipeline import fetch_annual, years
from .warehouse import init_db, load_bytes, write_export


@asset(description="Public Census annual county downloads, raw bytes and source fingerprints.")
def census_annual_sources(context):
    records = [fetch_annual(year, Path(os.getenv("HOUSING_DATA_DIR", "data")))
               for year in years(os.getenv("HOUSING_YEARS", "2021:2025"))]
    context.add_output_metadata({"source_count": len(records), "sources": MetadataValue.json(records)})
    return records


@asset(description="Validate and transactionally publish each source revision to PostgreSQL.")
def utah_county_warehouse(context, census_annual_sources):
    init_db()
    receipts = [load_bytes(Path(source["path"]).read_bytes(), source["year"], source["url"],
                           retrieved_at=source["retrieved_at"]) for source in census_annual_sources]
    context.add_output_metadata({"receipts": MetadataValue.json(receipts)})
    return receipts


@asset(description="Quality-gated original-source snapshot used by the public dashboard.")
def housing_dashboard_export(context, utah_county_warehouse):
    output = Path(os.getenv("HOUSING_EXPORT_PATH", str(Path(os.getenv("HOUSING_DATA_DIR", "data")) / "exports/housing.json")))
    result = write_export(output)
    context.add_output_metadata({"path": str(output), "rows": len(result["annual"]), "quality": result["quality"]["status"]})
    return result


@asset_check(asset=housing_dashboard_export)
def source_bound_export(housing_dashboard_export):
    result = housing_dashboard_export["quality"]
    return AssetCheckResult(passed=result["status"] == "passed", metadata={"checks": MetadataValue.json(result["checks"])})


refresh_job = define_asset_job("housing_refresh", selection="*")
monthly_revision_check = ScheduleDefinition(
    name="monthly_source_revision_check", job=refresh_job, cron_schedule="0 9 20 * *",
    execution_timezone="America/Denver", default_status=DefaultScheduleStatus.STOPPED,
    description="Opt-in monthly check of configured annual source revisions; stopped by default.")
defs = Definitions(assets=[census_annual_sources, utah_county_warehouse, housing_dashboard_export],
                   asset_checks=[source_bound_export], jobs=[refresh_job], schedules=[monthly_revision_check])
