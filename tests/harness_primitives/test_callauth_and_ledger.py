"""Authentication without text markers, and the ledger that makes it restart-safe."""
import json
import os
import stat

import pytest

from cria import callauth, privatepaths
from cria.ledger import Ledger, LedgerError
from ops_rig import isolated_home  # noqa: F401

CMD = "env -i PATH=/usr/bin python3 -I -S -c 'stub' nonce /w ''"


def test_the_key_is_created_private_once_and_never_appears_in_anything_derived_from_it():
    nonce, group, cid = callauth.nonce('0123456789ab', 0), callauth.group('0123456789ab'), callauth.call_id('0123456789ab', 0, CMD)
    path = privatepaths.CRIA_HOME / 'harness-call.key'
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and len(path.read_bytes()) == 32
    assert path.read_bytes().hex() not in nonce + group + cid and len(cid) <= 40
    callauth._cache.clear()                                                  # a restart: the same key file, the same derivations
    assert (callauth.nonce('0123456789ab', 0), callauth.group('0123456789ab'), callauth.call_id('0123456789ab', 0, CMD)) == (nonce, group, cid)
    assert nonce != callauth.nonce('0123456789ab', 1) and len(nonce) == 32 and callauth.secret_values() == [path.read_bytes().hex()]


def test_an_id_verifies_only_for_the_exact_command_it_was_derived_for():
    cid = callauth.call_id('0123456789ab', 3, CMD)
    assert callauth.verify(cid, CMD) == ('0123456789ab', 3)
    assert callauth.verify(cid, CMD + ' ') is None and callauth.verify(cid, CMD.replace('/w', '/x')) is None     # one byte
    assert callauth.verify(cid.replace('_3_', '_4_'), CMD) is None and callauth.verify(callauth.call_id('ba9876543210', 3, CMD), CMD) != ('0123456789ab', 3)
    assert callauth.verify('ctx_0123456789ab_3_' + '0' * 16, CMD) is None and callauth.verify('call_123', CMD) is None and callauth.verify(None, CMD) is None


def test_a_key_that_is_not_private_verifies_nothing_and_issues_nothing():
    callauth._key()
    path = privatepaths.CRIA_HOME / 'harness-call.key'
    cid = callauth.call_id('0123456789ab', 0, CMD)
    callauth._cache.clear()
    os.chmod(path, 0o644)
    assert callauth.verify(cid, CMD) is None
    with pytest.raises(callauth.KeyUnavailable):
        callauth.call_id('0123456789ab', 0, CMD)
    assert callauth.secret_values() == []


def test_a_model_authored_id_in_the_verified_namespace_is_given_a_neutral_one_and_cria_ids_are_not_touched_afterwards():
    completion = {'choices': [{'message': {'tool_calls': [
        {'id': callauth.call_id('0123456789ab', 0, CMD), 'function': {}}, {'id': 'call_keep', 'function': {}}, {'id': 'ctx_whatever', 'function': {}}]}}]}
    ids = [c['id'] for c in callauth.neutralize(completion)['choices'][0]['message']['tool_calls']]
    assert ids[1] == 'call_keep' and not ids[0].startswith('ctx_') and not ids[2].startswith('ctx_') and ids[0] != ids[2]


def test_the_ledger_is_private_append_only_first_frame_wins_and_reads_back_after_a_restart():
    ledger = Ledger()
    ledger.append('s1', {'t': 'op', 'op': 'a', 'kind': 'list_dir', 'call': {'id': 'm1'}, 'ctx': {}},
                  {'t': 'step', 'op': 'a', 's': 0, 'id': 'ctx_a_0_x', 'cmd': 'h', 'what': 'ls', 'args': {'wave': 0}})
    ledger.append('s1', {'t': 'frame', 'op': 'a', 's': 0, 'hdr': {'ok': 1}, 'text': 'first'}, {'t': 'frame', 'op': 'a', 's': 0, 'hdr': {'ok': 0}, 'text': 'second'})
    directory = privatepaths.CRIA_HOME / 'ops'
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700 and [stat.S_IMODE(p.stat().st_mode) for p in directory.iterdir()] == [0o600]
    for fresh in (ledger, Ledger()):                                         # the live object and a restarted process
        op = fresh.ops('s1')['a']
        assert op.steps[0].frame == {'hdr': {'ok': 1}, 'text': 'first'} and op.final is None and op.call == {'id': 'm1'}
    assert Ledger().ops('another session') == {}


def test_a_torn_last_line_is_skipped_and_the_next_append_starts_a_fresh_line():
    ledger = Ledger()
    ledger.append('s', {'t': 'op', 'op': 'a', 'kind': 'list_dir', 'call': {}, 'ctx': {}})
    path = next((privatepaths.CRIA_HOME / 'ops').iterdir())
    with open(path, 'ab') as f:
        f.write(b'{"t":"step","op":"a","s":0,"id":"ctx_a_0')                # a writer killed mid-line
    assert Ledger().ops('s')['a'].steps == {}
    ledger.append('s', {'t': 'final', 'op': 'a', 'outcome': 'ran', 'text': 't'})
    assert Ledger().ops('s')['a'].final == {'outcome': 'ran', 'text': 't'}


def test_a_ledger_directory_that_is_a_symlink_or_not_private_is_refused(tmp_path):
    real = tmp_path / 'real'
    real.mkdir(mode=0o700)
    (tmp_path / 'link').symlink_to(real)
    with pytest.raises(LedgerError):
        Ledger(tmp_path / 'link').append('s', {'t': 'op', 'op': 'a', 'kind': 'k', 'call': {}, 'ctx': {}})
    loose = tmp_path / 'loose'
    loose.mkdir(mode=0o755)
    with pytest.raises(LedgerError):
        Ledger(loose).append('s', {'t': 'op', 'op': 'a', 'kind': 'k', 'call': {}, 'ctx': {}})
    assert Ledger(loose).ops('s') == {}


def test_the_key_file_never_exists_half_written_and_concurrent_first_use_agrees_on_one_key(monkeypatch):
    """Review (low): create-then-write left an empty key after a crash, and a reader could see it empty."""
    import threading
    path = privatepaths.CRIA_HOME / 'harness-call.key'
    real_fsync = os.fsync
    def crash(fd):
        raise OSError('killed between create and write')
    monkeypatch.setattr(os, 'fsync', crash)
    callauth._cache.clear()
    with pytest.raises(callauth.KeyUnavailable):
        callauth._key()
    monkeypatch.setattr(os, 'fsync', real_fsync)
    assert not path.exists() and not list(path.parent.glob('.harness-call.key.*'))        # nothing half-made is left behind
    callauth._cache.clear()
    seen, errors = [], []
    def first_use():
        try:
            seen.append(callauth._key())
        except Exception as exc:         # noqa: BLE001
            errors.append(exc)
    threads = [threading.Thread(target=first_use) for _ in range(16)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and len({bytes(k) for k in seen}) == 1 and path.read_bytes() == seen[0] and len(seen[0]) == 32


def test_a_ledger_under_a_symlinked_home_works_but_a_symlinked_ledger_directory_is_refused(tmp_path):
    """Review (low): the walk from / with no-follow made a symlinked /home (an immutable distribution) disable every operation."""
    real = tmp_path / 'real'
    real.mkdir()
    (tmp_path / 'linkhome').symlink_to(real)
    ledger = Ledger(tmp_path / 'linkhome' / 'cria' / 'ops')
    ledger.append('s', {'t': 'op', 'op': 'a', 'kind': 'list_dir', 'call': {'id': 'x'}, 'ctx': {}})
    assert list(ledger.ops('s')) == ['a'] and (real / 'cria' / 'ops').is_dir()
    other = tmp_path / 'evil'
    other.mkdir()
    (real / 'cria' / 'ops2').symlink_to(other)
    with pytest.raises(LedgerError):
        Ledger(tmp_path / 'linkhome' / 'cria' / 'ops2').append('s', {'t': 'op', 'op': 'a', 'kind': 'k', 'call': {}, 'ctx': {}})
    assert not list(other.iterdir())


def test_a_short_write_is_written_on_not_dropped(tmp_path, monkeypatch):
    ledger = Ledger(tmp_path / 'ops')
    real = os.write
    monkeypatch.setattr(os, 'write', lambda fd, data: real(fd, bytes(data)[:7]))          # the kernel took 7 bytes at a time
    ledger.append('s', {'t': 'op', 'op': 'a', 'kind': 'k', 'call': {'id': 'x' * 100}, 'ctx': {}})
    monkeypatch.setattr(os, 'write', real)
    assert ledger.ops('s')['a'].call == {'id': 'x' * 100}
