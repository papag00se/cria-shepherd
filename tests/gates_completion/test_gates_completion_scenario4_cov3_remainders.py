"""probegate's bounded session memories and its refusals to guess: the per-transport fact table and the spool-cleanup queue forget the OLDEST rather than grow, a transport that is
finished, failed or never framed offers no further page request, an empty workspace names no directory, and a location is read only from the shapes cria parses."""
import os
from collections import OrderedDict

import pytest

from cria import probegate
from gates_completion_helpers import cand, deliver, gates_completion_view, new_plan, sec  # noqa: F401  (autouse fixture)


def test_the_transport_fact_table_forgets_the_oldest_transport_and_keeps_the_newest(monkeypatch):
    """Per-section facts (command, kind, composed-by-cria) outlive the live plan so an older gate still names its command; past the bound the OLDEST is forgotten, never a recent one."""
    monkeypatch.setattr(probegate, "_transport_facts", OrderedDict())
    monkeypatch.setattr(probegate, "_TRANSPORT_FACTS_MAX", 3)
    ids = [f"{n:024x}" for n in range(1, 6)]
    for n, tid in enumerate(ids):
        probegate._register_transport_facts(tid, [cand(["pytest", f"t{n}"])], "/ws", scope_known=True)
    assert [bool(probegate._facts_for_transport(t)) for t in ids] == [False, False, True, True, True]
    assert probegate._facts_for_transport(ids[-1])[0].command == ("pytest", "t4")


def test_the_spool_cleanup_queue_is_bounded_by_forgetting_not_by_growing(monkeypatch):
    """A spool is queued for removal only after its transport verified; with more than 256 workspaces waiting the queue is dropped whole (a leftover spool is private scratch, never evidence)
    and the newest workspace is queued afresh; nothing is queued without a workspace or a path."""
    monkeypatch.setattr(probegate, "_SPOOL_CLEANUP_QUEUE", {})
    probegate._queue_spool_cleanup("", "/tmp/.cria-gate-a.x")
    probegate._queue_spool_cleanup("/ws", "")
    assert probegate._SPOOL_CLEANUP_QUEUE == {}
    for n in range(257):
        probegate._queue_spool_cleanup(f"/ws{n}", f"/tmp/.cria-gate-{n}.x")
    assert len(probegate._SPOOL_CLEANUP_QUEUE) == 257
    probegate._queue_spool_cleanup("/last", "/tmp/.cria-gate-last.x")
    assert list(probegate._SPOOL_CLEANUP_QUEUE) == ["/last"]
    assert "/tmp/.cria-gate-last.x" in probegate.spool_cleanup_command("/last") and probegate.spool_cleanup_command("/ws0") == ""


def test_a_transport_that_cannot_continue_offers_no_page_request():
    """No next read for a transport that was never framed, is already whole, or failed (cria never re-asks a harness about bytes it will not use); a live one with a learned path does."""
    plan = new_plan(script="LAUNCH")
    assert probegate.continue_transport_command(plan) == "LAUNCH"
    assert probegate.continue_transport_command(probegate.GatePlan("")) == ""
    assert probegate.continue_transport_command(deliver(new_plan(), sec(0, "ok"))) == ""
    failed = new_plan(script="LAUNCH")
    probegate.fail_transport(failed, "bad page")
    assert probegate.continue_transport_command(failed) == ""


def test_an_empty_workspace_names_no_directory_and_an_unknown_section_is_never_a_hard_failure():
    """`abspath("")` would name cria's own directory; and a section id that maps to no discovered probe cannot be called a hard failure."""
    here = os.getcwd()
    assert probegate._checks_ran_elsewhere("", [cand(["pytest"], wd=here + "/sub")]) == ""
    assert "sub" in probegate._checks_ran_elsewhere(here, [cand(["pytest"], wd=here + "/sub")])
    plan = new_plan(candidates=[cand(["pytest"])])
    assert [probegate._is_hard_failure(plan, sid) for sid in ("probe-9", "probe-x", "git")] == [False, False, False]
    assert probegate.gate_sections(sec(0, "ok"), plan) == ({}, "") and probegate.gate_sections(sec(0, "ok"), None) == ({}, "")


@pytest.mark.parametrize("finding,location", [
    ("src/a.py:9: boom", ("src/a.py", 9)),
    ("config.toml: invalid key (at line 3, column 5)", ("config.toml", 3)),
    ("config.toml: invalid key", None),
    ("just words", None),
])
def test_a_finding_location_is_read_only_from_the_shapes_cria_parses(finding, location):
    """`path:line:` compiler shapes and the one `(at line N, column M)` shape give a location; prose gives none."""
    assert probegate._finding_location(finding) == location
