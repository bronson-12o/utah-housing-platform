"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const NS = "http://www.w3.org/2000/svg";
  const number = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
  const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
  const percentage = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });
  const sequential = ["#e8eee0", "#bed5ba", "#88b18b", "#4d875f", "#235a41"];
  const divergent = ["#c38b51", "#dfc6a3", "#e8eee0", "#92b68c", "#3f7d55"];
  const categoryLabels = [
    ["units_1", "1-unit buildings"],
    ["units_2", "2-unit buildings"],
    ["units_3_4", "3–4-unit buildings"],
    ["units_5_plus", "5+ unit buildings"],
  ];
  const countyFips = new Set(Array.from({ length: 29 }, (_, index) => String(index * 2 + 1).padStart(3, "0")));
  const displayedMetrics = ["buildings", "units", "valuation_usd", ...categoryLabels.map(([key]) => key)];
  let dataset = null;
  let geometry = null;
  let years = [];
  let countyNames = new Map();
  let rowsByKey = new Map();
  let state = { year: null, county: "all", metric: "units" };

  function element(tag, attributes = {}, text) {
    const item = document.createElement(tag);
    for (const [key, value] of Object.entries(attributes)) item.setAttribute(key, String(value));
    if (text !== undefined) item.textContent = String(text);
    return item;
  }
  function svg(tag, attributes = {}, text) {
    const item = document.createElementNS(NS, tag);
    for (const [key, value] of Object.entries(attributes)) item.setAttribute(key, String(value));
    if (text !== undefined) item.textContent = String(text);
    return item;
  }
  function format(value) {
    return value === null || value === undefined ? "Not reported" : number.format(value);
  }
  function percent(value, sign = false) {
    if (value === null || !Number.isFinite(value)) return "Unavailable";
    return `${sign && value > 0 ? "+" : ""}${percentage.format(value)}%`;
  }
  function date(value) {
    if (!value) return "Not recorded";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime())
      ? String(value)
      : new Intl.DateTimeFormat("en-US", {
          year: "numeric",
          month: "short",
          day: "numeric",
          timeZone: "UTC",
        }).format(parsed);
  }
  function safeUrl(value) {
    try {
      const url = new URL(value);
      return ["http:", "https:"].includes(url.protocol) ? url.href : null;
    } catch {
      return null;
    }
  }
  function validateSnapshot(value) {
    const record = (item) => item !== null && typeof item === "object" && !Array.isArray(item);
    if (
      !record(value) ||
      !Array.isArray(value.annual) ||
      !value.annual.length ||
      !record(value.metadata) ||
      !Array.isArray(value.sources)
    )
      throw new Error("The export is missing its annual records or source metadata.");
    const quality = value.quality;
    if (!record(quality) || !["passed", "needs_attention"].includes(quality.status) ||
        (quality.checks !== undefined && !Array.isArray(quality.checks)))
      throw new Error("The export is missing a readable validation receipt.");
    for (const check of quality.checks ?? []) {
      if (!record(check) || typeof check.name !== "string" || typeof check.passed !== "boolean" ||
          typeof check.detail !== "string" || (quality.status === "passed" && !check.passed))
        throw new Error("The validation status conflicts with its recorded checks.");
    }
    if ((value.metadata.synthetic !== undefined && typeof value.metadata.synthetic !== "boolean") ||
        !Array.isArray(value.metadata.periods) || !value.metadata.periods.every(Number.isInteger))
      throw new Error("The export has invalid reference periods or a missing data-type label.");
    if (value.operations !== undefined && (!record(value.operations) ||
        (value.operations.runs !== undefined && !Array.isArray(value.operations.runs)) ||
        !(value.operations.runs ?? []).every(record)))
      throw new Error("The captured run receipt is not readable.");
    const sourcePeriods = new Set(), bindings = new Set();
    for (const source of value.sources) {
      if (!record(source) || source.basis !== "annual" || typeof source.url !== "string" || !source.url ||
          typeof source.retrieved_at !== "string" || typeof source.sha256 !== "string" || !/^[a-f0-9]{64}$/.test(source.sha256) ||
          !["string", "number"].includes(typeof source.period) || !/^\d{4}$/.test(String(source.period)) || sourcePeriods.has(Number(source.period)) ||
          (source.year !== undefined && (!Number.isInteger(source.year) || source.year !== Number(source.period))))
        throw new Error("An original-source receipt has an invalid or conflicting annual reference period.");
      sourcePeriods.add(Number(source.period));
      bindings.add(`${source.period}/${source.sha256}`);
    }
    const completeSum = (values) => {
      if (values.some((item) => item === null)) return null;
      const sum = values.reduce((total, item) => total + item, 0);
      if (!Number.isSafeInteger(sum))
        throw new Error("The export contains a total too large to display exactly.");
      return sum;
    };
    const keys = new Set();
    for (const row of value.annual) {
      if (
        !record(row) ||
        !Number.isInteger(row.year) ||
        row.year < 2000 || row.year > 2100 ||
        row.state_fips !== "49" ||
        !countyFips.has(row.county_fips) ||
        row.geoid !== row.state_fips + row.county_fips ||
        (row.basis !== undefined && row.basis !== "annual") ||
        typeof row.county_name !== "string" ||
        !row.county_name.trim()
      )
        throw new Error("The export contains an invalid annual reporting year or Utah county identifier.");
      const key = `${row.year}/${row.geoid}`;
      if (keys.has(key))
        throw new Error(
          "The export contains duplicate county/year records; this view has been withheld.",
        );
      keys.add(key);
      for (const field of displayedMetrics) {
        if (row[field] !== null && (!Number.isSafeInteger(row[field]) || row[field] < 0))
          throw new Error(
            `The export has an invalid ${field} value. Missing data must stay separate from zero.`,
          );
        if (quality.status === "passed" && row[field] === null)
          throw new Error("The export declares passed checks but contains an unknown displayed value.");
      }
      if (!bindings.has(`${row.year}/${row.source_sha256}`))
        throw new Error("An annual record does not match its original-source fingerprint and reporting year.");
      const components = completeSum(categoryLabels.map(([field]) => row[field]));
      if (components !== null && row.units !== null && components !== row.units)
        throw new Error("The building-type unit counts do not reconcile with the annual total.");
    }
    const annualPeriods = [...new Set(value.annual.map((row) => row.year))].sort((a, b) => a - b);
    if (JSON.stringify(value.metadata.periods) !== JSON.stringify(annualPeriods) ||
        JSON.stringify([...sourcePeriods].sort((a, b) => a - b)) !== JSON.stringify(annualPeriods))
      throw new Error("The county records and source receipts cover different reporting years.");
    for (const year of annualPeriods) {
      const rows = value.annual.filter((row) => row.year === year);
      if (!value.metadata.synthetic && rows.length !== countyFips.size)
        throw new Error("A real annual export must contain all 29 Utah counties.");
      for (const field of displayedMetrics) completeSum(rows.map((row) => row[field]));
      const source = value.sources.find((item) => Number(item.period) === year);
      for (const field of ["row_count", "county_rows"]) {
        if (source[field] !== undefined && (!Number.isInteger(source[field]) || source[field] !== rows.length))
          throw new Error("An original-source record count does not match the published county records.");
      }
    }
    return value;
  }
  function rowsFor(year, county = state.county) {
    return dataset.annual.filter(
      (row) => row.year === year && (county === "all" || row.geoid === county),
    );
  }
  function total(rows, field) {
    if (!rows.length || rows.some((row) => row[field] === null || row[field] === undefined))
      return null;
    const value = rows.reduce((sum, row) => sum + row[field], 0);
    return Number.isSafeInteger(value) ? value : null;
  }
  function yearChange(year, county) {
    const current = rowsFor(year, county),
      prior = rowsFor(year - 1, county);
    const currentIds = new Set(current.map((row) => row.geoid));
    if (
      !current.length ||
      current.length !== prior.length ||
      prior.some((row) => !currentIds.has(row.geoid))
    )
      return null;
    const now = total(current, "units"),
      before = total(prior, "units");
    return now === null || before === null || before === 0 ? null : ((now - before) / before) * 100;
  }
  function share(rows) {
    const units = total(rows, "units"),
      multi = total(rows, "units_5_plus");
    return units === null || units === 0 || multi === null ? null : (multi / units) * 100;
  }
  function geography() {
    return state.county === "all" ? "Utah" : countyNames.get(state.county);
  }
  function metricValue(row) {
    return !row
      ? null
      : state.metric === "change"
        ? yearChange(state.year, row.geoid)
        : row[state.metric];
  }
  function metricLabel() {
    return {
      units: "Units authorized",
      change: "Change from prior year",
      units_5_plus: "Units in 5+ unit buildings",
    }[state.metric];
  }
  function metricFormatted(value) {
    return state.metric === "change" ? percent(value, true) : format(value);
  }

  function setupFilters() {
    years = [...new Set(dataset.annual.map((row) => row.year))].sort((a, b) => a - b);
    countyNames = new Map(dataset.annual.map((row) => [row.geoid, row.county_name]));
    rowsByKey = new Map(dataset.annual.map((row) => [`${row.year}/${row.geoid}`, row]));
    $("year-filter").replaceChildren(
      ...years.map((year) => element("option", { value: year }, year)),
    );
    $("county-filter").replaceChildren(
      element("option", { value: "all" }, "All Utah counties"),
      ...[...countyNames]
        .sort((a, b) => a[1].localeCompare(b[1]))
        .map(([id, name]) => element("option", { value: id }, name)),
    );
    const params = new URLSearchParams(window.location.search);
    state.year = years.includes(Number(params.get("year")))
      ? Number(params.get("year"))
      : years.at(-1);
    state.county = countyNames.has(params.get("county")) ? params.get("county") : "all";
    state.metric = ["units", "change", "units_5_plus"].includes(params.get("metric"))
      ? params.get("metric")
      : "units";
    $("year-filter").value = String(state.year);
    $("county-filter").value = state.county;
    $("map-metric").value = state.metric;
    $("coverage-label").textContent = `${years[0]}–${years.at(-1)} · annual county records`;
    $("year-filter").onchange = (event) => {
      state.year = Number(event.target.value);
      render();
    };
    $("county-filter").onchange = (event) => {
      state.county = event.target.value;
      render();
    };
    $("map-metric").onchange = (event) => {
      state.metric = event.target.value;
      render();
    };
    $("reset-county").onclick = () => selectCounty("all");
    $("download-data").onclick = () => {
      const blob = new Blob([JSON.stringify(dataset, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob),
        link = element("a", {
          href: url,
          download: `utah-housing-${years[0]}-${years.at(-1)}-snapshot.json`,
        });
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    };
  }
  function selectCounty(id) {
    state.county = id;
    $("county-filter").value = id;
    render();
  }
  function renderSummary() {
    const selected = rowsFor(state.year),
      units = total(selected, "units"),
      change = yearChange(state.year, state.county);
    $("metric-units").textContent = format(units);
    const countyCount = rowsFor(state.year, "all").length;
    $("metric-units-note").textContent =
      state.county === "all" && countyCount !== 29
        ? `${countyCount}/29 counties in export; partial coverage`
        : "Residential units, not completed homes";
    $("metric-change").textContent = percent(change, true);
    $("metric-change").classList.toggle("negative", change !== null && change < 0);
    $("metric-change-note").textContent =
      change === null
        ? `No comparable nonzero ${state.year - 1} total`
        : `Compared with annual ${state.year - 1}`;
    $("metric-buildings").textContent = format(total(selected, "buildings"));
    $("metric-multifamily").textContent = percent(share(selected));
    $("metric-multifamily-note").textContent =
      `${format(total(selected, "units_5_plus"))} units in 5+ unit buildings`;
    $("filter-context").textContent =
      `${geography()} · ${state.year} annual construction authorizations · ${state.county === "all" ? countyCount + " counties" : "County FIPS " + state.county}`;
    $("filter-announcement").textContent =
      `${geography()}, ${state.year}: ${format(units)} units authorized.`;
    $("map-year").textContent = String(state.year);
  }
  function mapScale() {
    const values = rowsFor(state.year, "all")
      .map(metricValue)
      .filter((value) => value !== null && Number.isFinite(value));
    if (!values.length)
      return { color: () => "url(#missing-fill)", min: null, max: null, colors: sequential };
    if (state.metric === "change") {
      const bound = Math.max(...values.map(Math.abs), 1);
      return {
        min: -bound,
        max: bound,
        colors: divergent,
        color: (value) =>
          value === null
            ? "url(#missing-fill)"
            : divergent[Math.min(4, Math.floor(((value + bound) / (bound * 2)) * 5))],
      };
    }
    const sorted = [...values].sort((a, b) => a - b);
    if (sorted[0] === sorted.at(-1))
      return {
        min: sorted[0],
        max: sorted[0],
        equal: true,
        colors: sequential,
        color: (value) =>
          value === null ? "url(#missing-fill)" : sequential[sorted[0] === 0 ? 0 : 2],
      };
    const thresholds = [0.2, 0.4, 0.6, 0.8].map(
      (fraction) => sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * fraction))],
    );
    return {
      min: sorted[0],
      max: sorted.at(-1),
      colors: sequential,
      color: (value) =>
        value === null
          ? "url(#missing-fill)"
          : sequential[thresholds.filter((threshold) => value >= threshold).length],
    };
  }
  function geometryRings(feature) {
    if (feature.geometry?.type === "Polygon") return feature.geometry.coordinates;
    if (feature.geometry?.type === "MultiPolygon") return feature.geometry.coordinates.flat();
    return [];
  }
  function validGeometry(value) {
    if (value?.type !== "FeatureCollection" || value.features?.length !== 29) return false;
    const ids = new Set();
    for (const feature of value.features) {
      const id = feature.properties?.GEOID;
      if (typeof id !== "string" || !/^49\d{3}$/.test(id) || ids.has(id)) return false;
      ids.add(id);
      const rings = geometryRings(feature);
      if (!rings.length || rings.some((ring) => !Array.isArray(ring) || ring.length < 4))
        return false;
      for (const ring of rings) {
        for (const point of ring) {
          if (
            !Array.isArray(point) ||
            !Number.isFinite(point[0]) ||
            !Number.isFinite(point[1]) ||
            point[0] < -115 ||
            point[0] > -108 ||
            point[1] < 36 ||
            point[1] > 43
          )
            return false;
        }
      }
    }
    return dataset.annual.every((row) => ids.has(row.geoid));
  }
  function renderMap() {
    const host = $("county-map");
    if (!geometry) {
      host.replaceChildren(
        element(
          "p",
          { class: "map-empty" },
          "The county boundary file could not be loaded. All data remain available in the table below.",
        ),
      );
      return;
    }
    const rings = geometry.features.flatMap(geometryRings),
      points = rings.flat();
    const minX = Math.min(...points.map((point) => point[0])),
      maxX = Math.max(...points.map((point) => point[0]));
    const minY = Math.min(...points.map((point) => point[1])),
      maxY = Math.max(...points.map((point) => point[1]));
    const cosine = Math.cos((((minY + maxY) / 2) * Math.PI) / 180);
    const width = (maxX - minX) * cosine,
      height = maxY - minY,
      factor = Math.min(395 / width, 470 / height);
    const project = (point) => [
      22 + (point[0] - minX) * cosine * factor,
      12 + (maxY - point[1]) * factor,
    ];
    const map = svg("svg", {
      viewBox: `0 0 ${width * factor + 44} ${height * factor + 24}`,
      role: "group",
      "aria-label": `${metricLabel()} by Utah county, ${state.year}`,
    });
    const definitions = svg("defs"),
      pattern = svg("pattern", {
        id: "missing-fill",
        patternUnits: "userSpaceOnUse",
        width: 6,
        height: 6,
        patternTransform: "rotate(45)",
      });
    pattern.append(
      svg("rect", { width: 6, height: 6, fill: "#6c806e" }),
      svg("line", { x1: 0, y1: 0, x2: 0, y2: 6, stroke: "#99aa96", "stroke-width": 2 }),
    );
    definitions.append(pattern);
    map.append(definitions);
    const scale = mapScale();
    for (const feature of geometry.features) {
      const id = String(feature.properties.GEOID),
        name = countyNames.get(id) || feature.properties.NAME;
      const row = rowsByKey.get(`${state.year}/${id}`),
        value = metricValue(row);
      const pathData = geometryRings(feature)
        .map(
          (ring) =>
            ring
              .map(
                (point, index) =>
                  `${index ? "L" : "M"}${project(point)
                    .map((n) => n.toFixed(2))
                    .join(",")}`,
              )
              .join("") + "Z",
        )
        .join("");
      const path = svg("path", {
        d: pathData,
        fill: scale.color(value),
        class: `county-path${state.county === id ? " selected" : ""}`,
        tabindex: 0,
        role: "button",
        "aria-label": `${name}: ${metricLabel()}, ${metricFormatted(value)}. Select county.`,
        "aria-pressed": state.county === id ? "true" : "false",
        "data-geoid": id,
      });
      path.append(svg("title", {}, `${name} · ${metricFormatted(value)}`));
      path.addEventListener("click", () => selectCounty(id));
      path.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          selectCounty(id);
          $("county-filter").focus();
        }
      });
      path.addEventListener("mouseenter", () => showMapInsight(id));
      path.addEventListener("focus", () => showMapInsight(id));
      map.append(path);
    }
    host.replaceChildren(map);
    showMapInsight(state.county);
    const label = element(
      "p",
      {},
      scale.equal
        ? "All counties report the same value"
        : state.metric === "change"
          ? "Diverging scale · prior-year %"
          : "Relative scale · county quintiles",
    );
    const ramp = element("div", { class: "legend-ramp", "aria-hidden": "true" });
    scale.colors.forEach((color) => {
      const swatch = element("span");
      swatch.style.background = color;
      ramp.append(swatch);
    });
    const limits = element("div", { class: "legend-limits" });
    limits.append(
      element(
        "span",
        {},
        scale.min === null
          ? "No data"
          : state.metric === "change"
            ? percent(scale.min)
            : compact.format(scale.min),
      ),
      element(
        "span",
        {},
        scale.max === null
          ? ""
          : state.metric === "change"
            ? percent(scale.max)
            : compact.format(scale.max),
      ),
    );
    const missing = element("div", { class: "missing-legend" });
    missing.append(
      element("span", { "aria-hidden": "true" }),
      document.createTextNode("Unavailable / not reported"),
    );
    $("map-legend").replaceChildren(label, ramp, limits, missing);
    $("reset-county").hidden = state.county === "all";
  }
  function showMapInsight(id) {
    const county = id === "all" ? null : rowsByKey.get(`${state.year}/${id}`);
    const host = $("map-insight");
    host.replaceChildren(
      element("strong", {}, id === "all" ? "Utah" : countyNames.get(id) || "County"),
      element(
        "span",
        {},
        county
          ? `${metricFormatted(metricValue(county))}\n${metricLabel()}`
          : id === "all"
            ? "Hover, focus, or select a county."
            : "No record for this reporting year.",
      ),
    );
  }
  function renderTrend() {
    $("trend-heading").textContent =
      state.county === "all" ? "Utah, over time." : `${geography()}, over time.`;
    const values = years.map((year) => ({ year, value: total(rowsFor(year), "units") })),
      finite = values.filter((item) => item.value !== null);
    if (!finite.length) {
      $("trend-chart").replaceChildren(
        element(
          "p",
          { class: "empty-chart" },
          "No complete annual totals are available for this selection.",
        ),
      );
      return;
    }
    const width = 460,
      height = 182,
      left = 45,
      right = 15,
      top = 16,
      bottom = 30,
      chartWidth = width - left - right,
      chartHeight = height - top - bottom;
    const max = Math.max(...finite.map((item) => item.value), 1) * 1.1;
    const x = (index) =>
        left + (values.length === 1 ? chartWidth / 2 : (index / (values.length - 1)) * chartWidth),
      y = (value) => top + (1 - value / max) * chartHeight;
    const chart = svg("svg", {
      viewBox: `0 0 ${width} ${height}`,
      role: "img",
      "aria-label":
        `${geography()} annual units authorized: ` +
        values.map((item) => `${item.year}, ${format(item.value)}`).join("; "),
    });
    for (let i = 0; i <= 3; i++) {
      const value = (max * i) / 3,
        py = y(value);
      chart.append(
        svg("line", { x1: left, y1: py, x2: width - right, y2: py, class: "chart-grid" }),
        svg(
          "text",
          { x: left - 8, y: py + 3, "text-anchor": "end", class: "chart-axis" },
          compact.format(value),
        ),
      );
    }
    let segments = [],
      segment = [];
    values.forEach((item, index) => {
      if (item.value === null) {
        if (segment.length) segments.push(segment);
        segment = [];
      } else segment.push([x(index), y(item.value)]);
    });
    if (segment.length) segments.push(segment);
    for (const points of segments) {
      const line = points.map((point, index) => `${index ? "L" : "M"}${point.join(",")}`).join(" ");
      if (points.length > 1) {
        const area = line + ` L${points.at(-1)[0]},${y(0)} L${points[0][0]},${y(0)} Z`;
        chart.append(
          svg("path", { d: area, fill: "#e4eddf" }),
          svg("path", { d: line, fill: "none", stroke: "#2d6c4e", "stroke-width": 2.3 }),
        );
      }
    }
    values.forEach((item, index) => {
      chart.append(
        svg(
          "text",
          { x: x(index), y: height - 8, "text-anchor": "middle", class: "chart-axis" },
          item.year,
        ),
      );
      if (item.value !== null) {
        const dot = svg("circle", { cx: x(index), cy: y(item.value), r: 4, class: "trend-point" });
        dot.append(svg("title", {}, `${item.year}: ${format(item.value)} units authorized`));
        chart.append(dot);
      }
    });
    $("trend-chart").replaceChildren(chart);
  }
  function renderMix() {
    const rows = rowsFor(state.year),
      unitTotal = total(rows, "units"),
      values = categoryLabels.map(([key, label]) => ({ label, value: total(rows, key) }));
    const children = values.map((item, index) => {
      const row = element("div", { class: "mix-row" });
      row.append(element("span", { class: "mix-label" }, item.label));
      const track = element("div", { class: "mix-track", "aria-hidden": "true" }),
        fill = element("span", { class: "mix-fill" });
      fill.style.width =
        item.value === null || !unitTotal
          ? "0%"
          : Math.min(100, (item.value / unitTotal) * 100) + "%";
      fill.style.background = ["#235e43", "#5f8964", "#9db895", "#c3a567"][index];
      track.append(fill);
      row.append(
        track,
        element(
          "span",
          { class: item.value === null ? "mix-value mix-null" : "mix-value" },
          item.value === null ? "Unknown" : format(item.value),
        ),
      );
      return row;
    });
    if (
      values.every((item) => item.value !== null) &&
      unitTotal !== null &&
      values.reduce((sum, item) => sum + item.value, 0) !== unitTotal
    )
      children.push(
        element(
          "p",
          { class: "chart-note" },
          "Category values do not reconcile with the reported total; inspect the source records.",
        ),
      );
    $("mix-chart").replaceChildren(...children);
  }
  function renderTable() {
    const rows = rowsFor(state.year, "all").sort(
      (a, b) => (b.units ?? -1) - (a.units ?? -1) || a.county_name.localeCompare(b.county_name),
    );
    $("county-table").replaceChildren(
      ...rows.map((row, index) => {
        const tr = element("tr", { class: state.county === row.geoid ? "selected" : "" }),
          name = element("td"),
          button = element("button", {
            type: "button",
            class: "county-button",
            "aria-pressed": state.county === row.geoid ? "true" : "false",
            "data-geoid": row.geoid,
          });
        button.append(
          element(
            "span",
            { class: "county-rank", "aria-hidden": "true" },
            String(index + 1).padStart(2, "0"),
          ),
          document.createTextNode(row.county_name),
        );
        button.onclick = (event) => {
          selectCounty(row.geoid);
          if (event.detail === 0) $("county-filter").focus();
        };
        name.append(button);
        tr.append(name);
        const change = yearChange(state.year, row.geoid);
        tr.append(
          element("td", {}, format(row.units)),
          element(
            "td",
            { class: change !== null && change < 0 ? "change-negative" : "" },
            percent(change, true),
          ),
          element("td", {}, format(row.buildings)),
          element("td", {}, percent(share([row]))),
        );
        return tr;
      }),
    );
    $("table-footnote").textContent =
      `${rows.length} county records in ${state.year}. A dash or unavailable value is not a reported zero. County comparisons are not adjusted for population or land area.`;
  }
  function renderProvenance() {
    const checkLabels = {
      published_rows: "Published county/year records",
      unique_grain: "Unique county and year",
      source_bindings: "Original-source links",
      known_unit_counts: "Missing values stay missing",
      known_display_metrics: "Displayed metrics are available",
      source_row_counts: "Source record counts reconcile",
      component_reconciliation: "Building-type totals reconcile",
      annual_only: "Consistent annual scope",
      county_coverage: "Complete county coverage",
    };
    const quality = dataset.quality || {},
      checks = Array.isArray(quality.checks) ? quality.checks : [];
    $("quality-summary").textContent = quality.status
      ? String(quality.status)
          .replaceAll("_", " ")
          .replace(/^./, (text) => text.toUpperCase())
      : "Validation status was not supplied.";
    $("quality-summary").classList.toggle("attention", quality.status === "needs_attention");
    $("quality-checks").replaceChildren(
      ...checks.slice(0, 8).map((check) => {
        const object =
            typeof check === "object" && check !== null ? check : { name: String(check) },
          passed = object.passed === true || object.status === "passed",
          failed = object.passed === false || ["failed", "error"].includes(object.status);
        const li = element("li", { class: failed ? "failed" : "" });
        li.append(
          element(
            "span",
            { class: "check-mark", "aria-hidden": "true" },
            passed ? "✓" : failed ? "!" : "·",
          ),
          element(
            "span",
            {},
            `${checkLabels[object.name] || object.name || object.check || "Recorded check"}${object.detail ? " — " + object.detail : ""}`,
          ),
        );
        return li;
      }),
    );
    if (!checks.length)
      $("quality-checks").append(
        element("li", {}, "No individual validation receipts are included."),
      );
    if (checks.length > 8)
      $("quality-checks").append(
        element(
          "li",
          {},
          `${checks.length - 8} more checks are included in the downloadable snapshot.`,
        ),
      );
    const operations = dataset.operations || {},
      runs = Array.isArray(operations.runs) ? [...operations.runs] : [];
    runs.sort((a, b) => String(b.started_at || "").localeCompare(String(a.started_at || "")));
    const last = operations.last_run || runs[0];
    const details = [
      [
        "Export mode",
        dataset.metadata.synthetic ? "Synthetic fixture snapshot" : "Saved warehouse export",
      ],
      ["Export generated", date(dataset.metadata.generated_at)],
    ];
    if (last) {
      details.push(
        ["Last captured run", String(last.status || "Not recorded").replaceAll("_", " ")],
        ["Run finished", date(last.finished_at)],
        ["Run period", last.period ?? "Not recorded"],
      );
      if (Number.isInteger(last.rows_loaded))
        details.push(["Rows loaded in run", format(last.rows_loaded)]);
      if (last.synthetic) details.push(["Run input", "Explicit synthetic fixture"]);
    } else details.push(["Run ledger", "No captured run supplied"]);
    if (Number.isInteger(operations.active_sources))
      details.push(["Active sources", format(operations.active_sources)]);
    if (Number.isInteger(operations.accepted_source_versions))
      details.push(["Accepted source versions", format(operations.accepted_source_versions)]);
    $("run-receipt").replaceChildren(
      ...details.map(([label, value]) => {
        const row = element("div");
        row.append(element("dt", {}, label), element("dd", {}, value));
        return row;
      }),
    );
    $("source-summary").replaceChildren(
      element(
        "p",
        {},
        `${dataset.sources.length} source records · ${dataset.annual.length} county/year records`,
      ),
      element("p", {}, `Reporting years ${years[0]}–${years.at(-1)} · annual basis only`),
    );
    const sourceCards = dataset.sources.map((source) => {
      const card = element("article", { class: "source-record" }),
        url = safeUrl(source.url);
      card.append(
        url
          ? element(
              "a",
              { href: url, target: "_blank", rel: "noopener noreferrer" },
              `${source.period ?? source.year ?? "Source"} · ${source.basis || "Source file"} ↗`,
            )
          : element("strong", {}, "Source URL unavailable"),
      );
      card.append(
        element(
          "p",
          {},
          `Retrieved ${date(source.retrieved_at)}${source.row_count !== undefined ? " · " + format(source.row_count) + " rows" : ""}`,
        ),
        element("code", {}, `SHA-256 ${source.sha256 || "Not supplied"}`),
      );
      return card;
    });
    if (geometry?.source) {
      const source = geometry.source,
        url = safeUrl(source.url),
        card = element("article", { class: "source-record", id: "source-geometry" });
      card.append(
        element("strong", {}, "County boundaries"),
        element(
          "p",
          {},
          source.description || "Official Census TIGERweb boundaries, generalized for display.",
        ),
      );
      if (url)
        card.append(
          element(
            "a",
            { href: url, target: "_blank", rel: "noopener noreferrer" },
            "Open original geometry response ↗",
          ),
        );
      card.append(
        element("p", {}, `Retrieved ${date(source.retrieved_at)}`),
        element("code", {}, `Response SHA-256 ${source.response_sha256 || "Not supplied"}`),
      );
      sourceCards.push(card);
    }
    $("source-records").replaceChildren(...sourceCards);
    $("freshness-note").textContent =
      dataset.metadata.freshness_note ||
      `Latest annual reference period: ${years.at(-1)}. Source files may be revised.`;
    $("snapshot-generated").textContent =
      `Snapshot exported ${date(dataset.metadata.generated_at)} · reference period and export date are different.`;
    const repo = safeUrl(dataset.metadata.repository_url);
    if (repo) {
      $("repository-link").href = repo;
      $("repository-link").hidden = false;
    }
    if (dataset.metadata.synthetic) {
      document.querySelector(".snapshot-tag").textContent = "Synthetic engineering fixture";
      $("filter-context").setAttribute("data-synthetic", "true");
    }
  }
  function render() {
    renderSummary();
    renderMap();
    renderTrend();
    renderMix();
    renderTable();
    const url = new URL(window.location.href);
    url.searchParams.set("year", String(state.year));
    if (state.county === "all") url.searchParams.delete("county");
    else url.searchParams.set("county", state.county);
    if (state.metric === "units") url.searchParams.delete("metric");
    else url.searchParams.set("metric", state.metric);
    history.replaceState(null, "", url.pathname + url.search + url.hash);
  }
  async function load() {
    $("loading").hidden = false;
    $("load-error").hidden = true;
    $("application").hidden = true;
    const controller = new AbortController(),
      timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch("data/housing.json", {
        cache: "no-store",
        signal: controller.signal,
      });
      if (!response.ok)
        throw new Error(
          `The snapshot returned HTTP ${response.status}. Run the documented pipeline/export command or try again shortly.`,
        );
      if (!(response.headers.get("content-type") || "").includes("json"))
        throw new Error(
          "The snapshot endpoint returned a page instead of JSON. Check that the data export is present.",
        );
      dataset = validateSnapshot(await response.json());
      geometry = null;
      try {
        const boundaries = await fetch("data/utah-counties.geojson", { signal: controller.signal });
        if (boundaries.ok) {
          const candidate = await boundaries.json();
          if (validGeometry(candidate)) geometry = candidate;
        }
      } catch {
        geometry = null;
      }
      setupFilters();
      render();
      renderProvenance();
      $("application").hidden = false;
      document.querySelector('a[href="#source-geometry"]').hidden = !geometry?.source;
      document.querySelector('a[href="#source-geometry"]').onclick = (event) => {
        const target = $("source-geometry");
        if (target) {
          event.preventDefault();
          target.closest("details").open = true;
          target.scrollIntoView({ block: "center" });
        }
      };
    } catch (error) {
      $("load-error-message").textContent =
        error.name === "AbortError"
          ? "The data request took too long. Check the connection and try again."
          : error.message;
      $("load-error").hidden = false;
    } finally {
      clearTimeout(timeout);
      $("loading").hidden = true;
    }
  }
  $("retry-load").onclick = load;
  load();
})();
