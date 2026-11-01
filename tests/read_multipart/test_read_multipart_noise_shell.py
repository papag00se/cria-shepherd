"""A login shell that prints around the program (a chatty .bash_profile, mise, direnv) must not cost the read its pages.

The rig is a REAL `bash -lc` on a REAL PTY (stdout and stderr both to the terminal, LF -> CRLF) whose profile prints N bytes on
stdout and on stderr before the program and N bytes from an EXIT trap after it, wrapped the way the pinned Codex wraps a result:
over 10,000 bytes it keeps the first and last 5,000 and says `Warning: truncated output` (the exact shape of the wave-10 E2EA
capture /var/tmp/w10-e2ea/calls/t7/*/0003-coder-s1.prompt.txt: 17,898 bytes in, head 5,000, `…7898 chars truncated…`, tail 5,000).
Before the fix the page record (9,9xx bytes) plus any noise was cut in the middle and the whole read ended unverified.
"""
import os, pty, subprocess

import pytest
import read_multipart_helpers as rig
from cria import bodykeys
from read_multipart_helpers import HEX, isolated_home, page_through, start  # noqa: F401

MISE = 'mise WARN  GitHub rate limit exceeded. Resets at 2026-10-31 16:32:13 -07:00\n'


def noise(n):
    return (MISE * (n // len(MISE) + 1))[:n]


def codex_result(raw: bytes, code: int = 0) -> str:
    """The harness's own envelope: whole under 10,000 bytes, else head 5,000 + marker + tail 5,000 behind the cut warning."""
    tokens = -(-len(raw) // 4)
    head = 'Chunk ID: 3a9c1e\nWall time: 1.1236 seconds\nProcess exited with code %d\nOriginal token count: %d\nOutput:\n' % (code, tokens)
    text = raw.decode('utf-8', 'replace')
    if len(raw) <= 10000:
        return head + text
    return (head + 'Warning: truncated output (original token count: %d)\nTotal output lines: %d\n\n' % (tokens, raw.count(b'\n'))
            + text[:5000] + '…%d chars truncated…' % (len(text) - 10000) + text[-5000:])


@pytest.fixture
def noisy(tmp_path, monkeypatch):
    """Install a noisy harness: returns a setter `noisy(before_out, before_err, after)` and the list of raw results it produced."""
    shell_home = tmp_path / 'shellhome'; shell_home.mkdir()
    cfg = {'before_out': 0, 'before_err': 0, 'after': 0}; raw_results = []
    (shell_home / '.bash_profile').write_text('printf %s "$N_OUT"; printf %s "$N_ERR" >&2; trap \'printf %s "$N_AFTER"\' EXIT\n')

    def run(call):
        import json
        command = json.loads(call['function']['arguments'])['cmd']
        env = dict(os.environ, HOME=str(shell_home), N_OUT=noise(cfg['before_out']), N_ERR=noise(cfg['before_err']), N_AFTER=noise(cfg['after']))
        master, slave = pty.openpty()
        p = subprocess.Popen(['bash', '-lc', command], stdout=slave, stderr=slave, env=env, cwd=tmp_path); os.close(slave); data = bytearray()
        while True:
            try: chunk = os.read(master, 65536)
            except OSError: break
            if not chunk: break
            data.extend(chunk)
        os.close(master); code = p.wait()
        raw_results.append(bytes(data))
        return codex_result(bytes(data), code)
    monkeypatch.setattr(rig, 'run_call', run)

    def setter(before_out=0, before_err=0, after=0): cfg.update(before_out=before_out, before_err=before_err, after=after)
    setter.raw = raw_results
    return setter


def read_all(tmp_path, data=HEX):
    bridge, messages, _ = start(tmp_path, data)
    return page_through(bridge, messages)


SHAPES = {'clean': (0, 0, 0), 'out-1k': (1000, 0, 0), 'err-1k': (0, 1000, 0), 'both-1k-and-after': (1000, 1000, 1000), 'out-7k': (7000, 0, 0),
          'err-7k': (0, 7000, 0), 'split-3500': (3500, 3500, 0), 'after-7k': (0, 0, 7000), 'out-12k': (12000, 0, 0), 'after-12k': (0, 0, 12000), 'out-7k-after-1k': (7000, 0, 1000)}


@pytest.mark.parametrize('shape', SHAPES)
def test_a_chatty_login_shell_does_not_cost_the_read_its_verified_pages(tmp_path, noisy, shape):
    """The 45 KB file arrives verified, byte for byte, whatever the shell prints before and after the program (stdout and stderr)."""
    noisy(*SHAPES[shape])
    data = HEX[:12000] if '12k' in shape else HEX         # 12 KB of noise leaves ~2 KB pages: a smaller file keeps the real-bash run short
    projected, facts = read_all(tmp_path, data)
    assert [f.exact_body for f in facts] == [data.encode()]
    tool = [m for m in projected if m.get('role') == 'tool'][0]
    assert bodykeys.MULTIPART_UNVERIFIED not in tool


def test_noise_on_both_sides_that_leaves_no_room_ends_labelled_never_wrong(tmp_path, noisy):
    """7 KB before AND 7 KB after: every cut hides the record in the middle. The read says it is unverified; no byte of it is claimed."""
    noisy(7000, 0, 7000)
    projected, facts = read_all(tmp_path)
    tool = [m for m in projected if m.get('role') == 'tool'][0]
    assert facts == () or all(f.exact_body != HEX.encode() for f in facts)
    assert bodykeys.MULTIPART_UNVERIFIED in tool


@pytest.mark.parametrize('n', [7000, 12000])
def test_the_noise_is_measured_once_and_later_pages_are_sized_to_it(tmp_path, noisy, n):
    """One wasted full page and one probe, then the measured noise sizes every page: the room left (10,000 - noise) while there is
    one, else the size of the probe that was seen to arrive whole. The measure is exact even when the harness cut the result: the
    12 KB probe was cut, and its record plus the harness's own `N chars truncated` count give the shell's real output."""
    noisy(n, 0, 0)
    bridge, messages, _ = start(tmp_path, HEX[:12000])
    page_through(bridge, messages)
    a = bridge.sessions['s']['original'].assembly
    on_the_wire = n + noise(n).count('\n')            # the PTY turns each noise LF into CRLF: measured, not computed from the shell
    assert a.noise - on_the_wire == (n == 12000) and a.refetches == 1     # a cut result's blank line after `Total output lines` counts as one noise byte
    assert a.limit == max(10000 - a.noise, a.intact) and (a.intact == 0) == (n == 7000)
    sizes = [len(r) for r in noisy.raw]
    assert sizes[0] > 16000 and (sizes[1] <= 10000) == (n == 7000)


def test_a_restart_in_the_middle_of_a_noisy_read_replays_the_cut_pages_and_the_sizing(tmp_path, noisy):
    """The re-fetch and the measured sizing are rebuilt from the stored results alone: a server restarted after every page issues the
    same next command (the state loader refuses a changed continuation) and the read still ends verified."""
    from cria.multipart_bridge import Bridge
    noisy(7000, 0, 0)
    bridge, messages, _ = start(tmp_path, HEX[:12000], name='f')
    storage = str(tmp_path / 'state-f')
    projected, facts = page_through(bridge, messages, restart=lambda: Bridge(storage))
    assert [f.exact_body for f in facts] == [HEX[:12000].encode()]
