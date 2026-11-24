"use strict";

// Optional browser checks; no runtime dependency or database writes.
// See docs/verification/README.md for isolated Playwright setup.
const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const { chromium, webkit } = require(process.env.PLAYWRIGHT_MODULE || "@playwright/test");
const root = path.resolve(__dirname, "..");
const base = new URL(process.env.BASE_URL || "http://127.0.0.1:8089/");
if (!base.pathname.endsWith("/")) base.pathname += "/";
const output = path.resolve(process.env.ARTIFACT_DIR || path.join(root, "artifacts/dashboard-checks"));
fs.mkdirSync(output, { recursive: true });
const snapshot = fs.readFileSync(path.join(root, "web/data/housing.json"));
const payload = JSON.parse(snapshot);
const clone = () => structuredClone(payload);
const format = value => new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
const sum = year => payload.annual.filter(row => row.year === year).reduce((total, row) => total + row.units, 0);
const results = [];

function luminance(rgb) {
  const channels = rgb.match(/[\d.]+/g).slice(0, 3).map(value => Number(value) / 255)
    .map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
  return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
}
function contrast(first, second) {
  const values = [luminance(first), luminance(second)].sort((a, b) => a - b);
  return (values[1] + 0.05) / (values[0] + 0.05);
}

// Controlled in-browser mutations; original source files remain unchanged.
const negative={
 unbound_source:p=>p.annual[0].source_sha256='0'.repeat(64),
 row_monthly_basis:p=>p.annual[0].basis='monthly',
 source_year_conflict:p=>p.sources[0].year=2020,
 source_year_boolean:p=>p.sources[0].year=true,
 source_period_conflict:p=>p.sources[0].period='2020',
 source_period_array:p=>p.sources[0].period=[2021],
 source_hash_array:p=>p.sources[0].sha256=[p.sources[0].sha256],
 source_monthly_basis:p=>p.sources[0].basis='monthly',
 source_duplicate_period:p=>p.sources.push({...p.sources[0]}),
 source_row_count_mismatch:p=>p.sources[0].row_count=28,
 source_county_rows_mismatch:p=>p.sources[0].county_rows=28,
 source_row_count_string:p=>p.sources[0].row_count='29',
 source_null:p=>p.sources[0]=null,
 invalid_county:p=>{p.annual[0].geoid='49002';p.annual[0].county_fips='002'},
 metadata_period_conflict:p=>p.metadata.periods=[2025],
 metadata_period_reversed:p=>p.metadata.periods.reverse(),
 synthetic_not_boolean:p=>p.metadata.synthetic='false',
 declared_passed_failed_check:p=>p.quality.checks[0].passed=false,
 quality_boolean_string:p=>p.quality.checks[0].passed='true',
 quality_checks_null:p=>p.quality.checks=null,
 quality_check_nonobject:p=>p.quality.checks=[true],
 quality_status_unknown:p=>p.quality.status='unknown',
 quality_missing:p=>delete p.quality,
 run_receipt_nonobject:p=>p.operations=[],
 run_receipt_null_runs:p=>p.operations.runs=null,
 run_receipt_null_element:p=>p.operations.runs=[null],
 passed_missing_units:p=>p.annual[0].units=null,
 component_sum_mismatch:p=>p.annual[0].units_1++,
 real_county_coverage:p=>{p.annual=p.annual.filter(r=>!(r.year===2021&&r.geoid==='49001'));p.sources[0].row_count=28},
 unsafe_state_total:p=>{for(const r of p.annual.filter(r=>r.year===2025)){r.units=r.units_1=r.buildings=400000000000000;r.units_2=r.units_3_4=r.units_5_plus=0}},
 unsafe_component_total:p=>{p.annual[0].units=p.annual[0].units_1=Number.MAX_SAFE_INTEGER;p.annual[0].units_2=p.annual[0].units_3_4=p.annual[0].units_5_plus=1},
 unsafe_scalar:p=>p.annual[0].buildings=Number.MAX_SAFE_INTEGER+1,
 negative_metric:p=>p.annual[0].buildings=-1,
 boolean_metric:p=>p.annual[0].buildings=true,
 invalid_reference_year:p=>p.annual[0].year=1999,
};

async function open(page, value) {
  if (value) await page.route("**/data/housing.json", route => route.fulfill({ json: value }));
  await page.goto(base.href);
  await page.waitForFunction(() => document.getElementById("loading").hidden);
}

async function actualWorkflow(browser, engine, width) {
  const page = await browser.newPage({ viewport: { width, height: 1100 }, reducedMotion: "reduce" });
  const errors = [], http = [];
  page.on("pageerror", error => errors.push(error.message));
  page.on("response", response => {
    if (response.status() >= 400) http.push({ status: response.status(), url: response.url() });
  });
  const response = page.waitForResponse(response => new URL(response.url()).pathname.endsWith("/data/housing.json"));
  await open(page);
  const served = await (await response).json();
  await page.locator("#application").waitFor({ state: "visible" });
  assert.deepEqual(served.annual, payload.annual, "Served source facts differ from the checked-in snapshot; review before updating expectations.");
  assert.equal(await page.locator(".county-path").count(), 29);
  assert.equal(await page.locator("#county-table tr").count(), 29);
  for (const year of [2021, 2022, 2023, 2024, 2025]) {
    await page.locator("#year-filter").selectOption(String(year));
    assert.equal(await page.locator("#metric-units").innerText(), format(sum(year)));
  }
  await page.screenshot({ path: path.join(output, `${engine}-${width}.png`), fullPage: true });
  await page.locator("#county-filter").selectOption("49035");
  await page.locator("#year-filter").selectOption("2024");
  const saltLake = payload.annual.find(row => row.year === 2024 && row.geoid === "49035");
  assert.equal(await page.locator("#metric-units").innerText(), format(saltLake.units));
  assert.equal(await page.locator(".county-path.selected").count(), 1);
  await page.locator("#map-metric").selectOption("change");
  assert.ok((await page.locator("#county-map svg").getAttribute("aria-label")).includes("Change from prior year"));
  await page.locator('.county-path[data-geoid="49049"]').focus();
  await page.keyboard.press("Enter");
  assert.equal(await page.locator("#county-filter").inputValue(), "49049");
  await page.locator('.county-path[data-geoid="49035"]').focus();
  await page.keyboard.press("Space");
  assert.equal(await page.locator("#county-filter").inputValue(), "49035");
  assert.equal(await page.locator("#county-filter").evaluate(node => node === document.activeElement), true);
  await page.locator("#reset-county").click();
  await page.locator("#year-filter").selectOption("2021");
  assert.equal(await page.locator("#metric-change").innerText(), "Unavailable");
  await page.locator("#year-filter").selectOption("2025");
  const downloading = page.waitForEvent("download");
  await page.locator("#download-data").click();
  const download = await downloading;
  assert.deepEqual(JSON.parse(fs.readFileSync(await download.path())), served);
  await page.locator('a[href="#source-geometry"]').click();
  assert.equal(await page.locator("#source-geometry").isVisible(), true);
  assert.equal(await page.locator("#repository-link").isVisible(), true);
  assert.equal(await page.locator("#repository-link").getAttribute("href"), "https://github.com/bronson-12o/utah-housing-platform");
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  const colors = await page.evaluate(() => ({
    muted: getComputedStyle(document.querySelector(".trust-card > p")).color,
    trust: getComputedStyle(document.querySelector(".trust-card")).backgroundColor,
    axis: getComputedStyle(document.querySelector(".chart-axis")).fill,
    chart: getComputedStyle(document.querySelector(".chart-card")).backgroundColor,
    focus: getComputedStyle(document.documentElement).getPropertyValue("--focus").trim(),
    paper: getComputedStyle(document.documentElement).backgroundColor,
    map: getComputedStyle(document.querySelector(".map-card")).backgroundColor,
  }));
  const focusRgb = colors.focus.startsWith("#") ? `rgb(${[1, 3, 5].map(i => parseInt(colors.focus.slice(i, i + 2), 16)).join(",")})` : colors.focus;
  const ratios = { small_text: contrast(colors.muted, colors.trust), chart_axis: contrast(colors.axis, colors.chart),
    focus_on_paper: contrast(focusRgb, colors.paper), focus_on_map: contrast(focusRgb, colors.map) };
  assert.ok(ratios.small_text >= 4.5 && ratios.chart_axis >= 4.5);
  assert.ok(ratios.focus_on_paper >= 3 && ratios.focus_on_map >= 3);
  assert.deepEqual(errors, []);
  assert.deepEqual(http, []);
  results.push({ group: "actual_workflow", engine, width, rows: served.annual.length, annual_totals: 5,
    counties: 29, keyboard: "Enter and Space", download: "exact served JSON", ratios, passed: true });
  await mapViewWorkflow(page, engine, width, served);
  assert.deepEqual(errors, []);
  assert.deepEqual(http, []);
  await page.close();
}

async function mapViewWorkflow(page, engine, width, served) {
  await page.locator("#county-filter").selectOption("49035");
  await page.locator("#map-metric").selectOption("units");
  const fills = () => page.locator(".county-path").evaluateAll(paths => Object.fromEntries(paths.map(path => [path.dataset.geoid, path.getAttribute("fill")])));
  const metrics = () => page.locator(".metric strong, .statewide-summary strong").allTextContents();
  const original = await fills(), originalMetrics = await metrics();
  assert.equal(await page.locator("#map-view-compare").getAttribute("aria-pressed"), "true");
  await page.locator("#map-view-focus").focus();
  await page.keyboard.press("Enter");
  assert.equal(await page.locator("#map-view-focus").getAttribute("aria-pressed"), "true");
  assert.equal(new URL(page.url()).searchParams.get("view"), "focus");
  assert.deepEqual(await metrics(), originalMetrics, "Changing presentation must not alter facts or county/year selection.");
  const focused = await fills();
  assert.equal(focused["49035"], "#ff4b35");
  assert.equal(Object.values(focused).filter(fill => fill === "#ff4b35").length, 1);
  assert.ok(Object.entries(focused).every(([id, fill]) => fill === (id === "49035" ? "#ff4b35" : "#cbd0d6")));
  assert.match(await page.locator("#map-legend").innerText(), /selection, not quantity/);
  assert.doesNotMatch(await page.locator("#map-legend").innerText(), /quintile/);
  await page.reload();
  await page.locator("#application").waitFor({ state: "visible" });
  assert.equal(await page.locator("#map-view-focus").getAttribute("aria-pressed"), "true");
  assert.deepEqual(await metrics(), originalMetrics);
  await page.locator('.county-path[data-geoid="49049"]').focus();
  await page.keyboard.press("Space");
  assert.equal((await fills())["49049"], "#ff4b35");
  assert.equal((await fills())["49035"], "#cbd0d6");
  await page.locator("#year-filter").selectOption("2021");
  await page.locator("#map-metric").selectOption("change");
  assert.ok(Object.values(await fills()).every(fill => fill === "url(#missing-fill)"), "Absent prior-year values must remain hatched in Focus.");
  assert.equal(await page.locator("#metric-change").innerText(), "Unavailable");
  await page.locator("#map-metric").selectOption("units_5_plus");
  assert.equal((await fills())["49049"], "#ff4b35");
  await page.locator("#year-filter").selectOption("2025");
  await page.locator("#map-metric").selectOption("units");
  await page.locator("#county-filter").selectOption("49035");
  await page.locator("#map-view-compare").click();
  assert.equal(new URL(page.url()).searchParams.has("view"), false);
  assert.deepEqual(await fills(), original, "Compare must restore every original quantitative bin exactly.");
  assert.deepEqual(await metrics(), originalMetrics);
  await page.locator("#map-view-focus").click();
  await page.screenshot({ path: path.join(output, `${engine}-${width}-focus.png`), fullPage: true });
  await page.locator("#reset-county").click();
  assert.equal(await page.locator("#county-filter").inputValue(), "all");
  assert.ok(Object.values(await fills()).every(fill => fill === "#cbd0d6"));
  assert.match(await page.locator("#map-view-note").innerText(), /Choose a county/);
  assert.equal(await page.locator("#metric-units").innerText(), format(sum(2025)));
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  const downloadEvent = page.waitForEvent("download");
  await page.locator("#download-data").click();
  const download = await downloadEvent;
  assert.deepEqual(JSON.parse(fs.readFileSync(await download.path())), served);
  const invalid = new URL(base.href); invalid.searchParams.set("view", "invalid");
  await page.goto(invalid.href);
  await page.locator("#application").waitFor({ state: "visible" });
  assert.equal(await page.locator("#map-view-compare").getAttribute("aria-pressed"), "true");
  assert.equal(new URL(page.url()).searchParams.has("view"), false);
  results.push({ group: "map_views", engine, width, selection: "only one orange county", compare: "all original quantity fills restored", url_restore: true, keyboard: true, missing_values: "hatched", download: "exact snapshot", passed: true });
}

async function contractCases(browser, engine) {
  for (const [name, mutate] of Object.entries(negative)) {
    const value = clone(); mutate(value);
    const page = await browser.newPage({ reducedMotion: "reduce" });
    const errors = []; page.on("pageerror", error => errors.push(error.message));
    await open(page, value);
    assert.equal(await page.locator("#application").isVisible(), false, name);
    assert.equal(await page.locator("#load-error").isVisible(), true, name);
    assert.deepEqual(errors, [], name);
    results.push({ group: "controlled_contract", engine, case: name, result: "withheld_with_readable_error", passed: true });
    await page.close();
  }
  for (const width of [1440, 390, 320]) {
    const value = clone(); value.annual.find(row => row.year === 2025).units = null;
    value.quality.status = "needs_attention";
    value.quality.checks.find(check => check.name === "known_unit_counts").passed = false;
    const page = await browser.newPage({ viewport: { width, height: 1100 }, reducedMotion: "reduce" });
    await open(page, value);
    await page.locator("#application").waitFor({ state: "visible" });
    assert.equal(await page.locator("#metric-units").innerText(), "Not reported");
    assert.equal(await page.locator("#metric-change").innerText(), "Unavailable");
    assert.equal(await page.locator("#quality-summary").innerText(), "Needs attention");
    assert.ok((await page.locator("#quality-summary").getAttribute("class")).includes("attention"));
    const headerBounds = await page.evaluate(() => {
      const textBounds = id => {
        const range = document.createRange(); range.selectNodeContents(document.getElementById(id));
        const box = range.getBoundingClientRect();
        return { left: box.left, right: box.right };
      };
      return { units: textBounds("statewide-units"), buildings: textBounds("statewide-buildings") };
    });
    assert.ok(headerBounds.units.right <= headerBounds.buildings.left, "Unknown statewide totals must not overlap their neighboring metric.");
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    const unknownCounty = value.annual.find(row => row.year === 2025 && row.units === null).geoid;
    await page.locator("#county-filter").selectOption(unknownCounty);
    await page.locator("#map-view-focus").click();
    assert.equal(await page.locator(`.county-path[data-geoid="${unknownCounty}"]`).getAttribute("fill"), "url(#missing-fill)");
    assert.equal(await page.locator("#metric-units").innerText(), "Not reported");
    assert.equal(await page.locator("#quality-summary").innerText(), "Needs attention");
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    results.push({ group: "controlled_contract", engine, width, case: "honest_unknown_needs_attention", passed: true });
    await page.close();
  }
  const compatible = {
    optional_fields_absent: value => {
      for (const source of value.sources) { delete source.year; delete source.row_count; delete source.county_rows; }
      for (const row of value.annual) delete row.basis;
      delete value.metadata.synthetic; delete value.operations; delete value.quality.checks;
    },
    explicit_synthetic_partial_coverage: value => {
      value.metadata.synthetic = true;
      value.annual = value.annual.filter(row => ["49001", "49003"].includes(row.geoid));
      for (const source of value.sources) source.row_count = 2;
    },
  };
  for (const [name, mutate] of Object.entries(compatible)) {
    const value = clone(); mutate(value);
    const page = await browser.newPage(); await open(page, value);
    await page.locator("#application").waitFor({ state: "visible" });
    if (value.metadata.synthetic) assert.equal((await page.locator(".snapshot-tag").textContent()).trim(), "Synthetic engineering fixture");
    results.push({ group: "controlled_contract", engine, case: name, passed: true });
    await page.close();
  }
}

async function loadingCases(browser) {
  const page = await browser.newPage(); let attempts = 0;
  await page.route("**/data/housing.json", route => ++attempts === 1
    ? route.fulfill({ status: 503, body: "Controlled unavailable response" }) : route.fulfill({ json: payload }));
  await open(page);
  assert.equal(await page.locator("#load-error").isVisible(), true);
  await page.locator("#retry-load").click();
  await page.locator("#application").waitFor({ state: "visible" });
  results.push({ group: "loading", case: "HTTP failure then retry", passed: true }); await page.close();
  const duplicate = clone(); duplicate.annual.push(duplicate.annual[0]);
  const dup = await browser.newPage(); await open(dup, duplicate);
  assert.equal(await dup.locator("#application").isVisible(), false);
  assert.ok((await dup.locator("#load-error-message").innerText()).includes("duplicate"));
  results.push({ group: "loading", case: "duplicate county/year withheld", passed: true }); await dup.close();
  const missing = await browser.newPage();
  await missing.route("**/data/utah-counties.geojson", route => route.fulfill({ status: 404, body: "Controlled missing geometry" }));
  await open(missing);
  await missing.locator("#application").waitFor({ state: "visible" });
  assert.equal(await missing.locator("#county-table tr").count(), 29);
  assert.ok((await missing.locator("#county-map").innerText()).includes("could not be loaded"));
  await missing.locator("#map-view-focus").click();
  assert.ok((await missing.locator("#county-map").innerText()).includes("could not be loaded"));
  assert.match(await missing.locator("#map-view-note").innerText(), /map is unavailable/);
  assert.equal(await missing.locator("#county-table tr").count(), 29);
  assert.equal(await missing.locator('a[href="#source-geometry"]').isVisible(), false);
  results.push({ group: "loading", case: "missing geometry retains table", passed: true }); await missing.close();
}

(async () => {
  for (const engine of [chromium, webkit]) {
    const browser = await engine.launch();
    try {
      for (const width of [1440, 390, 320]) await actualWorkflow(browser, engine.name(), width);
      await contractCases(browser, engine.name());
      if (engine === chromium) await loadingCases(browser);
    } finally { await browser.close(); }
  }
  const receipt = { status: "passed", snapshot_sha256: crypto.createHash("sha256").update(snapshot).digest("hex"),
    scope: "Actual snapshot workflows plus controlled in-browser mutations; no source files or database data modified.",
    checks: results.length, results };
  fs.writeFileSync(path.join(output, "checks.json"), JSON.stringify(receipt, null, 2) + "\n");
  console.log(JSON.stringify({ status: receipt.status, checks: receipt.checks, artifacts: output }));
})().catch(error => { console.error(error); process.exitCode = 1; });
