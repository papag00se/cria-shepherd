"""A confirm veto that calls an on-disk file "missing" is refuted by the disk, not delivered.

Walked on ada-handles_nemotron-elastic_codex_pon_1785834747 call 0054: the confirm checker ruled
{"consistent": false, "why": "Missing swagger.json file at /tmp/…/tmp/read-only/
api.handle.me_swagger.json"} — without a single inspection call — while that exact path existed
(the coder `ls`'d it one call later and read it the call after). The false veto re-blocked a step
the critic had verified, three times in one run, and the coder received "Missing <file>" in cria's
voice — the false fact rule 5b forbids. Measured: 31 of 152 captured confirm-false verdicts assert
a missing file; the truly-missing ones keep their veto (that is the brake's legitimate win), and
only what the disk disproves is overturned.
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


def _confirm_false(why):
    return {"choices": [{"message": {"content": json.dumps({"consistent": False, "why": why})}}]}


class VetoRefutedByDiskTests(unittest.TestCase):
    def test_absolute_path_that_exists_refutes_the_veto(self):
        with tempfile.TemporaryDirectory() as ws:
            os.makedirs(os.path.join(ws, "tmp", "read-only"))
            spec = os.path.join(ws, "tmp", "read-only", "api.handle.me_swagger.json")
            open(spec, "w").write("{}")
            why = f"Missing swagger.json file at {spec}"
            self.assertEqual(_veto_refuted_by_disk(why, ws), spec)

    def test_relative_name_that_exists_refutes(self):
        with tempfile.TemporaryDirectory() as ws:
            open(os.path.join(ws, "resolve_handle.py"), "w").write("x\n")
            self.assertEqual(
                _veto_refuted_by_disk("resolve_handle.py does not exist in the workspace", ws),
                "resolve_handle.py")

    def test_truly_missing_file_keeps_its_veto(self):
        with tempfile.TemporaryDirectory() as ws:
            self.assertEqual(_veto_refuted_by_disk("README.md does not exist on disk", ws), "")

    def test_mixed_why_with_a_real_absence_keeps_its_veto(self):
        # One named file exists, another is genuinely missing → the veto stands whole.
        with tempfile.TemporaryDirectory() as ws:
            open(os.path.join(ws, "test_x.py"), "w").write("x\n")
            self.assertEqual(
                _veto_refuted_by_disk("test_x.py exists but README.md is missing", ws), "")

    def test_no_missing_assertion_is_not_touched(self):
        with tempfile.TemporaryDirectory() as ws:
            open(os.path.join(ws, "a.py"), "w").write("x\n")
            self.assertEqual(_veto_refuted_by_disk("a.py asserts the wrong holder value", ws), "")


class ConfirmCompletionRefutationTests(unittest.TestCase):
    def _run(self, ws, why):
        calls = [0]

        def chat(body, rlog):
            calls[0] += 1
            return json.dumps(_confirm_false(why)).encode()
        rlog = _Rlog()
        ok, out_why = _confirm_completion(
            "Write resolve_handle.py using the fetched swagger spec", "it is written and green",
            ws, chat, Role(name="reasoner", backend="local"), rlog, phase="critic-confirm")
        return ok, out_why, rlog

    def test_refuted_veto_confirms_and_is_loud(self):
        # FAILS BEFORE THE FIX: the false "missing file" veto stood and blocked the step.
        with tempfile.TemporaryDirectory() as ws:
            os.makedirs(os.path.join(ws, "tmp", "read-only"))
            spec = os.path.join(ws, "tmp", "read-only", "api.handle.me_swagger.json")
            open(spec, "w").write("{}")
            open(os.path.join(ws, "resolve_handle.py"), "w").write("x\n")
            ok, why, rlog = self._run(ws, f"Missing swagger.json file at {spec}")
            self.assertTrue(ok)
            self.assertIn("loop.confirm_refuted_by_disk", rlog.kinds())

    def test_genuine_absence_still_vetoes(self):
        with tempfile.TemporaryDirectory() as ws:
            open(os.path.join(ws, "resolve_handle.py"), "w").write("x\n")
            ok, why, rlog = self._run(ws, "test_resolve_handle.py does not exist in the workspace")
            self.assertFalse(ok)
            self.assertNotIn("loop.confirm_refuted_by_disk", rlog.kinds())


if __name__ == "__main__":
    unittest.main()
