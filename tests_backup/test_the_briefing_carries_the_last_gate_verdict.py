"""The compaction briefing looked up the session under a key the store is never written under.

`_last_checks_note` exists to bolt the last gate verdict onto the model-authored briefing verbatim —
"deterministic check truth the model-authored briefing kept omitting", in its own docstring. The
briefing is the ONLY surviving record of the session once the transcript is cut, so a briefing
without it leaves the compactor describing a broken build from memory.

It resolved the session with `session_key({}, messages)` — an EMPTY headers dict. `session_key` reads
the session header first and falls back to a hash of the conversation's first user message, so with
no headers it can only ever return the `task:` form. The loop's store is written under the caller's
key, which under Codex is `sid:<prompt_cache_key>`. The lookup therefore missed on every compaction
of every session, silently: `_last_checks_note` returned "" as though the gate had never spoken, and
`_session_gate_plan` returned None the same way.

Walked on `feed-pipeline-java x nemotron-elastic` 20260820T103857. Zero `LATEST CHECK RESULTS` blocks
appear in that run's 75 prompts, while the workspace inventory — which needs no store lookup —
appears in six. Left to describe the build itself, the compactor wrote that the code "still
references `CSVRecord` … without importing the class": the import was line 5, and the real fault was
that the class does not exist in that package. cria carried that sentence as `⟦ctx:continuation⟧` for
the remaining twenty calls and a steer turned it into a numbered work order (#5b).

The caller already holds the right key and passes it now. #11b: a mechanism must reach what it judges.
"""

import json
import unittest
from types import SimpleNamespace

from cria import server as srv


GATE_TEXT = "Importer.java:[5,19] cannot find symbol\n  symbol:   class CSVRecord"
CALLER_KEY = "sid:01a02041-2b68-7673-9fbe-8cd35911109e"


class _NullRlog:
    def emit(self, *a, **k):
        pass


class _Srv:
    class cfg:
        class routing:
            roles = {}


def _server_with_gate(asked: list):
    sess = SimpleNamespace(gate_plan=None, last_gate_flag=GATE_TEXT)

    def _get(k):
        asked.append(k)
        return sess if k == CALLER_KEY else None

    s = _Srv()
    s.loop = SimpleNamespace(_store=SimpleNamespace(get=_get))
    return s


def _msgs():
    return [{"role": "user", "content": "Fix the supplier feed importer."},
            {"role": "assistant", "content": "done"}]


def _briefing(comp):
    return (comp["choices"][0]["message"].get("content") or "")


class TheStoreIsAskedForTheCallersKeyTests(unittest.TestCase):
    def test_the_gate_verdict_reaches_the_briefing(self):
        asked: list = []
        comp = {"choices": [{"message": {"role": "assistant", "content": "a briefing"}}]}
        out = srv._harden_compaction_reply(comp, {"messages": _msgs()}, provider=None,
                                           server=_server_with_gate(asked), rlog=_NullRlog(),
                                           sess_key=CALLER_KEY)
        self.assertIn("LATEST CHECK RESULTS", _briefing(out))
        self.assertIn("class CSVRecord", _briefing(out))

    def test_the_store_is_asked_under_the_key_it_was_written_under(self):
        asked: list = []
        comp = {"choices": [{"message": {"role": "assistant", "content": "a briefing"}}]}
        srv._harden_compaction_reply(comp, {"messages": _msgs()}, provider=None,
                                     server=_server_with_gate(asked), rlog=_NullRlog(),
                                     sess_key=CALLER_KEY)
        self.assertTrue(asked, "the store was never consulted")
        self.assertIn(CALLER_KEY, asked)
        self.assertFalse([k for k in asked if k.startswith("task:")],
                         f"re-derived a content-hash key instead of using the caller's: {asked}")

    def test_without_a_key_it_still_falls_back_rather_than_crashing(self):
        # A caller that has no key (a transport that never had headers) must not break compaction.
        asked: list = []
        comp = {"choices": [{"message": {"role": "assistant", "content": "a briefing"}}]}
        out = srv._harden_compaction_reply(comp, {"messages": _msgs()}, provider=None,
                                           server=_server_with_gate(asked), rlog=_NullRlog())
        self.assertTrue(asked)
        self.assertIsNotNone(_briefing(out))


class SilenceIsStillSilenceTests(unittest.TestCase):
    def test_a_clean_gate_appends_nothing(self):
        """Empty when no gate has spoken or the last gate was clean — silence over noise (#3)."""
        sess = SimpleNamespace(gate_plan=None, last_gate_flag="")
        s = _Srv()
        s.loop = SimpleNamespace(_store=SimpleNamespace(get=lambda k: sess))
        comp = {"choices": [{"message": {"role": "assistant", "content": "a briefing"}}]}
        out = srv._harden_compaction_reply(comp, {"messages": _msgs()}, provider=None,
                                           server=s, rlog=_NullRlog(), sess_key=CALLER_KEY)
        self.assertNotIn("LATEST CHECK RESULTS", _briefing(out))

    def test_an_unknown_session_appends_nothing(self):
        asked: list = []
        comp = {"choices": [{"message": {"role": "assistant", "content": "a briefing"}}]}
        out = srv._harden_compaction_reply(comp, {"messages": _msgs()}, provider=None,
                                           server=_server_with_gate(asked), rlog=_NullRlog(),
                                           sess_key="sid:not-this-one")
        self.assertNotIn("LATEST CHECK RESULTS", _briefing(out))


if __name__ == "__main__":
    unittest.main()
