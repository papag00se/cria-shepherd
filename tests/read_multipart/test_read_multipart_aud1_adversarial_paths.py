"""Audit (AUD1): what the producer programs say about a path the model chose. The line count is substituted into a template that
also holds the path, so a path that spells the template's own placeholder was rewritten in the sentence cria showed the coder."""
import json
import subprocess
import sys

import pytest

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from read_multipart_helpers import HEX, page_through, start  # noqa: E402,F401  (isolated_home is autouse in the helper module)

from cria import filecommands as fc  # noqa: E402

NAME = 'a%N%b'


def test_the_past_the_end_sentence_of_a_plain_ranged_read_names_the_path_exactly(tmp_path):
    (tmp_path / NAME).write_text('a\nb\n')
    r = subprocess.run(['bash', '-c', fc._read_command_body({'path': NAME, 'start_line': 9})], cwd=tmp_path, capture_output=True, text=True)
    assert r.stdout == f'(no lines in that range — {NAME} has 2 lines; line 9 is past the end of the file)\n'


def test_the_past_the_end_sentence_of_a_multipart_page_names_the_path_exactly(tmp_path):
    bridge, messages, path = start(tmp_path, HEX, {'start_line': 99999}, name=NAME)
    projected, _ = page_through(bridge, messages)
    shown = next(m for m in projected if m.get('tool_call_id') == 'original')['content']
    assert shown.endswith(f'(no lines in that range — {path} has 5000 lines; line 99999 is past the end of the file)\n')


# --- failure injection: the snapshot cannot be made, or the place it would live is hostile -----------------------------------------

import base64  # noqa: E402
import re  # noqa: E402

import read_multipart_helpers as rig  # noqa: E402


def _token_of(command):
    return json.loads(base64.b64decode(re.search(r"b64decode\('([A-Za-z0-9+/=]+)'\)\)\noffset", command).group(1)))['token']


def _hostile_harness(how, tmp):
    """The harness for this failure: files cannot grow past 20 KiB (a 45 KB snapshot write fails after its directory exists, as on a full
    disk), or something already sits on the name the snapshot would take."""
    def run(call):
        command = json.loads(call['function']['arguments'])['cmd']
        name = tmp / (fc.MULTIPART_SNAPSHOT_DIR + _token_of(command))
        if how == 'symlink-at-the-snapshot-name' and not name.is_symlink(): name.symlink_to(tmp.parent)
        if how == 'loose-directory-at-the-snapshot-name' and not name.exists(): name.mkdir(mode=0o755)
        return rig.pty_run(('ulimit -f 20; ' if how == 'disk-full' else '') + command)
    return run


@pytest.mark.parametrize('how', ['disk-full', 'symlink-at-the-snapshot-name', 'loose-directory-at-the-snapshot-name'])
def test_a_snapshot_that_cannot_be_made_is_cleaned_up_and_the_read_completes_exact_and_live(tmp_path, monkeypatch, how):
    """Whatever stops the snapshot, the page says `live`/`unavailable`, leaves no half-made directory, touches nothing it did not make
    (a planted name is left exactly as found, its target untouched), and the read still delivers the exact file."""
    tmp = tmp_path / 'harness-tmp'; tmp.mkdir(); monkeypatch.setenv('TMPDIR', str(tmp))
    monkeypatch.setattr(rig, 'run_call', _hostile_harness(how, tmp))
    bridge, messages, path = rig.start(tmp_path, HEX)
    bridge.incoming('s', messages)
    assert bridge.sessions['s']['original'].assembly.snapshot == ('live', 'unavailable', None)
    left = sorted(p.name for p in tmp.iterdir())
    assert (left == []) == (how == 'disk-full') and len(left) == (0 if how == 'disk-full' else 1)
    if how == 'loose-directory-at-the-snapshot-name': assert list((tmp / left[0]).iterdir()) == []
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.startswith('.')) == []
    projected, facts = rig.page_through(bridge, messages)
    assert facts[0].exact_body == HEX.encode()
