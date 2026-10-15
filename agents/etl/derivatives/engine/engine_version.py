#!/usr/bin/env python3
"""Engine version guard for derivatives KAT/backtest runners.

The engine hash of record is the sha256 of engine.py from the committed
manifest engine_sha256.json. Any engine.py edit without a manifest update (and
therefore a new KAT) makes runners refuse to start.
"""
import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, 'engine_sha256.json')


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def current_engine_sha256():
    return sha256_file(os.path.join(HERE, 'engine.py'))


def assert_engine_matches():
    if not os.path.exists(MANIFEST):
        raise RuntimeError(f'engine manifest missing: {MANIFEST}')
    with open(MANIFEST) as f:
        manifest = json.load(f)
    expected = (manifest.get('files') or {}).get('engine.py')
    actual = current_engine_sha256()
    if not expected:
        raise RuntimeError(f'engine manifest has no engine.py entry: {MANIFEST}')
    if actual != expected:
        raise RuntimeError(
            'engine.py hash mismatch: manifest={} actual={} — engine changed; '
            'run a new KAT and update the manifest/tag before backtesting'.format(
                expected, actual))
    return actual
