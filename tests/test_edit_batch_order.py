"""A batch of edits applies in the coder's CALL order, however the harness schedules the processes.

Real batch: phi4 / Java attempt A11 call 0024 — eleven edits to Importer.java in one turn, run concurrently by
the harness. Later edits are anchored on text earlier ones produce; applied in arrival order the file ended
up different from the call-order result (9 landed in order, 10 reversed, different bytes)."""
import json
import os
import pathlib
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

from cria import prompts, writeproxy
from cria.writeproxy import translate_outbound

_FX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "a11_call24_batch.json").read_text())
_SHELL = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}


def _lower(edits, path=None, *, sequences=None):
    comp = {"choices": [{"message": {"tool_calls": [
        {"id": f"c{i}", "type": "function", "function": {"name": "edit_file", "arguments": json.dumps(
            {"path": path or _FX["path"], **e})}} for i, e in enumerate(edits)]}}]}
    original = writeproxy._edit_sequence
    def observed(*args):
        result = original(*args)
        if sequences is not None:
            sequences.update(result)
        return result
    with mock.patch.object(writeproxy, '_edit_sequence', side_effect=observed):
        translate_outbound(comp, _SHELL, injected={"edit_file"})
    return [json.loads(tc["function"]["arguments"])["cmd"] for tc in comp["choices"][0]["message"]["tool_calls"]]


def _workspace(base):
    d = tempfile.mkdtemp()
    f = pathlib.Path(d, _FX["path"])
    f.parent.mkdir(parents=True)
    f.write_text(base)
    return d, f


def _run(cmd, d, tmp):
    return subprocess.run(["bash", "-c", cmd], cwd=d, capture_output=True, text=True,
                          env={**os.environ, "TMPDIR": tmp})


class BatchOrderTests(unittest.TestCase):
    def test_a_reversed_concurrent_batch_equals_the_call_order_result(self):
        cmds = _lower(_FX["edits"])
        d, f = _workspace(_FX["base"])
        tmp = tempfile.mkdtemp()
        for c in cmds:                                   # the reference: one at a time, in call order
            _run(c, d, tmp)
        expected = f.read_text()
        d2, f2 = _workspace(_FX["base"])
        tmp2 = tempfile.mkdtemp()
        outs = {}

        def one(i):
            outs[i] = _run(cmds[i], d2, tmp2)

        ts = []
        for i in reversed(range(len(cmds))):             # the LAST call starts first
            t = threading.Thread(target=one, args=(i,))
            t.start()
            ts.append(t)
            time.sleep(0.05)
        [t.join() for t in ts]
        self.assertEqual(f2.read_text(), expected)
        self.assertTrue(all(writeproxy.EDIT_ORDER_LATE not in o.stdout + o.stderr for o in outs.values()))
        self.assertEqual([p.name for p in pathlib.Path(d2).iterdir()], ["src"])        # nothing in the tree
        self.assertEqual(os.listdir(tmp2), [])             # and the queue's marks are gone once the batch is done

    def test_a_resent_identical_batch_gets_its_own_queue(self):
        edits = [{"old_string": "a", "new_string": "b"}, {"old_string": "b", "new_string": "c"}]
        first_facts, second_facts = {}, {}
        with mock.patch.object(writeproxy, 'EDIT_SEQ_WAIT_SECONDS', .2):
            first = _lower(edits, path='f.txt', sequences=first_facts)
            second = _lower(edits, path='f.txt', sequences=second_facts)
        self.assertNotEqual(first_facts[1][0], second_facts[1][0])
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as scratch:
            path = pathlib.Path(directory, 'f.txt')
            path.write_text('a')
            self.assertIn(writeproxy._WROTE, _run(first[0], directory, scratch).stdout)
            # A previous batch's completed predecessor must not satisfy a retry's queue.
            result = _run(second[1], directory, scratch)
            self.assertEqual(path.read_text(), 'c')
            self.assertIn(writeproxy.EDIT_ORDER_LATE, result.stdout + result.stderr)

    def test_the_wait_is_shorter_than_the_yield_the_call_gets(self):
        """The lowered call is not given a time budget; a harness yields a running command at ~10 s, so a
        queued edit that outwaited that would be reported 'still running' and apply behind the model's back."""
        from cria import probegate
        self.assertLess(writeproxy.EDIT_SEQ_WAIT_SECONDS, probegate.GATE_POLL_WAIT_S)
        self.assertLessEqual(writeproxy.EDIT_SEQ_WAIT_SECONDS, 7)

    def test_without_the_queue_the_same_reversed_batch_differs(self):
        """The fixture really is order-sensitive (guards the test above against going vacuous)."""
        plain = [writeproxy._edit_command(_FX["path"], e["old_string"], e["new_string"]) for e in _FX["edits"]]
        outs = []
        for order in (plain, plain[::-1]):
            d, f = _workspace(_FX["base"])
            for c in order:
                _run(c, d, tempfile.mkdtemp())
            outs.append(f.read_text())
        self.assertNotEqual(*outs)

    def test_a_predecessor_that_never_arrives_is_not_waited_for_and_the_result_says_so(self):
        old = writeproxy.EDIT_SEQ_WAIT_SECONDS
        writeproxy.EDIT_SEQ_WAIT_SECONDS = 0.4
        try:
            cmds = _lower([{"old_string": "line 1", "new_string": "one"}, {"old_string": "line 2", "new_string": "two"}],
                          path="f.txt")
        finally:
            writeproxy.EDIT_SEQ_WAIT_SECONDS = old
        d = tempfile.mkdtemp()
        pathlib.Path(d, "f.txt").write_text("line 1\nline 2\n")
        t0 = time.time()
        r = _run(cmds[1], d, tempfile.mkdtemp())          # call 0 never runs
        self.assertLess(time.time() - t0, 10)
        self.assertEqual(pathlib.Path(d, "f.txt").read_text(), "line 1\ntwo\n")
        rendered = writeproxy.render_edit_echo(r.stdout, "f.txt")
        self.assertIn(prompts.load("edit_order_late").strip(), rendered)
        self.assertNotIn(writeproxy.EDIT_ORDER_LATE, rendered)

    def test_a_late_refusal_is_also_said_in_words(self):
        old = writeproxy.EDIT_SEQ_WAIT_SECONDS
        writeproxy.EDIT_SEQ_WAIT_SECONDS = 0.3
        try:
            cmds = _lower([{"old_string": "line 1", "new_string": "one"}, {"old_string": "nope", "new_string": "x"}],
                          path="f.txt")
        finally:
            writeproxy.EDIT_SEQ_WAIT_SECONDS = old
        d = tempfile.mkdtemp()
        pathlib.Path(d, "f.txt").write_text("line 1\n")
        r = _run(cmds[1], d, tempfile.mkdtemp())
        from cria import editrecovery
        text = editrecovery.recover(r.stdout + r.stderr, [])
        self.assertIn(prompts.load("edit_order_late").strip(), text)
        self.assertNotIn(editrecovery.ORDER_LATE, text)

    def test_a_refused_predecessor_releases_the_queue(self):
        cmds = _lower([{"old_string": "line 1", "new_string": None}, {"old_string": "line 2", "new_string": "two"}],
                      path="f.txt")
        tmp = tempfile.mkdtemp()
        d = tempfile.mkdtemp()
        pathlib.Path(d, "f.txt").write_text("line 1\nline 2\n")
        # Run the actual refused producer, not a regex reconstruction of its release leg.
        refused = _run(cmds[0], d, tmp)
        self.assertNotIn(writeproxy._WROTE, refused.stdout)
        t0 = time.time()
        r = _run(cmds[1], d, tmp)
        self.assertLess(time.time() - t0, 5)
        self.assertNotIn(writeproxy.EDIT_ORDER_LATE, r.stdout)
        self.assertEqual(pathlib.Path(d, 'f.txt').read_text(), 'line 1\ntwo\n')
        self.assertEqual(os.listdir(tmp), [])

    def test_a_last_refusal_does_not_retire_a_live_predecessors_group(self):
        cmds = _lower([{'old_string': 'a', 'new_string': 'b'}, {'old_string': 'b', 'new_string': None}], path='f.txt')
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as scratch:
            path = pathlib.Path(directory, 'f.txt')
            path.write_text('a')
            _run(cmds[1], directory, scratch)  # last call refused before the first even starts
            self.assertTrue(os.listdir(scratch))
            result = _run(cmds[0], directory, scratch)
            self.assertEqual(path.read_text(), 'b')
            self.assertIn(writeproxy._WROTE, result.stdout)
            self.assertEqual(os.listdir(scratch), [])

    def test_one_edit_per_file_carries_no_queue(self):
        cmds = _lower([{"old_string": "a", "new_string": "b"}], path="f.txt")
        self.assertNotIn(writeproxy.EDIT_SEQ_DIR, cmds[0])
        two = _lower([{"old_string": "a", "new_string": "b"}], path="g.txt")
        # A workspace survey may independently add another Python program.
        # Queue absence is the sequencing invariant, not total program count.
        self.assertNotIn(writeproxy.EDIT_SEQ_DIR, two[0])


if __name__ == "__main__":
    unittest.main()
