# Sources and metric definitions

[Census Building Permits Survey](https://www.census.gov/construction/bps/index.html) reports privately owned residential construction authorized by building permits. This project reads the public annual county files `co2021a.txt` through `co2025a.txt` from the [county download directory](https://www2.census.gov/econ/bps/County/).

The [county ASCII specification](https://www2.census.gov/econ/bps/Documentation/cntyasc.pdf) defines two header rows and 30 columns. The first four structure categories carry estimates for buildings, units and valuation. Reported-only categories are retained separately, **not added again** to those estimates. A two-unit building is one building and two units. The annual date is the reference year; do not combine annual, YTD or monthly observations.

Utah has state FIPS `49`; county identifiers retain leading zeroes. Every published year must contain the expected 29 unique counties. County valuation is in dollars. Independently published [state annual files](https://www2.census.gov/econ/bps/State/) use `YYYY99` annual dates and valuation in thousands of dollars; see the [state specification](https://www2.census.gov/econ/bps/Documentation/stateasc.pdf). State and county unit totals agree for the captured years. Valuation rounding differences are in the verification receipt.

The independent reader performs nine comparisons per county-year: three category-summed totals, four category unit counts, the county name and the original-file fingerprint. That is 1,305 comparisons across 145 records; it is not 1,305 separate raw numeric cells.

The dashboard's county geometry comes from Census TIGERweb. Its complete query, retrieval time and raw-response fingerprint are embedded in `web/data/utah-counties.geojson`. The response does not establish a specific vintage year; no vintage is invented. Geometry was generalized for display and is unrelated to the permit counts.

Annual change uses the previous published year for the same county (or statewide total). Where no prior year exists or the prior total is zero, the UI displays unavailable. The five-plus share divides units in buildings with five or more units by all authorized units. All metrics derive from captured source counts; no AI model estimates missing observations.
