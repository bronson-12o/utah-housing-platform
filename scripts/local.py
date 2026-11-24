"""Local-only launcher; no cloud account or global container cleanup."""
from pathlib import Path
import argparse
import json
import os
import secrets
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def setup():
    path = ROOT / '.env'
    if not path.exists():
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        with os.fdopen(os.open(path, flags, 0o600), 'w') as stream:
            stream.write('POSTGRES_PASSWORD=' + secrets.token_hex(24) + '\n')
            stream.write('HOUSING_PORT=8087\nHOUSING_FIXTURE_PORT=8088\nDAGSTER_PORT=3007\n')
    values = {}
    for line in path.read_text().splitlines():
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            values[key] = value
    return values


def compose(*args, capture=False):
    setup()
    command = ['docker', 'compose', '--env-file', str(ROOT / '.env'),
               '-f', str(ROOT / 'compose.yaml'), *args]
    return subprocess.run(command, cwd=ROOT, check=True, text=True,
                          capture_output=capture)


def wait(url):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=4) as response:
                if response.status == 200:
                    return
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError('Local service did not become ready: ' + url)


def pipeline(*args, fixture=False):
    values = setup()
    extra = ['-e', 'DATABASE_URL=postgresql://housing:' + values['POSTGRES_PASSWORD'] + '@db:5432/housing_fixture'] if fixture else []
    # Credentials are passed directly to the local process, never printed.
    return compose('run', '--rm', *extra, 'pipeline', *args)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['setup', 'up', 'fixture', 'status', 'stop', 'refresh', 'snapshot', 'check'])
    args = parser.parse_args()
    values = setup()
    if args.command == 'setup':
        print('Created or retained private local configuration. No service started.')
    elif args.command in ('up', 'fixture'):
        compose('build', 'app')
        compose('up', '-d', '--wait', 'db')
        if args.command == 'fixture':
            pipeline('init', fixture=True)
            pipeline('fixture', fixture=True)
            compose('--profile', 'fixture', 'up', '-d', 'fixture-app')
            port = values.get('HOUSING_FIXTURE_PORT', '8088')
            wait('http://127.0.0.1:' + port + '/health/ready')
            print('Synthetic fixture workspace: http://127.0.0.1:' + port)
        else:
            pipeline('init')
            pipeline('backfill', '--years', '2021:2025', '--output', '/data/exports/housing.json')
            compose('up', '-d', 'app', 'dagster')
            port = values.get('HOUSING_PORT', '8087')
            wait('http://127.0.0.1:' + port + '/health/ready')
            wait('http://127.0.0.1:' + values.get('DAGSTER_PORT', '3007'))
            print('Real-source workspace: http://127.0.0.1:' + port)
            print('Local Dagster: http://127.0.0.1:' + values.get('DAGSTER_PORT', '3007'))
    elif args.command == 'refresh':
        pipeline('backfill', '--years', '2021:2025', '--output', '/data/exports/housing.json')
    elif args.command == 'snapshot':
        pipeline('export', '--output', '/data/exports/housing.json')
        compose('cp', 'app:/data/exports/housing.json', str(ROOT / 'web/data/housing.json'))
        print('Wrote actual warehouse snapshot. Review this data diff before publishing.')
    elif args.command == 'check':
        pipeline('check')
    elif args.command == 'status':
        compose('ps')
    elif args.command == 'stop':
        compose('stop')
        print('Only this Compose project stopped. Data volumes retained.')


if __name__ == '__main__':
    main()
