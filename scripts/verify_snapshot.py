"""Independent stdlib reader: no application imports and no inferred source values.

Default downloads original county and state annual files. --source-dir reuses raw
files already captured by a reviewer. --offline checks snapshot shape and receipt
consistency only; it deliberately does not claim fresh source reconciliation.
"""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

def require(condition, message):
    if not condition:
        raise ValueError(message)

def verify(snapshot, source_dir=None, offline=False):
    raw = Path(snapshot).read_bytes()
    payload = json.loads(raw)
    require(payload['quality']['status'] == 'passed', 'Export quality did not pass')
    require(not payload['metadata'].get('synthetic', False), 'Public snapshot must contain real data')
    rows = payload['annual']
    require(len(rows) == 145, 'Expected five years × 29 counties')
    indexed = {(row['year'], row['geoid']): row for row in rows}
    require(len(indexed) == len(rows), 'Duplicate annual county')
    sources = {int(source['period']): source for source in payload['sources']}
    report = {'snapshot_sha256': hashlib.sha256(raw).hexdigest(), 'rows': len(rows),
              'mode': 'offline-structure-only' if offline else 'independent-source-reconciliation',
              'field_checks': 0, 'years': []}
    for year in range(2021, 2026):
        actual = [row for row in rows if row['year'] == year]
        require({row['geoid'] for row in actual} == {'49'+str(code).zfill(3) for code in range(1,58,2)}, 'County coverage')
        source = sources[year]
        require(all(row['source_sha256'] == source['sha256'] for row in actual), 'Source binding')
        require(all(row['units'] == sum(row[key] for key in ('units_1','units_2','units_3_4','units_5_plus')) for row in actual), 'Mix arithmetic')
        if offline:
            report['years'].append({'year': year, 'units': sum(row['units'] for row in actual)})
            continue
        def read(name, family):
            url = f'https://www2.census.gov/econ/bps/{family}/{name}'
            if source_dir:
                return (Path(source_dir)/name).read_bytes()
            with urllib.request.urlopen(url, timeout=60) as response:
                return response.read()
        county_raw = read(f'co{year}a.txt','County')
        require(hashlib.sha256(county_raw).hexdigest() == source['sha256'], 'Source changed since snapshot; review a new version rather than accepting stale expectations')
        county = list(csv.reader(io.StringIO(county_raw.decode('utf-8-sig'))))
        require(len(county[1]) == 30, 'County source schema changed')
        expected = [row for row in county[2:] if len(row) > 1 and row[1].strip() == '49']
        require(len(expected) == 29, 'Original county coverage')
        for row in expected:
            require(row[0].strip() == str(year), 'County reference period')
            geoid = row[1].strip().zfill(2)+row[2].strip().zfill(3)
            numbers = [int(value.strip()) for value in row[6:18]]
            values = {'buildings':sum(numbers[0::3]), 'units':sum(numbers[1::3]),
                      'valuation_usd':sum(numbers[2::3]), 'county_name':row[5].strip(),
                      'source_sha256':hashlib.sha256(county_raw).hexdigest(),
                      'units_1':numbers[1], 'units_2':numbers[4],
                      'units_3_4':numbers[7], 'units_5_plus':numbers[10]}
            for field,value in values.items():
                require(indexed[(year,geoid)][field] == value, f'{year}/{geoid}/{field} differs from original')
                report['field_checks'] += 1
        state_raw = read(f'st{year}a.txt','State')
        states = list(csv.reader(io.StringIO(state_raw.decode('utf-8-sig'))))
        require(len(states[1]) == 29, 'State source schema changed')
        state = [row for row in states[2:] if len(row) > 1 and row[1].strip() == '49']
        require(len(state) == 1 and state[0][0].strip() == f'{year}99', 'State annual period')
        state_numbers = [int(value.strip()) for value in state[0][5:17]]
        units = sum(row['units'] for row in actual)
        require(units == sum(state_numbers[1::3]), 'County sum differs from separately published state units')
        report['years'].append({'year': year, 'county_units':units, 'state_units':sum(state_numbers[1::3]),
            'valuation_rounding_difference_usd':sum(row['valuation_usd'] for row in actual)-1000*sum(state_numbers[2::3]),
            'state_sha256':hashlib.sha256(state_raw).hexdigest()})
    report['status'] = 'passed'
    return report

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, default=ROOT/'web/data/housing.json')
    parser.add_argument('--source-dir', type=Path)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = verify(args.snapshot,args.source_dir,args.offline)
    text = json.dumps(result,indent=2)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(text)
    print(text)
