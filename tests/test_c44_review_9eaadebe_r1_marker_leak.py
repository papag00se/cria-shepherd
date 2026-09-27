"""R1 (independent review 9eaadebe, re-review of 1b7c2f1e): the dropped-prose marker
(`indicators.PROSE_DROPPED_MARKER`, named `loop._PROSE_DROPPED_MARKER` before this fix) reached the
model. `reframe_compaction` was the ONLY reader that removed it, and that only runs at CONTEXT_FIXES
(level 3) and above, for a `user` message carrying a RECOGNIZED Codex-preamble compaction turn. Two
real shapes bypassed it:

1. Engagement level < CONTEXT_FIXES: `server._strip_and_reframe_inbound` gates `reframe_compaction`
   itself on `context_fixes`, but `<<<LOCAL_COMPACT>>>` compactions are recognized at EVERY level
   (`server.py`'s recognizer has no level gate) — a regression against the level-3-only reframe.
2. A harness that stores the compaction reply verbatim under a different role with no Codex preamble
   — a shape C37's OWN harness-agnostic recognizer admits on the way OUT (the harness need not be
   Codex), but `reframe_compaction`'s `_COMPACTION_MARKER` match only recognizes Codex's specific
   preamble text, so it never fires for this shape at any level.

Fix: `indicators.strip_prose_dropped_marker` — an unconditional net, run from
`server._strip_and_reframe_inbound` regardless of level (AFTER `reframe_compaction`, so the
interpreter gets first look at shapes it recognizes) and from `Upstream._prep` at the wire (#24) —
either alone keeps the marker off the wire; together, no single missed call site can leak it. The
marker's own spelling no longer contains "cria" (#17): a third missed path would leak an odd
bracketed token, never the name.
"""

from __future__ import annotations

import json
import re
import unittest
from unittest import mock

from cria import config as cfgmod
from cria import indicators
from cria import loop
from cria import server as srv
from cria.config import Config, RoutingConfig
from cria.upstream import Upstream


class _Rlog:
    phase = "test"

    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))


def _handler(level: int):
    h = srv.CriaHandler.__new__(srv.CriaHandler)
    h.headers = {}
    h.server = type("S", (), {"cfg": Config(routing=RoutingConfig(engagement_level=level))})()
    return h


PRE = ("Another language model started to solve this problem and produced a summary of its thinking "
      "process. You also have access to the state of the tools that were used by that language "
      "model. Use this to build on the work that has already been done and avoid duplicating work. "
      "Here is the summary produced by the other language model, use the information in this "
      "summary to assist with your own analysis:\n")

# Built from `loop._PROSE_DROPPED_MARKER`, not `indicators.PROSE_DROPPED_MARKER` directly, so this
# fixture is valid on BOTH sides of the fix: `loop` re-exports the same marker under its old name
# after the move, and this is exactly what `_harden_compaction_reply` actually prepends either way.
SHIPPED_APPENDIX_ONLY = (loop._PROSE_DROPPED_MARKER + "\n"
                        "FILES ALREADY IN THIS WORKSPACE (on disk right now - do not re-create "
                        "them):\n  README.md")

_CRIA_WORD = re.compile(r"\bcria\b", re.I)


def _assert_never_reaches_the_model(test, final_text: str) -> None:
    """The behavioural check both fails-before tests below share: no marker-shaped text, and
    specifically no literal "cria" word (#17) — checked by substring/regex, never by referencing
    `indicators.PROSE_DROPPED_MARKER` (a name that exists only on the FIXED side, which would turn a
    real behavioural failure on the baseline into a collection-time AttributeError instead)."""
    test.assertNotIn("prose-dropped", final_text)
    test.assertIsNone(_CRIA_WORD.search(final_text))


class MarkerNeverReachesTheModelTests(unittest.TestCase):
    """FAILS-BEFORE (confirmed against 1b7c2f1e, behaviourally — a real AssertionError, the literal
    "cria" word found in the rendered content): `_strip_and_reframe_inbound` only ever removed the
    marker through `reframe_compaction`, which is gated on CONTEXT_FIXES and only recognizes a
    Codex-preamble `user` message — every case below leaked it on that commit."""

    def test_level_below_context_fixes_never_leaks_the_marker(self):
        """A `<<<LOCAL_COMPACT>>>` compaction is recognized at EVERY level (no level gate on
        recognition) — so this shape reaches a real session even when CONTEXT_FIXES is off."""
        h = _handler(level=cfgmod.TOOL_CALL_FIXES)   # below CONTEXT_FIXES on purpose
        self.assertLess(h.server.cfg.routing.engagement_level, cfgmod.CONTEXT_FIXES)
        body = {"messages": [{"role": "user", "content": PRE + SHIPPED_APPENDIX_ONLY}]}
        with mock.patch.object(h, "_bind_workspace_view", lambda *a, **k: None):
            srv.CriaHandler._strip_and_reframe_inbound(h, body, "sid:test", _Rlog())
        _assert_never_reaches_the_model(self, json.dumps(body["messages"]))

    def test_a_non_codex_harness_storing_the_reply_verbatim_never_leaks_the_marker(self):
        """No Codex preamble, no `user` role — a harness that just keeps the compaction reply as an
        assistant turn. `reframe_compaction`'s own recognizer never matches this shape at ANY level;
        the unconditional net must still catch it."""
        h = _handler(level=cfgmod.MAX_ENGAGEMENT_LEVEL)
        body = {"messages": [{"role": "assistant", "content": SHIPPED_APPENDIX_ONLY}]}
        with mock.patch.object(h, "_bind_workspace_view", lambda *a, **k: None):
            srv.CriaHandler._strip_and_reframe_inbound(h, body, "sid:test", _Rlog())
        _assert_never_reaches_the_model(self, json.dumps(body["messages"]))

    def test_list_shaped_content_is_scrubbed_too(self):
        """A Responses-API text part, not a plain string — `reframe_compaction` already handles this
        shape for the Codex-recognized case; the unconditional net must handle it for every shape."""
        h = _handler(level=cfgmod.TOOL_CALL_FIXES)
        body = {"messages": [{"role": "user",
                             "content": [{"type": "input_text", "text": PRE + SHIPPED_APPENDIX_ONLY}]}]}
        with mock.patch.object(h, "_bind_workspace_view", lambda *a, **k: None):
            srv.CriaHandler._strip_and_reframe_inbound(h, body, "sid:test", _Rlog())
        _assert_never_reaches_the_model(self, json.dumps(body["messages"]))

    def test_the_recognized_codex_shape_still_gets_the_interpreted_frame_not_just_a_scrub(self):
        """Regression guard (already true once the B1 template exists, so not itself fails-before
        for R1): the unconditional net must not pre-empt the INTERPRETER — a recognized
        Codex-preamble compaction, at CONTEXT_FIXES, still gets the appendix-aware "retained ground
        truth" framing, not merely a silent removal of the marker leaving the normal "ungrounded
        account" claim."""
        h = _handler(level=cfgmod.MAX_ENGAGEMENT_LEVEL)
        body = {"messages": [{"role": "user", "content": PRE + SHIPPED_APPENDIX_ONLY}]}
        with mock.patch.object(h, "_bind_workspace_view", lambda *a, **k: None):
            srv.CriaHandler._strip_and_reframe_inbound(h, body, "sid:test", _Rlog())
        final = body["messages"][0]["content"]
        _assert_never_reaches_the_model(self, final)
        self.assertNotIn("ungrounded account", final)
        self.assertIn("RE-DERIVED AT THE TIME OF THAT COMPACTION", final)
        self.assertIn("README.md", final)


class WireLevelBackstopTests(unittest.TestCase):
    """`Upstream._prep` is the last point before serialization (#24) — even with EVERY upstream
    scrub skipped, the marker must never reach the wire. (Not fails-before: `Upstream._prep` did not
    scrub this at all on 1b7c2f1e — this documents the NEW backstop, verified against current code.)"""

    def test_prep_alone_strips_the_marker_and_says_no_literal_cria(self):
        up = Upstream(base_url="http://127.0.0.1:1", context_window=100000)
        body = {"model": "x", "messages": [{"role": "user", "content": PRE + SHIPPED_APPENDIX_ONLY}]}
        data, _sent, _cap = up._prep(body, stream=False, rlog=_Rlog())
        _assert_never_reaches_the_model(self, data.decode())

    def test_prep_leaves_an_unmarked_body_byte_identical(self):
        """The scrub must be a no-op — not even a re-serialization difference — when the marker is
        absent, so every model that never triggers this path ships an unchanged body."""
        msgs = [{"role": "user", "content": "ordinary content, no marker here"}]
        scrubbed = indicators.strip_prose_dropped_marker(msgs)
        self.assertIs(scrubbed, msgs)


class MarkerSpellingTests(unittest.TestCase):
    """Not fails-before (the marker did not live in `indicators` at all before this fix) — documents
    the new spelling and the re-export."""

    def test_the_marker_itself_never_spells_cria(self):
        self.assertIsNone(_CRIA_WORD.search(indicators.PROSE_DROPPED_MARKER))

    def test_loop_re_exports_the_same_marker_and_function(self):
        """Existing references (`loop._PROSE_DROPPED_MARKER`, `server._harden_compaction_reply`'s own
        prepend) must keep working unchanged after the move to `indicators`."""
        self.assertIs(loop._PROSE_DROPPED_MARKER, indicators.PROSE_DROPPED_MARKER)
        self.assertIs(loop.strip_prose_dropped_marker, indicators.strip_prose_dropped_marker)


if __name__ == "__main__":
    unittest.main()
