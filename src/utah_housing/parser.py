"""Read the original Census county BPS two-header annual format without imputation."""
from __future__ import annotations

import csv
from dataclasses import dataclass, asdict
import hashlib
import io
import re

TOP = "Survey,FIPS,FIPS,Region,Division,County,,1-unit,,,2-units,,,3-4 units,,,5+ units,,,1-unit rep,,,2-units rep,,,3-4 units rep,,, 5+units rep"
BOTTOM = "Date,State,County,Code,Code,Name,Bldgs,Units,Value,Bldgs,Units,Value,Bldgs,Units,Value,Bldgs,Units,Value,Bldgs,Units,Value,Bldgs,Units,Value,Bldgs,Units,Value,Bldgs,Units,Value"
UTAH_COUNTIES = {f"{n:03}" for n in range(1, 58, 2)}
TYPE_NAMES = ("1", "2", "3_4", "5_plus")
MAX_EXACT_INTEGER = 9_007_199_254_740_991


class SourceError(ValueError):
    """A source failed the declared input contract; no publication is permitted."""


def integer(value: str, *, label: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    if not re.fullmatch(r"[0-9]+", value):
        raise SourceError(f"{label}: expected a nonnegative integer or blank.")
    number = int(value)
    if number > MAX_EXACT_INTEGER:
        raise SourceError(f"{label}: exceeds exact browser integer range.")
    return number


def complete_sum(values: list[int | None]) -> int | None:
    known_sum = sum(value for value in values if value is not None)
    if known_sum > MAX_EXACT_INTEGER:
        raise SourceError("Derived total exceeds exact browser integer range.")
    return known_sum if all(x is not None for x in values) else None


@dataclass(frozen=True)
class ParsedSource:
    year: int
    sha256: str
    rows: list[dict]
    national_rows: int
    missing_value_count: int


def parse_annual(raw: bytes, year: int, *, require_all_counties: bool = True) -> ParsedSource:
    if not 2000 <= year <= 2100:
        raise SourceError("Annual year must be a four-digit supported year.")
    try:
        table = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    except (UnicodeError, csv.Error) as error:
        raise SourceError("Source is not a readable UTF-8 CSV.") from error
    if len(table) < 3:
        raise SourceError("Missing two source header rows and data.")
    normalize = lambda row: [x.strip().casefold() for x in row]
    if normalize(table[0]) != normalize(next(csv.reader([TOP]))):
        raise SourceError("First BPS header does not match the annual county schema.")
    if normalize(table[1]) != normalize(next(csv.reader([BOTTOM]))):
        raise SourceError("Second BPS header does not match the annual county schema.")
    records = []
    seen = set()
    national_rows = 0
    missing = 0
    for line, row in enumerate(table[2:], 3):
        if not row or not any(x.strip() for x in row):
            continue
        if len(row) != 30:
            raise SourceError(f"Line {line}: expected 30 columns, got {len(row)}.")
        if row[0].strip() != str(year):
            raise SourceError(f"Line {line}: reference period is not annual {year}.")
        state, county = row[1].strip(), row[2].strip()
        if not re.fullmatch(r"\d{2}", state) or not re.fullmatch(r"\d{3}", county):
            raise SourceError(f"Line {line}: state/county FIPS must retain two/three digits.")
        national_rows += 1
        if state != "49":
            continue
        if county not in UTAH_COUNTIES:
            raise SourceError(f"Line {line}: unknown Utah county FIPS {county}.")
        if county in seen:
            raise SourceError(f"Line {line}: duplicate Utah county {county}.")
        seen.add(county)
        name = row[5].strip()
        if not name:
            raise SourceError(f"Line {line}: missing county name.")
        measurements = [integer(value, label=f"Line {line}, column {i}")
                        for i, value in enumerate(row[6:], 7)]
        missing += sum(value is None for value in measurements)
        record = {"year": year, "state_fips": state, "county_fips": county,
                  "geoid": state + county, "county_name": name,
                  "basis": "annual", "reported_only": {}}
        for group, category in enumerate(TYPE_NAMES):
            buildings, units, valuation = measurements[group * 3:group * 3 + 3]
            if buildings is not None and units is not None:
                if (buildings == 0) != (units == 0):
                    raise SourceError(f"Line {line}: zero buildings and zero units must agree in {category} category.")
                good = (units == buildings if group == 0 else
                        units == 2 * buildings if group == 1 else
                        3 * buildings <= units <= 4 * buildings if group == 2 else
                        units >= 5 * buildings)
                if not good:
                    raise SourceError(f"Line {line}: units/buildings inconsistent in {category}-unit category.")
            record[f"buildings_{category}"] = buildings
            record[f"units_{category}"] = units
            record[f"valuation_{category}"] = valuation
            record["reported_only"][category] = dict(zip(
                ("buildings", "units", "valuation_usd"), measurements[12 + group * 3:15 + group * 3]))
        record["buildings"] = complete_sum([record[f"buildings_{t}"] for t in TYPE_NAMES])
        record["units"] = complete_sum([record[f"units_{t}"] for t in TYPE_NAMES])
        record["valuation_usd"] = complete_sum([record[f"valuation_{t}"] for t in TYPE_NAMES])
        records.append(record)
    if not records:
        raise SourceError("Source contains no Utah county records.")
    if require_all_counties and seen != UTAH_COUNTIES:
        raise SourceError("Incomplete Utah coverage; missing counties: " + ", ".join(sorted(UTAH_COUNTIES - seen)))
    # The UI also adds county rows. Exact components alone do not guarantee an
    # exact statewide total, so bound every displayed aggregate before load.
    for field in ["buildings", "units", "valuation_usd"] + [f"units_{t}" for t in TYPE_NAMES]:
        complete_sum([record[field] for record in records])
    return ParsedSource(year, hashlib.sha256(raw).hexdigest(), sorted(records, key=lambda r: r["geoid"]), national_rows, missing)


def synthetic_fixture(year: int = 2025, *, revised: bool = False) -> bytes:
    """Explicitly synthetic two-county engineering data, never a Census substitute."""
    rows = [next(csv.reader([TOP])), next(csv.reader([BOTTOM]))]
    for county, name, values, reported in [
        ("001", "Synthetic Beaver County", [10, 10, 1_000_000, 2, 4, 400_000, 1, 3, 300_000, 1, 7 if revised else 6, 600_000],
         [9, 9, 900_000, 1, 2, 200_000, 1, 3, 300_000, 1, 5, 500_000]),
        ("003", "Synthetic Box Elder County", [20, 20, 2_000_000, 0, 0, 0, 0, 0, 0, 1, 10, 1_000_000],
         [19, 19, 1_900_000, 0, 0, 0, 0, 0, 0, 1, 9, 900_000]),
    ]:
        # Reported-only figures intentionally differ from estimates.
        rows.append([str(year), "49", county, "4", "8", name] + [str(x) for x in values + reported])
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)
    return out.getvalue().encode()
