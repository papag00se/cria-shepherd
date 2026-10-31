"""Operator retention CLI arms beyond the happy paths: list --json shape, human table + notes, age/size formatting, sealed-marker retry,
leftover temps, forged/foreign records and call associations, session-prefix selection, unreadable roots."""
import hashlib, json, os, time
import pytest
from cria import imagepersist, retention
from test_server_config_cov_ops import DAY, age, home, image, record, run  # noqa: F401

def rows(home, *argv):
    code, text = run(home, 'list', '--json', *argv); assert code == 0; return json.loads(text)

def test_list_json_reports_every_entry_state_and_the_ignored_names(home, tmp_path):
    """One home holding a good record, a forged one, a stray temp, a bad association, a live and a closed image: json says exactly what each is."""
    good = record(home, tmp_path, 'sid:good'); mp = home / 'multipart'
    forged = mp / ('c' * 64 + '.json'); forged.write_text(json.dumps({'session': 'other'})); forged.chmod(0o600)
    tmp = mp / ('.multipart-' + 'a' * 32); tmp.write_text('half'); (mp / 'notes.txt').write_text('stray')
    bad_assoc = mp / ('call-' + 'd' * 64 + '.json'); bad_assoc.write_text(json.dumps({'v': 2})); bad_assoc.chmod(0o600)
    live = image(home, 'live'); closed = image(home, 'closed'); closed._hold.close()
    imagepersist.seal_marker(closed._root, json.loads((home / 'images' / (closed._root.name + '.owner.json')).read_text())['generation'], 'seal1')
    age(home, 3)
    data = rows(home); got = sorted((e['kind'], e['state'], e['label'], e['detail'], e['refused']) for e in data['entries'])
    assert data['ignored'] == ['multipart/notes.txt'] and data['notes'] == []
    assert got == [
        ('image', 'active', '', 'held by a live cria process', False),
        ('image', 'closed', 'closed', 'sealed for cleanup (an earlier cleanup did not finish)', False),
        ('multipart', 'corrupt', '', 'call-ddddddddddddddd: invalid call association', False),
        ('multipart', 'corrupt', '', 'cccccccccccccccccccc: record is not named for its session', False),
        ('multipart', 'unknown', '', 'leftover temporary file from an interrupted write', False),
        ('multipart', 'unknown', 'sid:good', '1 read(s)', False)]
    assert {e['id'] for e in data['entries'] if e['detail'].startswith('leftover')} == {'tmp-multipart-aaaaaaaaaa'}
    assert all(e['age_seconds'] >= 3 * DAY - 5 for e in data['entries']) and good.exists()
    live._hold.close()

def test_human_list_formats_sizes_ages_and_long_labels_and_prefix_selects_one_session(home, tmp_path):
    """Table: 'no retained entries' on an empty home, long session labels ellipsised, minute/hour ages; --session takes a >=8 char id prefix and nothing shorter."""
    assert run(home, 'list')[1] == 'no retained entries\n'
    rec = record(home, tmp_path, 'sid:' + 'x' * 40); other = record(home, tmp_path, 'sid:other'); age(home, 0); os.utime(rec, (time.time() - 7300,) * 2)
    for p in (home / 'multipart').glob('call-*'): os.utime(p, (time.time() - 90,) * 2)
    text = run(home, 'list')[1]
    assert 'sid:' + 'x' * 17 + '...' in text and '2h' in text
    digest = hashlib.sha256(('sid:' + 'x' * 40).encode()).hexdigest()
    assert 'removed' not in run(home, 'prune', '--session', digest[:7], '--apply')[1] and rec.exists()
    assert run(home, 'prune', '--session', digest[:8], '--apply')[0] == 0 and not rec.exists() and other.exists()

@pytest.mark.parametrize('seconds, text', [(0, '0s'), (59, '59s'), (60, '1m'), (3599, '59m'), (3600, '1h'), (2 * DAY, '2d'), (-5, '0s')])
def test_age_text_table(seconds, text): assert retention._fmt_age(seconds) == text

@pytest.mark.parametrize('n, text', [(0, '0B'), (1023, '1023B'), (1024, '1.0K'), (3 * 1024 ** 2, '3.0M'), (5 * 1024 ** 3, '5.0G'), (7 * 1024 ** 4, '7168.0G')])
def test_size_text_table(n, text): assert retention._size_text(n) == text

@pytest.mark.parametrize('text', ['', '7', 'd', '1y', '-1d', '1.5h', '1d2h'])
def test_parse_age_rejects_everything_but_count_and_unit(text):
    with pytest.raises(ValueError): retention.parse_age(text)

def test_sealed_image_with_missing_payload_is_retried_by_age_and_unsealed_or_unreadable_markers_only_by_name(home):
    """An owner marker whose payload is gone: sealed -> state closed and removed regardless of age; unsealed, unreadable or loose-mode -> corrupt and skipped by age."""
    images = home / 'images'; images.mkdir(mode=0o700)
    def marker(name, body, mode=0o600):
        p = images / (name + '.owner.json'); p.write_text(body); p.chmod(mode); os.utime(p, (time.time() - 40 * DAY,) * 2)
    marker('image-session-sealed', json.dumps({'generation': 'a' * 32, 'closed': 'seal'}))
    marker('image-session-open', json.dumps({'generation': 'a' * 32}))
    marker('image-session-junk', '{nope')
    marker('image-session-loose', '{}', 0o644)
    states = {e['id']: (e['state'], e['detail']) for e in rows(home)['entries']}
    assert states['image-session-sealed'] == ('closed', 'payload already removed; marker left by an interrupted cleanup')
    assert states['image-session-open'] == ('corrupt', 'unsealed owner marker without a session directory')
    assert states['image-session-junk'][0] == states['image-session-loose'][0] == 'corrupt' and 'unreadable: Expecting' in states['image-session-junk'][1]
    assert 'not a private regular file' in states['image-session-loose'][1]
    code, text = run(home, 'prune', '--older-than', '1w', '--apply')
    assert code == 0 and 'removed image image-session-sealed' in text and text.count('skipped: corrupt') == 3
    assert sorted(os.listdir(images)) == ['image-session-junk.owner.json', 'image-session-loose.owner.json', 'image-session-open.owner.json']

def test_a_named_unsealed_orphan_marker_can_be_cleared_but_age_pruning_never_touches_it(home):
    """`--session` seals an orphan marker (no payload, no seal) and clears it; `--older-than` skips it as corrupt; a marker with no generation still fails safely."""
    images = home / 'images'; images.mkdir(mode=0o700)
    def marker(name, body):
        p = images / (name + '.owner.json'); p.write_text(body); p.chmod(0o600); os.utime(p, (time.time() - 40 * DAY,) * 2)
    marker('image-session-open', '{"generation": "%s"}' % ('a' * 32)); marker('image-session-bare', '{}')
    assert 'skipped: corrupt' in run(home, 'prune', '--older-than', '1w', '--apply')[1] and len(os.listdir(images)) == 2
    code, text = run(home, 'prune', '--session', 'image-session-bare', '--apply')
    assert code == 1 and 'FAILED image image-session-bare' in text and 'image-session-bare.owner.json' in os.listdir(images)
    code, text = run(home, 'prune', '--session', 'image-session-open', '--apply')
    assert code == 0 and 'removed image image-session-open' in text and os.listdir(images) == ['image-session-bare.owner.json']

def test_unusable_roots_are_noted_not_fatal_and_wrong_mode_or_foreign_files_are_never_deleted(home):
    """A world-readable multipart root is refused with a note; image dir with wrong mode and a regular file posing as a record are corrupt+refused."""
    (home / 'multipart').mkdir(mode=0o755); (home / 'images').mkdir(mode=0o700)
    d = home / 'images' / 'image-session-wide'; d.mkdir(mode=0o755); (d / 'f').write_text('x')
    data = rows(home)
    assert any('multipart: root' in n and 'refused' in n for n in data['notes'])
    assert [(e['id'], e['state']) for e in data['entries']] == [('image-session-wide', 'corrupt')]
    code, text = run(home, 'prune', '--older-than', '0s', '--apply')
    assert code == 0 and 'APPLY: will remove 0 entries' in text and 'refused: not an owned private directory' in text and 'multipart: root' in text and (d / 'f').exists()
    assert run(home, 'prune', '--kind', 'image', '--session', 'image-session-wide', '--apply')[1].count('refused') == 1 and (d / 'f').exists()
