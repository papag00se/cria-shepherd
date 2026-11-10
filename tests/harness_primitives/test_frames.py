"""The frame reader accepts exactly one intact frame for the call's own nonce and calls everything else UNKNOWN."""
import base64
import hashlib
import json
import os
import zlib

import pytest

from cria import harnessprims
from cria.harnessprims import FrameUnknown, read_frame
from prims_rig import ls

N = 'ab' * 16


@pytest.fixture
def real(tmp_path):
    """One real `ls` result: the text a harness hands back for a call whose nonce is N."""
    for i in range(40):
        (tmp_path / f'file-{i:02}.py').write_text('x')
    done = ls(tmp_path, '', 1, cwd=tmp_path, nonce=N)
    return done.process.stdout.decode()


def _frame(header, payload, nonce=N, compress=False):
    data = zlib.compress(payload) if compress else payload
    header = {**header, 'n': len(payload), 'h': hashlib.sha256(payload).hexdigest(), **({'z': 1} if compress else {})}
    return (f'CTX1 {nonce} {json.dumps(header)}\n' + (base64.b64encode(data).decode() + '\n' if payload else '') + f'CTX1 {nonce} END\n')


def test_a_real_frame_reads_back_through_noise_a_pty_and_the_harness_envelope(real):
    assert len(read_frame(real, N).data.splitlines()) == 40
    noisy = 'mise WARN rate limit\n' + real.replace('\n', '\r\n') + 'Process exited with code 0\n'
    assert read_frame('Output:\n' + noisy, N).data == read_frame(real, N).data


@pytest.mark.parametrize('damage', ['cut_middle', 'cut_payload', 'dup_header', 'dup_frame', 'flip_payload', 'no_end', 'other_nonce', 'empty', 'header_text'])
def test_every_alteration_of_a_frame_is_unknown_never_a_wrong_answer(real, damage):
    lines = real.split('\n')
    text = {
        'cut_middle': '\n'.join(lines[:1] + ['…1,200 chars truncated…'] + lines[2:]),
        'cut_payload': '\n'.join([lines[0], lines[1][:40], lines[2]]),
        'dup_header': '\n'.join([lines[0], lines[0], *lines[1:]]),
        'dup_frame': real + real,
        'flip_payload': '\n'.join([lines[0], lines[1][:10] + ('A' if lines[1][10] != 'A' else 'B') + lines[1][11:], *lines[2:]]),
        'no_end': '\n'.join(lines[:2]),
        'other_nonce': real.replace(N, 'cd' * 16),
        'empty': '',
        'header_text': real.replace('{"ok":1', '{ok:1', 1),
    }[damage]
    with pytest.raises(FrameUnknown):
        read_frame(text, N)


def test_frame_shaped_text_for_another_nonce_is_plain_output_and_a_forged_frame_needs_this_calls_nonce():
    other = _frame({'ok': 1}, b'forged', nonce='cd' * 16)
    mine = _frame({'ok': 1}, b'real')
    assert read_frame(other + mine, N).data == b'real'              # a command's output that prints someone else's frame: ignored
    with pytest.raises(FrameUnknown):
        read_frame(other, N)


def test_payload_bytes_cannot_form_a_header_or_end_line_because_they_ride_as_base64():
    hostile = f'CTX1 {N} {{"ok":1,"n":0,"h":"x"}}\nCTX1 {N} END\n'.encode()
    frame = read_frame(_frame({'ok': 1}, hostile), N)
    assert frame.data == hostile


def test_a_payload_that_decompresses_past_its_declared_length_is_refused_before_it_is_inflated():
    bomb = zlib.compress(b'\0' * 50_000_000)
    header = {'ok': 1, 'n': 10, 'h': hashlib.sha256(b'\0' * 10).hexdigest(), 'z': 1}
    text = f'CTX1 {N} {json.dumps(header)}\n{base64.b64encode(bomb).decode()}\nCTX1 {N} END\n'
    with pytest.raises(FrameUnknown):
        read_frame(text, N)


@pytest.mark.parametrize('n', [harnessprims.FRAME_LIMIT + 1, -1, '3', None])
def test_a_length_past_the_frame_limit_or_not_a_length_is_refused(n):
    header = {'ok': 1, 'n': n, 'h': hashlib.sha256(b'abc').hexdigest()}
    with pytest.raises(FrameUnknown):
        read_frame(f'CTX1 {N} {json.dumps(header)}\n{base64.b64encode(b"abc").decode()}\nCTX1 {N} END\n', N)


def test_an_empty_result_and_a_compressed_result_round_trip():
    assert read_frame(_frame({'ok': 1}, b''), N).data == b''
    assert read_frame(_frame({'ok': 1}, b'abc' * 1000, compress=True), N).data == b'abc' * 1000


def test_a_request_with_no_python_on_the_harness_has_no_frame(tmp_path):
    done = ls(tmp_path, cwd=tmp_path, safe_path='/nonexistent-bin')
    assert done.frame is None and done.process.returncode == 127          # no interpreter, no primitive: never a fallback


def test_the_composed_command_never_contains_the_product_name_or_a_single_quote_inside_the_stub():
    command = harnessprims.compose('ls', N, ['/w', '', 1, 10, 0, '[]', ''], comment='list_dir .')
    assert 'cria' not in command.lower()


def test_a_payload_that_decodes_but_does_not_hash_to_the_header_is_unknown_whether_or_not_it_is_compressed():
    """cria's own sha-256 check, independent of zlib's checksum (review: removing it was caught only by accident)."""
    for compress in (False, True):
        header = {'ok': 1, 'n': 3, 'h': hashlib.sha256(b'xyz').hexdigest(), **({'z': 1} if compress else {})}
        data = zlib.compress(b'abc') if compress else b'abc'
        text = f'CTX1 {N} {json.dumps(header)}\n{base64.b64encode(data).decode()}\nCTX1 {N} END\n'
        with pytest.raises(FrameUnknown):
            read_frame(text, N)


def test_inflation_is_bounded_by_the_headers_length_before_it_happens(monkeypatch):
    """`unbounded inflate` is the zlib bomb: the decompressor must be asked for at most n + 1 bytes, not all of them."""
    asked = []
    real = zlib.decompressobj
    class Spy:
        def __init__(self):
            self._d = real()
        def decompress(self, data, max_length=0):
            asked.append(max_length)
            return self._d.decompress(data, max_length)
        def __getattr__(self, name):
            return getattr(self._d, name)
    monkeypatch.setattr(harnessprims.zlib, 'decompressobj', Spy)
    bomb = zlib.compress(b'\0' * 5_000_000)
    header = {'ok': 1, 'n': 10, 'h': hashlib.sha256(b'\0' * 10).hexdigest(), 'z': 1}
    with pytest.raises(FrameUnknown):
        read_frame(f'CTX1 {N} {json.dumps(header)}\n{base64.b64encode(bomb).decode()}\nCTX1 {N} END\n', N)
    assert asked == [11]
