"""Minimum-width capture names must retain their identity after counter loss.

All records are made by production capture writers in pytest temporary directories.
Seeding the in-memory counter avoids making ten thousand irrelevant calls.
"""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from cria import callcapture


class Log:
    session = "width-restart"
    _turn = "t1"

    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))


@pytest.fixture
def captures(tmp_path, monkeypatch):
    monkeypatch.setattr(callcapture, "_seq", {})
    return tmp_path, Log()


def upstream(captures, text, phase="coder-s1"):
    root, log = captures
    body = {"model": "fixture", "messages": [{"role": "user", "content": text}]}
    path = callcapture.capture(body, log, calls_dir=root, phase=phase, rendered=text)
    assert path is not None
    response = {"choices": [{"message": {"role": "assistant", "content": text}}]}
    assert callcapture.capture_response(path, response, log) is not None
    assert json.loads(Path(path).read_text())["body"] == body
    return Path(path)


def snapshot(directory):
    return {p: p.read_bytes() for p in directory.rglob("*") if p.is_file()}


@pytest.mark.parametrize("boundary", [10000, 100000])
def test_real_capture_restart_preserves_request_prompt_and_response(captures, boundary):
    root, log = captures
    callcapture._seq[callcapture.session_dirname(log.session)] = boundary - 2
    upstream(captures, "before boundary")
    last = upstream(captures, "at boundary")
    assert last.name == f"{boundary}-coder-s1.json"
    before = snapshot(root)
    callcapture._seq.clear()  # process restart: retain disk, lose only counter
    resumed = upstream(captures, "after restart")
    assert snapshot(root).items() >= before.items(), "restart overwrote existing capture bytes"
    assert resumed.name == f"{boundary + 1}-coder-s1.json"
    assert log.events[-2][1]["seq"] == boundary + 1


@pytest.mark.parametrize("companion", ["prompt", "response"])
def test_remaining_companion_reserves_wide_sequence(captures, companion):
    root, log = captures
    callcapture._seq[callcapture.session_dirname(log.session)] = 99999
    request = upstream(captures, "retained evidence")
    keep = request.with_suffix(".prompt.txt") if companion == "prompt" else request.with_suffix(".response.json")
    for path in request.parent.iterdir():
        if path != keep:
            path.unlink()
    before = snapshot(root)
    callcapture._seq.clear()
    resumed = upstream(captures, "new evidence", phase="critic")
    assert resumed.name == "100001-critic.json"
    assert snapshot(root).items() >= before.items()


def test_sequential_threaded_and_repeated_restart_share_phase_sequence(captures):
    root, log = captures
    callcapture._seq[callcapture.session_dirname(log.session)] = 9998
    first = upstream(captures, "first", "planner")
    second = upstream(captures, "second", "coder-s1")
    assert [json.loads(p.read_text())["seq"] for p in (first, second)] == [9999, 10000]
    before = snapshot(root)
    callcapture._seq.clear()
    with ThreadPoolExecutor(max_workers=8) as pool:
        paths = list(pool.map(lambda i: upstream(captures, str(i), ["critic", "coder-s2"][i % 2]), range(32)))
    assert len(set(paths)) == 32
    assert sorted(json.loads(p.read_text())["seq"] for p in paths) == list(range(10001, 10033))
    assert snapshot(root).items() >= before.items()
    for seq in (10033, 10034):
        callcapture._seq.clear()
        assert json.loads(upstream(captures, str(seq), "proxy").read_text())["seq"] == seq


def native(captures, namespace="native-a", phase="retrospective"):
    root, log = captures
    request, response = {"input": "whole native input"}, {"label": "result", "values": [1, 2]}
    path = callcapture.capture_native(request, response, log, calls_dir=root, namespace=namespace, phase=phase)
    assert path is not None
    record = json.loads(Path(path).read_text())
    assert record["request"] == request and record["response"] == response
    assert "body" not in record
    return Path(path), record["seq"]


def test_native_restart_keeps_wide_sequence_and_namespaces_independent(captures):
    root, log = captures
    sess = callcapture.session_dirname(log.session)
    callcapture._seq[f"{sess}/native-a"] = 9998
    assert native(captures)[1] == 9999
    assert native(captures)[1] == 10000
    before = snapshot(root)
    callcapture._seq.clear()
    assert native(captures, phase="dictation")[1] == 10001
    assert native(captures, "native-b")[1] == 1
    assert not log.events  # native receipts never emit upstream events
    assert json.loads(upstream(captures, "upstream").read_text())["seq"] == 1
    assert snapshot(root).items() >= before.items()


def test_native_exclusive_creation_preserves_existing_bytes_with_stale_counter(captures):
    root, log = captures
    sess = callcapture.session_dirname(log.session)
    callcapture._seq[f"{sess}/native-a"] = 9999
    path, seq = native(captures)
    assert seq == 10000
    before = path.read_bytes()
    # A stale allocator proposes an occupied path: exercise the real exclusive-open retry.
    callcapture._seq[f"{sess}/native-a"] = 9999
    next_path, seq = native(captures)
    assert seq == 10001 and next_path != path
    assert path.read_bytes() == before


def test_fresh_sessions_and_namespaces_start_at_one(captures):
    assert json.loads(upstream(captures, "fresh").read_text())["seq"] == 1
    assert native(captures)[1] == 1
    assert native(captures, "native-b")[1] == 1
    root, _ = captures
    other = Log()
    other.session = "other-session"
    assert json.loads(upstream((root, other), "other").read_text())["seq"] == 1
