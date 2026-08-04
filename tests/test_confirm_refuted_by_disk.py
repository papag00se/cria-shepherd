"""A confirm veto claiming a file is "missing" is checked against the disk, then RULED — not
pattern-matched.

Walked on ada-handles_nemotron-elastic_codex_pon_1785834747 call 0054: the checker vetoed with
"Missing swagger.json file at <path>" while that exact path existed, without one inspection call.
The first fix decided what "missing" referred to with a regex and a substring rule — audited the
same day: it overturned vetoes about content missing INSIDE existing files, absent functions, and
a genuinely-missing X.py "covered" by test_X.py, with one live misfire. Operator ruling
(2026-08-04): deterministic code GATHERS (stat per named path), one targeted reasoner call JUDGES
(STANDS or REFUTED). Every failure direction keeps the veto.
"""

import json
import os
import tempfile
import unittest

from cria.config import Role
from cria.loop import _confirm_completion, _veto_refuted_by_disk


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, kind, **kw):
        self.events.append((kind, kw))

    def kinds(self):
        return [k for k, _ in self.events]


class _Ask:
    """Scripted one-word ruler; records the prompts it was shown."""

    def __init__(self, answer):
        self.answer = answer
        self.prompts = []

    def __call__(self, system):
        self.prompts.append(system)
        return self.answer


class VetoRefutedByDiskTests(unittest.TestCase):
    def _ws(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        os.makedirs(os.path.join(d.name, "tmp", "read-only"))
        spec = os.path.join(d.name, "tmp", "read-only", "api.handle.me_swagger.json")
        open(spec, "w").write("{}")
        return d.name, spec

    def test_refuted_ruling_overturns(self):
        ws, spec = self._ws()
        ask = _Ask("REFUTED")
        self.assertEqual(_veto_refuted_by_disk(f"Missing swagger.json file at {spec}", ws, ask=ask), spec)
        self.assertEqual(len(ask.prompts), 1)
        self.assertIn("EXISTS on disk", ask.prompts[0])   # the gathered facts reached the ruler

    def test_stands_ruling_keeps_the_veto(self):
        ws, spec = self._ws()
        ask = _Ask("STANDS")
        self.assertEqual(_veto_refuted_by_disk(f"Missing swagger.json file at {spec}", ws, ask=ask), "")

    def test_unreadable_ruling_keeps_the_veto(self):
        ws, spec = self._ws()
        for garbage in ("", "maybe?", "10296752880400"):
            self.assertEqual(
                _veto_refuted_by_disk(f"Missing swagger.json file at {spec}", ws, ask=_Ask(garbage)), "")

    def test_no_existing_named_file_asks_nothing(self):
        # The disk holds no disproof → no call is spent and the veto stands unquestioned.
        ws, _ = self._ws()
        ask = _Ask("REFUTED")
        self.assertEqual(_veto_refuted_by_disk("README.md does not exist on disk", ws, ask=ask), "")
        self.assertEqual(ask.prompts, [])

    def test_no_missing_assertion_asks_nothing(self):
        ws, spec = self._ws()
        ask = _Ask("REFUTED")
        self.assertEqual(_veto_refuted_by_disk(f"{spec} asserts the wrong holder value", ws, ask=ask), "")
        self.assertEqual(ask.prompts, [])

    def test_no_reasoner_keeps_the_veto(self):
        ws, spec = self._ws()
        self.assertEqual(_veto_refuted_by_disk(f"Missing swagger.json file at {spec}", ws, ask=None), "")

    def test_facts_carry_both_states(self):
        # The ruler sees exactly what the disk holds — the existing file AND the absent one.
        ws, spec = self._ws()
        ask = _Ask("STANDS")
        _veto_refuted_by_disk(f"handles.py is missing; the workspace only contains {spec}", ws, ask=ask)
        self.assertIn("handles.py: NOT on disk", ask.prompts[0])
        self.assertIn("EXISTS on disk", ask.prompts[0])


class ConfirmCompletionRefutationTests(unittest.TestCase):
    def test_refuted_veto_confirms_and_is_loud(self):
        with tempfile.TemporaryDirectory() as ws:
            os.makedirs(os.path.join(ws, "tmp", "read-only"))
            spec = os.path.join(ws, "tmp", "read-only", "api.handle.me_swagger.json")
            open(spec, "w").write("{}")
            open(os.path.join(ws, "resolve_handle.py"), "w").write("x\n")
            calls = {"n": 0}

            def chat(body, rlog):
                calls["n"] += 1
                if calls["n"] == 1:   # the confirm checker's veto
                    return json.dumps({"choices": [{"message": {"content": json.dumps(
                        {"consistent": False, "why": f"Missing swagger.json file at {spec}"})}}]}).encode()
                return json.dumps({"choices": [{"message": {"content": "REFUTED"}}]}).encode()
            rlog = _Rlog()
            ok, _ = _confirm_completion(
                "Write resolve_handle.py using the fetched swagger spec", "written and green",
                ws, chat, Role(name="reasoner", backend="local"), rlog, phase="critic-confirm")
            self.assertTrue(ok)
            self.assertIn("loop.confirm_refuted_by_disk", rlog.kinds())

    def test_stands_ruling_leaves_the_veto_standing(self):
        with tempfile.TemporaryDirectory() as ws:
            open(os.path.join(ws, "resolve_handle.py"), "w").write("x\n")
            calls = {"n": 0}

            def chat(body, rlog):
                calls["n"] += 1
                if calls["n"] == 1:
                    return json.dumps({"choices": [{"message": {"content": json.dumps(
                        {"consistent": False,
                         "why": "resolve_handle.py exists but is missing the resolve function"})}}]}).encode()
                return json.dumps({"choices": [{"message": {"content": "STANDS"}}]}).encode()
            rlog = _Rlog()
            ok, _ = _confirm_completion(
                "Write resolve_handle.py with a resolve() function", "written",
                ws, chat, Role(name="reasoner", backend="local"), rlog, phase="critic-confirm")
            self.assertFalse(ok)
            self.assertNotIn("loop.confirm_refuted_by_disk", rlog.kinds())


if __name__ == "__main__":
    unittest.main()
