from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

from .parser import synthetic_fixture, SourceError
from .pipeline import backfill, fetch_annual, years
from .warehouse import init_db, load_bytes, export_snapshot, write_export, run_history


def main(argv=None):
    parser = argparse.ArgumentParser(description="Source-versioned Utah housing permit pipeline; no paid services.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Initialize application tables in the explicitly configured PostgreSQL database.")
    fetch = sub.add_parser("fetch", help="Download one public annual source with a raw fingerprint.")
    fetch.add_argument("--year", type=int, required=True)
    fetch.add_argument("--data-dir", type=Path)
    load = sub.add_parser("load", help="Validate and atomically publish one annual source file.")
    load.add_argument("path", type=Path)
    load.add_argument("--year", type=int, required=True)
    load.add_argument("--source-url")
    fill = sub.add_parser("backfill", help="Fetch, validate and publish selected source years.")
    fill.add_argument("--years", default="2021:2025")
    fill.add_argument("--data-dir", type=Path)
    fill.add_argument("--output", type=Path)
    fixture = sub.add_parser("fixture", help="Load visibly synthetic engineering data into an isolated fixture/test database.")
    fixture.add_argument("--year", type=int, default=2025)
    fixture.add_argument("--revised", action="store_true")
    fixture.add_argument("--output", type=Path)
    check = sub.add_parser("check", help="Run source-binding, grain and arithmetic checks on active data.")
    check.add_argument("--synthetic", action="store_true")
    export = sub.add_parser("export", help="Atomically export a quality-passed, source-bound static snapshot.")
    export.add_argument("--output", type=Path, required=True)
    export.add_argument("--synthetic", action="store_true")
    sub.add_parser("runs", help="Read actual run history.")
    serve = sub.add_parser("serve", help="Serve the dashboard and read-only local API.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    serve.add_argument("--web-root", type=Path, default=Path(os.getenv("HOUSING_WEB_ROOT", "web")))
    serve.add_argument("--snapshot", type=Path, help="Explicit frozen-only mode, independent of PostgreSQL.")
    serve.add_argument("--synthetic", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            init_db(); result = {"status": "initialized", "backend": "postgresql"}
        elif args.command == "fetch":
            result = fetch_annual(args.year, args.data_dir)
        elif args.command == "load":
            result = load_bytes(args.path.read_bytes(), args.year, args.source_url or "local-file:" + args.path.name)
        elif args.command == "backfill":
            result = backfill(years(args.years), data_dir=args.data_dir, output=args.output)
        elif args.command == "fixture":
            database = urlsplit(os.getenv("DATABASE_URL", "")).path.rsplit("/", 1)[-1]
            if not ("fixture" in database or "test" in database):
                raise SourceError("Fixture mode requires a distinct database whose name includes fixture or test.")
            result = load_bytes(synthetic_fixture(args.year, revised=args.revised), args.year,
                                "fixture://synthetic-two-county-engineering-data", synthetic=True)
            if args.output:
                write_export(args.output, synthetic=True)
        elif args.command == "check":
            result = export_snapshot(synthetic=args.synthetic)["quality"]
            if result["status"] != "passed":
                print(json.dumps(result, indent=2)); return 1
        elif args.command == "export":
            snapshot = write_export(args.output, synthetic=args.synthetic)
            result = {"status": "exported", "path": str(args.output), "rows": len(snapshot["annual"]), "synthetic": args.synthetic}
        elif args.command == "runs":
            result = {"runs": run_history()}
        elif args.command == "serve":
            from .api import create_app
            import uvicorn
            uvicorn.run(create_app(web_root=args.web_root, snapshot_path=args.snapshot, synthetic=args.synthetic),
                        host=args.host, port=args.port)
            return 0
        print(json.dumps(result, indent=2, default=str))
        return 0
    except Exception as error:
        # CLI errors remain visible and nonzero; never manufacture a passing report.
        print(json.dumps({"status": "failed", "error": f"{type(error).__name__}: {error}"}), file=sys.stderr)
        return 1
