"""Gate transport is verified before it is believed: paged, spooled, private-namespace evidence is UNKNOWN until proven whole."""
import base64
import glob
import json
import os
import time
import zlib

import pytest

from cria import probegate, writeproxy
from gates_completion_helpers import gates_completion_view, harness_dir, new_plan, page, real_gate, run_in_harness, sec  # noqa: F401  (autouse fixture)

RAW = sec(0, "x" * 70 + "\nsrc/a.py:9: boom", 1) + sec(1, "3 passed")
B64 = lambda s: base64.b64encode(s.encode()).decode()  # noqa: E731
YIELD_CUT = "Chunk ID: 34454d\nWall time: 30.0008 seconds\nProcess running with session ID 51757\nOutput:\n"


def running(plan, path=None):
    return "\n".join([probegate._transport_marker(plan.transport_id),
                      "path\t" + B64(path or f"/tmp/.cria-gate-{plan.transport_id}.spool"), "running\t1.0",
                      probegate._transport_marker(plan.transport_id, end=True)])


def test_paged_stream_completes_only_when_every_byte_and_the_hash_agree():
    """Pages are `pending` until the declared total verifies; only then is the stream readable."""
    plan = new_plan()
    out = probegate.interpret_gate(plan, page(plan, RAW, 0, 40))
    assert out.transport_pending and not out.ran and probegate.transported_result(plan) == ""
    assert probegate.ingest_transport(plan, page(plan, RAW, 40, 40)) == "pending"
    assert probegate.ingest_transport(plan, page(plan, RAW, 80)) == "complete"
    assert probegate.transported_result(plan) == RAW and plan.transport_total == len(RAW.encode())
    last = new_plan()                                                   # one byte short of the declared total is still pending
    assert probegate.ingest_transport(last, page(last, RAW, 0, len(RAW.encode()) - 1)) == "pending"


@pytest.mark.parametrize("over", [
    dict(sha256="0" * 64), dict(total="5"), dict(path=B64("/tmp/.cria-gate-ffffffffffffffffffffffff.spool")),
    dict(data="!!not-base64"), dict(sha256=None), dict(enc="gzip"),
], ids=["bad-hash", "short-total", "foreign-spool", "undecodable", "missing-field", "unknown-enc"])
def test_a_page_that_disagrees_with_itself_is_terminal_unknown_never_clean(over):
    """Every envelope check fails CLOSED: UNKNOWN, no readable bytes, and the gate result says so."""
    plan = new_plan()
    assert probegate.ingest_transport(plan, page(plan, RAW, **over)) == "unknown"
    out = probegate.interpret_gate(plan, page(plan, RAW))        # even a later perfect page cannot revive it
    assert out.transport_unknown and not out.ran and probegate.transported_result(plan) == ""


@pytest.mark.parametrize("second", [
    lambda p: page(p, RAW, 0, 40),                                   # replayed page 0
    lambda p: page(p, RAW, 60),                                      # a skipped range
    lambda p: page(p, RAW, 40, total="999"),                         # total changed midstream
    lambda p: page(p, RAW, 40, path=B64(f"/tmp/.cria-gate-{p.transport_id}.other")),   # spool changed
    lambda p: page(p, RAW, 40)[:-20],                                # cut before its closing marker
    lambda p: (page(p, RAW, 40) + "\n") * 2,                         # doubled envelope
], ids=["replay", "gap", "total-changed", "spool-changed", "cut", "doubled"])
def test_a_second_page_that_contradicts_the_first_or_is_malformed_is_unknown(second):
    """Reordered, replayed, altered, cut or doubled pages never assemble into evidence."""
    plan = new_plan()
    assert probegate.ingest_transport(plan, page(plan, RAW, 0, 40)) == "pending"
    assert probegate.ingest_transport(plan, second(plan)) == "unknown"


def test_a_zlib_page_with_trailing_bytes_or_an_expansion_bomb_is_unknown():
    """N1: pages may be zlib-packed (the real-shell test below proves they round-trip); trailing bytes and a bomb are UNKNOWN."""
    raw = ("x" * 100 + "\n") * 600
    for blob in (zlib.compress(raw.encode()) + b"extra", zlib.compress(b"\0" * probegate.TRANSPORT_RAW_PAGE_MAX * 20)):
        bad = new_plan()
        assert probegate.ingest_transport(bad, page(bad, raw, data=base64.b64encode(blob).decode(), enc="zlib")) == "unknown"


def test_a_harness_yield_is_retried_within_bounds_then_fails_closed():
    """P18 Orders: Codex answered a 5-minute gate with 'Process running…' and no envelope; 28 of 29 gates went UNKNOWN.
    Silence is retried, but only twice in a row and never past the plan's own deadline."""
    plan = new_plan()
    assert probegate.ingest_transport(plan, YIELD_CUT) == "running"
    out = probegate.interpret_gate(plan, YIELD_CUT)
    assert out.transport_pending and not out.transport_unknown and plan.transport_error == ""
    plan = new_plan(transport_deadline_s=1e6)
    for _ in range(probegate.GATE_OPENERLESS_MAX):
        assert probegate.ingest_transport(plan, YIELD_CUT) == "running"
    assert probegate.ingest_transport(plan, YIELD_CUT) == "unknown" and "repeatedly" in plan.transport_error
    plan = new_plan()
    for _ in range(6):                                              # a real envelope between silences resets the streak
        assert probegate.ingest_transport(plan, YIELD_CUT) == "running"
        assert probegate.ingest_transport(plan, running(plan)) == "running"
    late = new_plan(transport_deadline_s=5.0, transport_started=time.monotonic() - 60)
    assert probegate.ingest_transport(late, running(late)) == "unknown" and "exceeded" in late.transport_error
    assert probegate.interpret_gate(late, "").transport_unknown
    for nothing in ("", 'Rejected("rm -f style commands are not permitted")'):      # nothing launched / refused: terminal at once
        assert probegate.ingest_transport(new_plan(), nothing) == "unknown"


def test_typed_envelopes_learn_or_end_the_transport():
    """running teaches the spool path (later polls are narrow reads); gone / helper-gone / foreign path are terminal."""
    plan = new_plan(script="LAUNCH-SCRIPT")
    assert probegate.continue_transport_command(plan) == "LAUNCH-SCRIPT"
    assert probegate.ingest_transport(plan, running(plan)) == "running"
    assert plan.transport_path and "LAUNCH-SCRIPT" not in probegate.continue_transport_command(plan)
    assert probegate.ingest_transport(plan, running(plan, f"/tmp/.cria-gate-{plan.transport_id}.v2")) == "unknown"
    for fields, why, ready in ((["gone\t1"], "gone", True), (["helper-gone\t1"], "helper", False)):
        p = new_plan(helpers_ready=True)
        env = "\n".join([probegate._transport_marker(p.transport_id), *fields, probegate._transport_marker(p.transport_id, end=True)])
        assert probegate.ingest_transport(p, env) == "unknown" and why in p.transport_error and p.helpers_ready is ready
    foreign = new_plan()
    assert probegate.ingest_transport(foreign, running(foreign, "/tmp/.cria-gate-deadbeefdeadbeefdeadbeef.spool")) == "unknown"


def test_a_verified_stream_whose_worker_declared_no_extents_is_unknown():
    """Hash-verified bytes still carry no meaning without the producer's declared extents: UNKNOWN, never a pass."""
    plan = new_plan()
    assert probegate.ingest_transport(plan, page(plan, RAW, bounds=None)) == "complete"
    out = probegate.interpret_gate(plan, "")
    assert out.transport_unknown and not out.ran


def test_the_continuation_command_is_crias_own_and_not_refused_as_external():
    """cart-billing-go 20260906: the write guard refused the gate's own `/tmp/.cria-gate-*` pager as an external path."""
    plan = new_plan("76d2c884f9d09725178dd678", workspace="/ws", transport_path="/tmp/.cria-gate-76d2c884f9d09725178dd678.x")
    plan.transport_data = bytearray(b"first page")
    cmd = probegate.continue_transport_command(plan)
    assert "/tmp/.cria-gate-" in cmd
    assert writeproxy._external_refusal("exec_command", {"cmd": cmd}, {"arguments": json.dumps({"cmd": cmd})},
                                        injected=set(), level="none", workspace="/ws") is None


NOISE = ("import hashlib,sys\nfor i in range(900): print('noise-%04d-'%i+hashlib.sha256(str(i).encode()).hexdigest())\n"
         "print('src/middle.py:73: MIDDLE_FAILURE'); print('FINAL_TALLY: 1 failed'); sys.exit(1)")


def test_a_real_gate_run_under_sh_pages_home_every_byte_and_a_lost_helper_is_unknown(tmp_path, monkeypatch):
    """Real script, real shell: >2 pages assemble the complete stream; a helper deleted mid-transport makes the next poll UNKNOWN."""
    plan, outcome, pages = real_gate(tmp_path, monkeypatch, NOISE)
    assert len(pages) > 2 and outcome.ran and not outcome.transport_unknown
    full = probegate.transported_result(plan)
    assert "noise-0000" in full and "MIDDLE_FAILURE" in full and "FINAL_TALLY" in full and len(full.encode()) == plan.transport_total
    assert any("middle.py" in f.file for f in outcome.report.results[0].findings)
    fresh = probegate.plan_gate(str(tmp_path))
    assert probegate.ingest_transport(fresh, run_in_harness(fresh.script, tmp_path, "sh")) == "pending"
    for helper in glob.glob(str(harness_dir(tmp_path) / ".cria-helper-*")):
        os.unlink(helper)
    poll = run_in_harness(probegate.continue_transport_command(fresh), tmp_path)
    assert probegate.ingest_transport(fresh, poll) == "unknown" and not fresh.transport_complete
