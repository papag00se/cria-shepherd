"""Independent author's local fixture adapter; does not import training cases.

The isolated held-out author runs this on their own private specification. This
module contains no held-out examples and does not open any dataset by default.
"""
from __future__ import annotations

import argparse
import base64
import difflib
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile
import uuid

from cria import prompts
from suite.gliclass_probe import render_state as render_text
from suite.progress_dataset import LABELS, render_state


def full_diff(seed: dict[str, str], current: dict[str, str]) -> str:
    lines = []
    for name in sorted(seed.keys() | current.keys()):
        old, new = seed.get(name), current.get(name)
        if old == new:
            continue
        before, after = (old or '').splitlines(keepends=True), (new or '').splitlines(keepends=True)
        block = list(difflib.unified_diff(
            before, after, fromfile=f'a/{name}' if old is not None else '/dev/null',
            tofile=f'b/{name}' if new is not None else '/dev/null',
            n=max(len(before), len(after)) + 1, lineterm=''))
        if not block:
            lines.append(f'empty file added: {name}' if old is None else f'deleted file: {name}')
            continue
        for index, line in enumerate(block):
            if index < 3:  # unified-diff file headers and first hunk header
                lines.append(line)
            elif line.endswith('\n'):
                lines.append(line[:-1])
            else:
                lines.extend((line, r'\ No newline at end of file'))
    return '\n'.join(lines)


def put_files(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        target = (root / name).resolve()
        if not target.is_relative_to(root.resolve()) or target == root.resolve():
            raise ValueError(f'file must be inside fixture directory: {name!r}')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')


def output_fields(stdout: bytes | None, stderr: bytes | None) -> dict:
    result = {}
    for name, data in [('stdout', stdout or b''), ('stderr', stderr or b'')]:
        result[name] = data.decode('utf-8', errors='backslashreplace')
        result[name + '_base64'] = base64.b64encode(data).decode('ascii')
    return result


def run_check(snapshot: dict[str, str], check: dict) -> dict:
    with tempfile.TemporaryDirectory(prefix='progress-fixture-', dir=os.environ.get('TMPDIR') or '/var/tmp') as tmp:
        root = Path(tmp)
        put_files(root, snapshot)
        # A verifier must not replace the implementation it is intended to check.
        verifier_files = check.get('files', {})
        if snapshot.keys() & verifier_files.keys():
            raise ValueError('verifier files overlap snapshot files')
        put_files(root, verifier_files)
        env = {'PATH': os.environ.get('PATH', os.defpath), 'HOME': tmp, 'TMPDIR': tmp,
               'PYTHONDONTWRITEBYTECODE': '1', 'GOPROXY': 'off', 'GOTOOLCHAIN': 'local',
               'GOCACHE': str(root / '.cache' / 'go-build'), 'CARGO_NET_OFFLINE': 'true'}
        try:
            result = subprocess.run(check['argv'], cwd=root, env=env, capture_output=True,
                                    timeout=check.get('timeout_seconds', 10), check=False)
            return {'argv': check['argv'], 'returncode': result.returncode,
                    **output_fields(result.stdout, result.stderr)}
        except FileNotFoundError as exc:
            return {'argv': check['argv'], 'returncode': None, 'unavailable': str(exc), **output_fields(None, None)}
        except subprocess.TimeoutExpired as exc:
            return {'argv': check['argv'], 'returncode': None, 'timeout': True,
                    **output_fields(exc.stdout, exc.stderr)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', required=True, type=Path, help='author-private JSON specification')
    parser.add_argument('--out', required=True, type=Path, help='author-private output directory')
    args = parser.parse_args()
    groups = json.loads(args.spec.read_text(encoding='utf-8'))['groups']
    blind, private = [], []
    for group in groups:
        for label in LABELS:
            snap = group['snapshots'][label]
            identifier = uuid.uuid4().hex
            state = render_state(group['requirement'], full_diff(group['seed_files'], snap))
            blind.append({'id': identifier, 'policy': prompts.load('offline_onejev_progress') + '\n',
                          'state': state, 'rendered_state': render_text(state), 'options': list(LABELS)})
            private.append({'id': identifier, 'family': group['family'], 'group': group['group'],
                            'label': label, 'seed_files': group['seed_files'], 'snapshot': snap,
                            'rationale': group['rationale'], 'verifiers': group['checks'],
                            'results': {c['name']: run_check(snap, c) for c in group['checks']}})
    random.SystemRandom().shuffle(blind)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, records in [('review-blind.jsonl', blind), ('private-evidence.jsonl', private)]:
        with (args.out / name).open('w', encoding='utf-8') as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
    print(json.dumps({'groups': len(groups), 'rows': len(private), 'output': str(args.out)}))


if __name__ == '__main__':
    main()
