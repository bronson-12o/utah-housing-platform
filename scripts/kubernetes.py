"""Dedicated local kind cluster; explicit private kubeconfig, no cloud context."""
from pathlib import Path
import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
CLUSTER = 'utah-housing-platform'
KUBECONFIG = ROOT / 'data/kubernetes/config'
NAMESPACE = 'utah-housing'


def kubectl(*args, capture=False, input_text=None):
    return subprocess.run(['kubectl', '--kubeconfig', str(KUBECONFIG),
                           '--context', 'kind-' + CLUSTER, *args], check=True,
                          text=True, capture_output=capture, input=input_text)


def kind_bin():
    value = os.getenv('KIND_BIN') or shutil.which('kind')
    if not value:
        raise RuntimeError('Install the free kind CLI from https://kind.sigs.k8s.io/docs/user/quick-start/ or set KIND_BIN.')
    return value


def up():
    kind = kind_bin()
    KUBECONFIG.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([kind, 'get', 'clusters'], text=True, capture_output=True, check=True)
    if CLUSTER not in result.stdout.splitlines():
        subprocess.run([kind, 'create', 'cluster', '--name', CLUSTER, '--config',
                        str(ROOT / 'deploy/kubernetes/kind.yaml'), '--kubeconfig', str(KUBECONFIG),
                        '--wait', '180s'], check=True)
    elif not KUBECONFIG.exists():
        subprocess.run([kind, 'export', 'kubeconfig', '--name', CLUSTER,
                        '--kubeconfig', str(KUBECONFIG)], check=True)
    KUBECONFIG.chmod(0o600)
    subprocess.run([kind, 'load', 'docker-image', 'utah-housing-platform:local', '--name', CLUSTER], check=True)
    # Apply Namespace before its Secret; never print the generated secret.
    namespace = {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': NAMESPACE}}
    kubectl('apply', '-f', '-', input_text=json.dumps(namespace))
    existing = kubectl('-n', NAMESPACE, 'get', 'secrets', '-o', 'name', capture=True).stdout
    if 'secret/housing-secret' not in existing.splitlines():
        secret = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'housing-secret', 'namespace': NAMESPACE},
                  'type': 'Opaque', 'stringData': {'password': secrets.token_hex(24)}}
        kubectl('apply', '-f', '-', input_text=json.dumps(secret))
    kubectl('apply', '-f', str(ROOT / 'deploy/kubernetes/platform.yaml'))
    kubectl('-n', NAMESPACE, 'rollout', 'status', 'deployment/warehouse', '--timeout=180s')
    name = 'initial-load-' + str(int(time.time()))
    kubectl('-n', NAMESPACE, 'create', 'job', name, '--from=cronjob/annual-source-check')
    kubectl('-n', NAMESPACE, 'wait', '--for=condition=complete', 'job/' + name, '--timeout=240s')
    kubectl('-n', NAMESPACE, 'rollout', 'restart', 'deployment/dashboard')
    kubectl('-n', NAMESPACE, 'rollout', 'status', 'deployment/dashboard', '--timeout=180s')
    print('Local cluster ready. Keep this terminal command open to view it:')
    print('python3 scripts/kubernetes.py forward')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['up', 'status', 'forward', 'refresh'])
    args = parser.parse_args()
    if args.command == 'up':
        up()
    elif args.command == 'status':
        kubectl('-n', NAMESPACE, 'get', 'pods,jobs,cronjobs,pvc')
    elif args.command == 'forward':
        kubectl('-n', NAMESPACE, 'port-forward', '--address', '127.0.0.1', 'service/dashboard', '18087:8080')
    elif args.command == 'refresh':
        name = 'manual-load-' + str(int(time.time()))
        kubectl('-n', NAMESPACE, 'create', 'job', name, '--from=cronjob/annual-source-check')
        kubectl('-n', NAMESPACE, 'wait', '--for=condition=complete', 'job/' + name, '--timeout=240s')


if __name__ == '__main__':
    main()
