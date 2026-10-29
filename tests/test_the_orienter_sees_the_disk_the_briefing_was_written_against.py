"""After a harness compaction the post-compaction orienter must be shown the workspace listing.

The workspace view is rebuilt on every request from the surveys in the conversation, and the
compaction has just removed all of them, so `workspace_inventory` returned "" for the orienter and its
WORKSPACE INVENTORY section was empty in 28 of 32 captured reasoner prompts. Walked on ornith1.5_9b /
Java overnight run 4 (session 01a18337, reasoner 0043): with no listing it read the ledger's folded
`src/  (main)` line as the whole tree, told the coder the inventory listed only README.md, pom.xml,
data/ and target/ (not the Importer.java the session had rewritten twice), and to "Re-establish a
baseline … by running the importer". The coder restored the seed over its rewrite and the run ended at 2%.

The compaction request still had the survey; cria's hardener showed it to the briefing writer. That
listing now rides on the producer record and reaches the orienter when this request has none of its own.
"""
import copy

import pytest

from cria import assistruntime, groundtruth, indicators, loop, memoryhandoff as memory, server
from cria.config import Role
from test_generation_driver_policy import setup_driver
from test_loop import _Rlog
from tests.test_harness_memory_boundaries import ResponseProvider, response_handler
from tests.test_harness_memory_source import Log, completion, history

TASK = "Make the importer 4x faster. Add REVIEW.md."
LISTING = ("FILES ON DISK — WORKSPACE SURVEY (names observed, newest first).\n"
           "  src/main/java/pipeline/Importer.java (11796 B)\n  pom.xml (980 B)\n"
           "The underlying survey is complete and current; this filtered inventory does not list every path.")


def _author_grounding(driver, sess, body, monkeypatch):
    seen = []

    def author(chat, role, system, grounding, log, **kwargs):
        seen.append(grounding)
        return "Inspect Importer.java before continuing."
    monkeypatch.setattr(loop, "summarize", author)
    with assistruntime.bound(assistruntime.AssistRuntime.select(level=5)):
        driver._prepare_coder_context(sess, body, _Rlog(), synthetic=False, rewritten=True)
    assert seen     # the author's call comes first; a name-grounding question may follow it
    return seen[0]


def _session_after_harness_compaction(continuation_text, origin_continuation):
    driver, sess, body = setup_driver()
    driver._ctx.reasoner_role = Role(name="reasoner", backend="local")
    sess.workspace_root = "/w"                    # no survey bound: the view has nothing to say
    origin = loop._HandoffOrigin("Built Importer.java.", "", False, continuation=origin_continuation)
    origin.inventory = LISTING                    # what the hardener recorded at the boundary
    origin.inventory_root = "/w"                  # ...for this workspace root
    sess.handoff_origin = origin
    body["messages"] = [{"role": "user", "content": TASK},
                        {"role": "user", "content": continuation_text}]
    return driver, sess, body


def test_the_orienter_is_shown_the_survey_the_briefing_was_written_against(monkeypatch):
    summary = f"{loop.CONTINUATION_MARKER} Earlier: rewrote Importer.java with OpenCSV."
    driver, sess, body = _session_after_harness_compaction(summary, summary)
    grounding = _author_grounding(driver, sess, body, monkeypatch)
    inventory = grounding.split("WORKSPACE INVENTORY", 1)[1]
    assert "src/main/java/pipeline/Importer.java (11796 B)" in inventory


def test_another_boundarys_listing_is_never_shown(monkeypatch):
    """The recorded listing belongs to the continuation cria produced; a different one gets none."""
    summary = f"{loop.CONTINUATION_MARKER} Earlier: rewrote Importer.java with OpenCSV."
    other = f"{loop.CONTINUATION_MARKER} A different handoff cria did not produce."
    driver, sess, body = _session_after_harness_compaction(other, summary)
    grounding = _author_grounding(driver, sess, body, monkeypatch)
    assert "Importer.java (11796 B)" not in grounding


def test_another_roots_listing_is_never_shown(monkeypatch):
    """A listing recorded for one workspace root is not this session's disk once the root differs."""
    summary = f"{loop.CONTINUATION_MARKER} Earlier: rewrote Importer.java with OpenCSV."
    driver, sess, body = _session_after_harness_compaction(summary, summary)
    sess.workspace_root = "/elsewhere"
    grounding = _author_grounding(driver, sess, body, monkeypatch)
    assert "Importer.java (11796 B)" not in grounding


def test_this_requests_own_survey_wins(monkeypatch):
    summary = f"{loop.CONTINUATION_MARKER} Earlier: rewrote Importer.java with OpenCSV."
    driver, sess, body = _session_after_harness_compaction(summary, summary)
    monkeypatch.setattr(loop, "workspace_inventory", lambda root, flavor="judge", compacted=False:
                        "FILES ON DISK — WORKSPACE SURVEY\n  src/Fresh.java (5 B)")
    grounding = _author_grounding(driver, sess, body, monkeypatch)
    assert "src/Fresh.java" in grounding and "Importer.java (11796 B)" not in grounding


def test_the_hardener_records_the_listing_it_showed_the_writer(monkeypatch):
    """Server side: the producer record carries the exact inventory text the writer received."""
    shown = []

    def inventory(root, flavor="judge", compacted=False):
        text = f"FILES ON DISK — WORKSPACE SURVEY of {root}\n  src/main/java/pipeline/Importer.java (11796 B)"
        shown.append(text)
        return text
    monkeypatch.setattr(groundtruth, "workspace_inventory", inventory)
    monkeypatch.setattr(server, "_session_cwd", lambda *a, **k: "/w")
    root = assistruntime.AssistRuntime.select(level=3, registrations=(memory.DEFINITION,))
    provider = ResponseProvider(completion("Next step: rewrite the importer."))   # rejected -> ledger
    handler, session = response_handler(provider, "sid:boundary-inventory")
    handler.server.pilot_runtime = root
    body = {"messages": history()}
    body["messages"][-1]["content"] = "<<<LOCAL_COMPACT>>> Summarize"
    with assistruntime.bound(root):
        handler._produce_completion(body, Log(), "sid:boundary-inventory")
    origin = session.handoff_origin
    assert origin is not None and shown
    assert origin.inventory == shown[-1]
    assert origin.inventory_root == "/w"
