"""Characterisation of grep / glob / web_fetch / web_search: what the model reads and what is on disk, case by case, against the capture of the route that
shipped before Phase 6b (tests/fixtures/search_characterization.json). `CRIA_CHARACTERIZE=<path>` writes a capture of the route under test instead."""
import hashlib
import re
import json
import os
import pathlib

import pytest

import search_rig
from cria import webfetch
from ops_rig import isolated_home  # noqa: F401

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / 'fixtures' / 'search_characterization.json'


def slim(disk):
    """The disk of a case with every long file reduced to its size, hash and ends (the fixture stays small; a difference anywhere still shows)."""
    out = {}
    for rel, entry in disk.items():
        text = entry.get('text')
        if text is not None and len(text) > 3000:
            entry = {**{k: v for k, v in entry.items() if k != 'text'}, 'sha': hashlib.sha256(text.encode()).hexdigest(), 'head': text[:200], 'tail': text[-200:]}
        out[rel] = entry
    return out


def norm(text):
    """The old route's results came through a pty: a CR before every line feed and a trailing newline, which the text cria composes now does not have."""
    return text.replace('\r\n', '\n').rstrip('\n')


STDOUT = re.compile(r'stdout-[0-9a-f]{64}\.txt')
RECORD = re.compile(r'\A\{"v":1,"r":"[0-9a-f]+","k":"ran"\}\n')


def unname(text):
    return STDOUT.sub('stdout-X.txt', text)


def essence(entry, typed_record=False):
    """``(size, head, tail)`` of a saved file: the old route's saved output began with the typed record line the harness program printed first (and its
    name was the hash of that record plus the text), the text cria saves now does not."""
    text = entry.get('text')
    head, tail, size = (text, text, entry['size']) if text is not None else (entry['head'], entry['tail'], entry['size'])
    if typed_record:
        record = RECORD.match(head)
        assert record, head[:80]
        head, size = head[record.end():], size - record.end()
        text = text[record.end():] if text is not None else None
    return size, head[:150], tail[-150:]


def same_files(got_disk, want_disk, saved=None):
    """The disk of a case, equal but for the saved-output files (compared by what they hold) and any file in ``saved`` (the cases that say what changed)."""
    saved = saved or ()
    got_out = [v for k, v in got_disk.items() if STDOUT.search(k)]
    want_out = [v for k, v in want_disk.items() if STDOUT.search(k)]
    assert [essence(v) for v in got_out] == [essence(v, True) for v in want_out]
    rest = lambda d: {k: v for k, v in d.items() if not STDOUT.search(k) and k not in saved}
    assert rest(slim(got_disk)) == rest(want_disk)


def lines(*items):
    return ''.join(i + '\n' for i in items).rstrip('\n')


def landed_whole(name, chars_at_least):
    """The saved document is the whole of what cria holds, byte for byte (compared by size and hash: the snapshot keeps no text past 60,000 bytes)."""
    def check(got):
        pointer = got['results'][0]
        assert 'saved IN FULL' in pointer and 'NOTE: this saved copy' not in pointer, pointer[:600]
        doc = next(iter(search_rig.CASES[name]['docs'].values()))
        whole = webfetch.spill_content(*webfetch.reduce_for_cache(doc['body'], doc['type'], search_rig.BIGURL if 'big' in name else search_rig.URL), doc['type'])
        saved = next(v for k, v in got['disk'].items() if k.startswith('tmp/reference/docs.example.com_') and k.endswith('.txt'))
        raw = whole.encode('utf-8')
        assert saved['size'] == len(raw) >= chars_at_least
        assert saved.get('text', None) == whole or saved['sha'] == hashlib.sha256(raw).hexdigest()
    return check


def saved_file(got):
    found = [v for k, v in got['disk'].items() if STDOUT.search(k)]
    assert len(found) == 1, list(got['disk'])
    return found[0]['text']


def saved_matches(got, expected_lines):
    assert got['results'][0].startswith('The search result exceeds the transport output limit.'), got['results'][0]
    assert saved_file(got) == ''.join(line + '\n' for line in expected_lines)


def partial_rows(got, name, rows):
    """The heavy file: the answer is the incomplete pointer, the saved file holds the first matches in order (at least 500 of them) and says it holds only those."""
    assert got['results'][0].startswith('The search was incomplete.'), got['results'][0]
    text = saved_file(got)
    body, _, note = text.partition('Search incomplete; these paths could not be read:\n')
    shown = body.splitlines()
    assert 500 <= len(shown) < rows and shown == [f'{name}:{i + 1}:row {i}' for i in range(len(shown))], (len(shown), shown[-2:])
    assert note == f'{name}: at least {len(shown):,} matches, more than one result holds; only those are shown\n'


def result_is(*expected):
    def check(got):
        assert [r.rstrip('\n') for r in got['results']] == list(expected), got['results']
    return check


# name -> what changed and what the model reads / what is on disk now
INTENDED = {
    'f_plain_text_30k': ('a fetched document past the shell command is saved whole, not cut at 46,080 bytes', landed_whole('f_plain_text_30k', 47_000)),
    'f_spill_100k_cut': ('a fetched document past the shell command is saved whole, not cut at 46,080 bytes', landed_whole('f_spill_100k_cut', 100_000)),
    'f_spill_250k': ('a fetched document past the shell command is saved whole, not cut at 46,080 bytes', landed_whole('f_spill_250k', 250_000)),
    'g_matches_in_a_big_file': ('a file with more matches than one `search` result holds (its frame is one harness result) is saved with the matches it holds and '
                                'a line that says so (STOPPED item, docs/harness-programs.md section 7)', lambda got: partial_rows(got, 'rows.txt', 2000)),
    'g_matches_in_a_big_file_1500': ('a file with more matches than one `search` result holds (its frame is one harness result) is saved with the matches it holds '
                                     'and a line that says so (STOPPED item, docs/harness-programs.md section 7)', lambda got: partial_rows(got, 'rows.txt', 1500)),
    'g_big_spill_with_errors': ('a file that is not text and has no match is no longer an unreadable file: no "incomplete" variant of the pointer',
                                lambda got: saved_matches(got, [f'm{i:03d}.txt:{j + 1}:line {j} has the needle in it, with some padding words to make it longer'
                                                                for i in range(60) for j in range(3)])),
    'g_binary_only': ('a line that is not UTF-8 and does not match is no longer an unreadable file', result_is('No matches.')),
    'g_binary_after_match': ('a line that is not UTF-8 and does not match is no longer an unreadable file',
                             result_is(lines('a.txt:1:needle first', 'bin:1:needle ok', 'bin:3:needle after'))),
    'g_binary_no_match_line': ('a line that is not UTF-8 and does not match is no longer an unreadable file', result_is('bin:3:zzz')),
}


@pytest.mark.parametrize('name', sorted(search_rig.CASES))
def test_case(tmp_path, monkeypatch, name):
    got = search_rig.run_case(name, tmp_path, monkeypatch)
    target = os.environ.get('CRIA_CHARACTERIZE')
    if target:
        path = pathlib.Path(target)
        data = json.loads(path.read_text()) if path.exists() else {}
        data[name] = {**got, 'disk': slim(got['disk'])}
        path.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False))
        return
    want = json.loads(FIXTURE.read_text())[name]
    if name in INTENDED:
        INTENDED[name][1](got)
        return
    assert [unname(t.rstrip('\n')) for t in got['results']] == [unname(norm(t)) for t in want['results']]
    same_files(got['disk'], want['disk'])
