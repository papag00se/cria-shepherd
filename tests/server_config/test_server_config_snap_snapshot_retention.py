"""Operator retention of the private source snapshots an abandoned multipart read leaves in the harness temp directory.
A completed read removes its own; one abandoned before its last page leaves `.ctx-mpsnap-<token>` (there is no session-close signal to
sweep it on, so only the operator's explicit `--kind snapshot`, never `all`, and only by age or token)."""
import io
import json
import os
import subprocess
import time

from cria import filecommands, retention

DAY = 86400


def abandoned_read(tmp_path, token):
    """Run the REAL first page command of a multi-page read under bash, with the harness TMPDIR pointing at tmp_path/'t', and leave it there."""
    source = tmp_path / ('source-' + token[:4]); source.write_bytes(b''.join(b'%08x\n' % (i * 2654435761 % 2**32) for i in range(5000)))
    spec = filecommands.make_multipart_read_spec('c-' + token[:4], 'read_file', json.dumps({'path': str(source)}), token)
    out = subprocess.run(['bash', '-c', filecommands.build_multipart_page(spec, 0)], capture_output=True, check=True,
                         env={**os.environ, 'TMPDIR': str(tmp_path / 't')}).stdout
    assert b'"mode":"snapshot"' in out
    return tmp_path / 't' / (filecommands.MULTIPART_SNAPSHOT_DIR + token)


def run(tmp_path, *argv):
    out = io.StringIO(); code = retention.main([argv[0], '--home', str(tmp_path / 'home'), '--tmp', str(tmp_path / 't'), *argv[1:]], out=out)
    return code, out.getvalue()


def test_an_abandoned_snapshot_is_listed_and_pruned_by_age_only_when_asked_for_and_decoys_are_never_touched(tmp_path):
    """Real snapshot made by the real page program: listed with its size; `all` does not scan the temp dir; prune needs a selector, honours age and
    removes exactly it (a directory in the shape an earlier release created is listed and pruned too); a same-prefix directory with foreign contents, a symlink, a wrong-shape name and an unrelated directory survive."""
    (tmp_path / 't').mkdir(); (tmp_path / 'home').mkdir(mode=0o700)
    snap = abandoned_read(tmp_path, 'a' * 32); other = abandoned_read(tmp_path, 'b' * 32)
    other = other.rename(other.with_name(filecommands.LEGACY_MULTIPART_SNAPSHOT_DIR + 'b' * 32))  # left by an earlier release: still swept
    prefix = filecommands.MULTIPART_SNAPSHOT_DIR
    foreign = tmp_path / 't' / (prefix + 'c' * 32); foreign.mkdir(mode=0o700); (foreign / 'precious.txt').write_text('mine')
    link = tmp_path / 't' / (prefix + 'd' * 32); link.symlink_to(foreign)
    (tmp_path / 't' / (prefix + 'zz')).write_text('not ours'); unrelated = tmp_path / 't' / 'work'; unrelated.mkdir()
    code, text = run(tmp_path, 'list', '--kind', 'snapshot', '--json'); data = json.loads(text)
    by_id = {e['id']: e for e in data['entries']}
    assert code == 0 and set(by_id) == {'a' * 32, 'b' * 32, 'c' * 32, 'd' * 32} and data['ignored'] == ['snapshot/' + prefix + 'zz']
    assert by_id['a' * 32]['kind'] == 'snapshot' and by_id['a' * 32]['size'] > 40000 and not by_id['a' * 32]['refused']
    assert by_id['c' * 32]['refused'] and 'precious.txt' in by_id['c' * 32]['detail'] and by_id['d' * 32]['refused']
    assert json.loads(run(tmp_path, 'list', '--json')[1])['entries'] == []                    # `all` never scans the harness temp directory
    assert run(tmp_path, 'prune', '--kind', 'snapshot', '--apply')[0] == 2 and snap.exists()  # a bare prune can never select everything
    assert 'would remove 0' in run(tmp_path, 'prune', '--kind', 'snapshot', '--older-than', '1d')[1]
    old = time.time() - 3 * DAY
    for p in (snap, *snap.iterdir()): os.utime(p, (old, old))
    code, text = run(tmp_path, 'prune', '--kind', 'snapshot', '--older-than', '1d')
    assert 'would remove 1 entry' in text and snap.exists()                                   # dry run
    code, text = run(tmp_path, 'prune', '--kind', 'snapshot', '--older-than', '1d', '--apply')
    assert code == 0 and 'removed snapshot ' + 'a' * 32 in text and not snap.exists() and other.exists()
    assert (foreign / 'precious.txt').read_text() == 'mine' and link.is_symlink() and unrelated.exists()
    code, text = run(tmp_path, 'prune', '--kind', 'snapshot', '--session', 'b' * 8, '--apply')
    assert code == 0 and not other.exists() and foreign.exists()
