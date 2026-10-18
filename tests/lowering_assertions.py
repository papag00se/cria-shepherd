"""Disk-effect oracle shared by read-credit and whole-write protection tests."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

from cria import writeproxy


def write_did_run(command):
    original = writeproxy.original_call(command)
    assert original and original['name'] == 'write_file'
    arguments = json.loads(original['arguments'])
    relative = Path(arguments['path'])
    assert not relative.is_absolute() and '..' not in relative.parts
    before = b'original fixture bytes\n'
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(before)
        result = subprocess.run(['sh', '-c', command], cwd=directory,
                                env={**os.environ, 'TMPDIR': directory}, capture_output=True, timeout=15)
        landed = writeproxy._WROTE.encode() in result.stdout
        assert path.read_bytes() == (arguments['content'].encode() if landed else before), result.stderr
        if landed:
            assert result.returncode == 0, result.stderr
        return landed
