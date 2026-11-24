CREATE TABLE IF NOT EXISTS housing_runs (
    run_id uuid PRIMARY KEY,
    command text NOT NULL,
    period integer,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    status text NOT NULL CHECK (status IN ('running','succeeded','noop','failed')),
    source_sha256 text,
    version_id uuid,
    rows_loaded integer NOT NULL DEFAULT 0,
    changed_rows integer NOT NULL DEFAULT 0,
    error text,
    synthetic boolean NOT NULL DEFAULT false
);
CREATE TABLE IF NOT EXISTS housing_source_versions (
    version_id uuid PRIMARY KEY,
    year integer NOT NULL,
    basis text NOT NULL CHECK (basis='annual'),
    sha256 char(64) NOT NULL,
    url text NOT NULL,
    retrieved_at timestamptz NOT NULL,
    accepted_at timestamptz NOT NULL DEFAULT now(),
    raw_bytes bigint NOT NULL,
    county_rows integer NOT NULL,
    national_rows integer NOT NULL,
    missing_values integer NOT NULL,
    synthetic boolean NOT NULL DEFAULT false,
    active boolean NOT NULL DEFAULT true,
    accepted_run_id uuid NOT NULL REFERENCES housing_runs(run_id),
    UNIQUE(year,basis,sha256,synthetic)
);
CREATE UNIQUE INDEX IF NOT EXISTS housing_one_active_source
ON housing_source_versions(year,basis,synthetic) WHERE active;
CREATE TABLE IF NOT EXISTS housing_county_annual (
    year integer NOT NULL,
    geoid char(5) NOT NULL,
    synthetic boolean NOT NULL DEFAULT false,
    county_name text NOT NULL,
    buildings bigint,
    units bigint,
    valuation_usd bigint,
    row_data jsonb NOT NULL,
    source_version_id uuid NOT NULL REFERENCES housing_source_versions(version_id),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(year,geoid,synthetic)
);
CREATE TABLE IF NOT EXISTS housing_county_history (
    version_id uuid NOT NULL REFERENCES housing_source_versions(version_id),
    geoid char(5) NOT NULL,
    row_data jsonb NOT NULL,
    PRIMARY KEY(version_id,geoid)
);
