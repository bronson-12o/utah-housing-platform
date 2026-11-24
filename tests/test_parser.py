import csv
import io

import pytest

from utah_housing.parser import SourceError, parse_annual, synthetic_fixture, integer
from utah_housing.pipeline import years


def edited(*, column=None, value=None, duplicate=False):
    rows = list(csv.reader(io.StringIO(synthetic_fixture().decode())))
    if column is not None:
        rows[2][column] = value
    if duplicate:
        rows.append(rows[2])
    output = io.StringIO()
    csv.writer(output).writerows(rows)
    return output.getvalue().encode()


def test_estimates_and_reported_only_are_not_double_counted():
    source = parse_annual(synthetic_fixture(), 2025, require_all_counties=False)
    row = source.rows[0]
    assert row["geoid"] == "49001"
    assert row["county_fips"] == "001"
    assert row["units"] == 23
    assert row["buildings"] == 14
    assert row["valuation_usd"] == 2_300_000
    assert row["reported_only"]["1"]["units"] == 9
    assert sum(row["units"] for row in source.rows) == 53


def test_genuine_blank_is_unknown_and_does_not_become_zero():
    result = parse_annual(edited(column=7, value=""), 2025, require_all_counties=False)
    assert result.rows[0]["units_1"] is None
    assert result.rows[0]["units"] is None
    assert result.missing_value_count == 1


@pytest.mark.parametrize("value", ["-1", "1.5", "1e3", "NaN", "true", "1,000", "9007199254740992"])
def test_numeric_contamination_is_rejected(value):
    with pytest.raises(SourceError):
        parse_annual(edited(column=7, value=value), 2025, require_all_counties=False)


def test_duplicate_county_is_rejected():
    with pytest.raises(SourceError, match="duplicate"):
        parse_annual(edited(duplicate=True), 2025, require_all_counties=False)


def test_fixture_cannot_pose_as_full_state_source():
    with pytest.raises(SourceError, match="Incomplete Utah coverage"):
        parse_annual(synthetic_fixture(), 2025)


@pytest.mark.parametrize("column,value", [(0, "202501"), (1, "049"), (2, "1"), (7, "11"), (10, "5")])
def test_period_grain_fips_and_building_type_constraints(column, value):
    with pytest.raises(SourceError):
        parse_annual(edited(column=column, value=value), 2025, require_all_counties=False)


def test_html_or_unrecognized_headers_are_not_valid_sources():
    with pytest.raises(SourceError):
        parse_annual(b"<html>Missing key</html>", 2025)
    raw = synthetic_fixture().replace(b"Survey", b"Changed schema", 1)
    with pytest.raises(SourceError, match="header"):
        parse_annual(raw, 2025, require_all_counties=False)


def test_bom_is_read_without_changing_reference_bytes():
    raw = b"\xef\xbb\xbf" + synthetic_fixture()
    source = parse_annual(raw, 2025, require_all_counties=False)
    assert source.rows[0]["units"] == 23
    import hashlib
    assert source.sha256 == hashlib.sha256(raw).hexdigest()


def test_source_revision_changes_only_the_revised_value():
    before = parse_annual(synthetic_fixture(), 2025, require_all_counties=False)
    after = parse_annual(synthetic_fixture(revised=True), 2025, require_all_counties=False)
    assert before.sha256 != after.sha256
    assert after.rows[0]["units"] == 24
    assert before.rows[1] == after.rows[1]


def test_year_range_is_bounded_and_unambiguous():
    assert years("2021:2025") == [2021, 2022, 2023, 2024, 2025]
    assert years("2025,2024,2025") == [2024, 2025]
    for value in ["2025:2021", "2000:2099", "2025-01", "../2025"]:
        with pytest.raises(SourceError):
            years(value)


def test_five_plus_units_cannot_exist_without_a_building():
    with pytest.raises(SourceError, match="zero buildings"):
        parse_annual(edited(column=15, value="0"), 2025, require_all_counties=False)


def test_derived_county_value_cannot_exceed_exact_integer_range():
    rows = list(csv.reader(io.StringIO(synthetic_fixture().decode())))
    for index in (8, 11, 14, 17):
        rows[2][index] = "3000000000000000"
    out = io.StringIO();csv.writer(out).writerows(rows)
    with pytest.raises(SourceError, match="Derived total"):
        parse_annual(out.getvalue().encode(), 2025, require_all_counties=False)


def test_statewide_value_is_also_bounded_even_when_each_county_is_exact():
    rows = list(csv.reader(io.StringIO(synthetic_fixture().decode())))
    rows[2][8] = "3000000000000000"
    rows[3][8] = "7000000000000000"
    out = io.StringIO();csv.writer(out).writerows(rows)
    with pytest.raises(SourceError, match="Derived total"):
        parse_annual(out.getvalue().encode(), 2025, require_all_counties=False)
