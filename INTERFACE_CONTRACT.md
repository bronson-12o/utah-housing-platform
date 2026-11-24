# Integration contract v1

Runtime Python package: `src/utah_housing`. Command: `python -m utah_housing`. PostgreSQL is the operational warehouse. SQLite may be a test/fixture-only convenience, never advertised as tested PostgreSQL. The dashboard must also work from a frozen verified public JSON export with no backend/account.

Candidate export path `web/data/housing.json`, served relative to a self-contained static `web/index.html` and integrated unchanged into the portfolio. Data is sourced from county Census BPS files (annual 2021–2025 first; add a bounded recent monthly period only when correctly parsed). JSON contract:

`{metadata:{generated_at, title, source_urls, periods, semantics, validation, freshness_note}, annual:[{year,state_fips,county_fips,geoid,county_name,buildings,units,valuation_usd,units_1,units_2,units_3_4,units_5_plus,source_sha256}], sources:[{url,sha256,retrieved_at,period,basis}], quality:{checks:[],status}, operations:{...}}`. Values may be null if unknown; validation cannot silently coerce. Annual rows have unique `(year,geoid)`. County identifiers remain strings with zeroes. No mixed YTD/monthly sums. Additional fields are backward-compatible.

UI owner owns web/index.html,web/app.js,web/styles.css and any generated map geometry in web/data/utah-counties.geojson. Pipeline owner owns JSON export housing.json. Root owns Docker/deploy/docs and generated architecture/schema figures. Browser export must carry concrete source/validation metadata, real results and limitations; simulated run histories cannot be presented as actual operations.

Initial business question: how have housing units authorized changed across Utah counties? Annual chart, county comparison, building-type mix, source details and job/quality status. Optional API enrichment is excluded until a free key is supplied.
