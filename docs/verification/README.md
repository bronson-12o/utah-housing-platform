# Verification record

These are bounded checks of the implemented release and captured 2021–2025 source files, not general accuracy certification. The [final audit](final-audit.json) summarizes the combined release. Receipts retain their timestamps and source fingerprints; the earlier independent-review and original browser records describe their captured versions.

- [Source reconciliation](source-reconciliation.json): 1,305 value/name/fingerprint comparisons and five separately published state totals. `scripts/verify_snapshot.py` does not import the application parser. Live-source checks are separate from CI's offline structure checks.
- [Independent runtime review](independent-review.json): 11 adversarial checks and 12 API boundary checks passed, including two separate export processes competing for the same output. Only synthetic data in disposable isolated schemas was written. The receipt pins the reviewed Python files by SHA256.
- [Actual browser checks](browser.json): six Chromium/WebKit cases at desktop, 390px and 320px widths, plus four negative cases. Filters, all five totals, map/table selection, keyboard access, source expansion and JSON download were checked. Negative cases cover a failed request/retry, duplicates, unknown units and missing geometry. This checks snapshot-to-UI behavior; source accuracy is verified separately.
- [Frontend contract review](frontend-review.json): 89 reproducible browser checks, including six actual workflows, 80 controlled contract cases and three loading/fallback cases. A separate reviewer passed 17 independent cases. Selected small-text and focus colors were measured against their actual backgrounds; this is not a complete accessibility certification. Original pictures, the source snapshot and county geometry were preserved.
- [Sharp county explorer](sharp-ui.json): the selected white/graphite interface with blue/cyan quantity classes passed visual review and 163 browser scenarios. A bounded header-typography followup reran the 89 baseline scenarios and passed 80 additional header text-layout cases across all five years, both phone widths and both browser engines. These rounds overlap and are not an accuracy percentage. Original data, geometry, pictures and source safeguards remain unchanged.
- [Sharp UI runtime update](sharp-runtime.json): the reviewed image runs in the existing Compose applications and local Kubernetes dashboard. All package files and all ten web files match; real145-row and synthetic2-row readiness passed. Database workloads, source/run history, jobs and stopped/suspended schedules stayed unchanged. This update did not repeat the earlier recovery drills.
- [Diagram rendering](diagram-render.json): both source-matched SVG diagrams rendered in Chromium with no text outside the viewbox and were visually reviewed.
- [Local Kubernetes](kubernetes.json): nine checks passed in the dedicated kind cluster, including rejected-job retry, unchanged accepted data, successful refresh, persistent data after pod replacement, dashboard recovery and deployed-package hash equality. Optional `python3 scripts/verify_kubernetes.py` deliberately records rejected runs and restarts only this project's named local cluster workloads.
- [Docker and Dagster](docker.json): 62 regression tests passed with zero skips, including 11 actual PostgreSQL integration cases. Real and synthetic workspaces became ready separately; five repeated annual loads were no-ops. The Dagster refresh and asset check succeeded. A controlled database outage returned 503 for readiness/data, and database/application restarts restored the same accepted rows and source versions.
- Runtime regression tests additionally exercise malformed inputs, source periods, category math, missing values, JavaScript-safe integer bounds, idempotence, revisions, rollback, concurrent load/export writers, delayed source observations, API failures and synthetic isolation. PostgreSQL cases run against isolated schemas.
- Screenshots in `../images/` are captured from the actual dashboard. Architecture/model SVGs describe the implementation. No AI-generated screenshot or fabricated geography is used.

These are local verification receipts; the GitHub Actions workflow shows the actual hosted CI result. The public dashboard's operations panel is the actual ledger **at export time**, not a live public scheduler.

## Optional browser regression checks

Use Node.js and an existing `@playwright/test` installation, or install the tested development tool into a temporary prefix:

```bash
npm install --prefix /tmp/utah-housing-browser-tools @playwright/test@1.63.0
/tmp/utah-housing-browser-tools/node_modules/.bin/playwright install chromium webkit
python3 -m http.server 8089 --bind 127.0.0.1 --directory web
```

Leave that static server running. From a second terminal at the repository root:

```bash
BASE_URL=http://127.0.0.1:8089/ \
PLAYWRIGHT_MODULE=/tmp/utah-housing-browser-tools/node_modules/@playwright/test \
node scripts/check_dashboard.cjs
```

`BASE_URL` can point to another serving location. `PLAYWRIGHT_MODULE` can point to an existing installation; when omitted, normal Node module resolution is used. `ARTIFACT_DIR` overrides the default ignored `artifacts/dashboard-checks/` output. Screenshots and the JSON receipt are written there, leaving all checked-in pictures untouched.

The script compares served annual facts to the checked-in snapshot, checks all five totals and 29 counties, and compares the download to the exact JSON received by that page. Its negative cases intercept requests only in their own browser pages; they do not change a server, database or the source files. It deliberately rejects contradictory “passed” receipts while separately proving that truthful `needs_attention` exports retain null values. This browser check does not replace the original-source reconciliation.
