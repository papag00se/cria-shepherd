"""cria restarted mid-session and wrote 274 call captures over the top of earlier ones.

`session_dirname` is deliberately restart-stable — its docstring says so: *"deterministic —
identical for every call of a session and across restarts, with no stored state."* The sequence
counter inside that folder was memory-only, so a restart reset it to 0 and the session's next call
wrote `0001-*` over the first call's capture, taking its `.prompt.txt` and `.response.json` with it.

cria restarts about 53 times a day — the operator's own restart-after-every-change rule — and 21 of
293 sessions in the 12-day log window span at least one. Counted exactly from `upstream.dump`, which
carries its own path: **25,823 distinct capture paths written, 189 written more than once, 274
captures destroyed** across 22 session folders, one path written eleven times. One folder holds
three interleaved runs of a single session id, with the earlier runs' first calls simply gone:

    (3, '2026-08-20T19:30:14', 'coder-s1')
    (4, '2026-08-20T18:53:40', 'coder-s1')     <- lower timestamp, higher seq
    (4, '2026-08-20T19:33:30', 'compactor')    <- survived only because the label differs

This is the evidence store the project's own doctrine says to diagnose from, and it was being
corrupted with no event and no disclosure.
"""

import tempfile
import unittest
from pathlib import Path

from cria import callcapture


class _Rlog:
    session = "01a02e27-1111-7000-8000-abcdefabcdef"
    _turn = 1
    phase = ""

    def emit(self, *a, **kw):
        pass


def _capture(d, n, phase="coder-s1"):
    for _ in range(n):
        callcapture.capture({"model": "m", "messages": []}, _Rlog(), calls_dir=d, phase=phase)


def _names(d):
    return sorted(f.name for f in next(Path(d).iterdir()).iterdir())


class ARestartContinuesTheSequenceTests(unittest.TestCase):
    def setUp(self):
        callcapture._seq.clear()
        self.addCleanup(callcapture._seq.clear)

    def test_nothing_written_before_the_restart_is_overwritten(self):
        d = tempfile.mkdtemp()
        _capture(d, 3)
        before = _names(d)
        callcapture._seq.clear()                     # the restart
        _capture(d, 2)
        after = _names(d)
        self.assertEqual(after[:3], before)
        self.assertEqual(len(after), 5)

    def test_the_folder_is_the_same_one_across_the_restart(self):
        """If it were not, there would be no collision to fix — and no continuous record either."""
        d = tempfile.mkdtemp()
        _capture(d, 1)
        callcapture._seq.clear()
        _capture(d, 1)
        self.assertEqual(len(list(Path(d).iterdir())), 1)

    def test_a_second_restart_keeps_counting(self):
        d = tempfile.mkdtemp()
        for _ in range(3):
            _capture(d, 2)
            callcapture._seq.clear()
        self.assertEqual(len(_names(d)), 6)

    def test_a_differently_labelled_call_does_not_reset_the_count(self):
        """The counter is per SESSION, not per phase — labels only masked some of the collisions."""
        d = tempfile.mkdtemp()
        _capture(d, 2, phase="coder-s1")
        callcapture._seq.clear()
        _capture(d, 1, phase="compactor")
        self.assertIn("0003-compactor.json", _names(d))

    def test_a_fresh_session_still_starts_at_one(self):
        d = tempfile.mkdtemp()
        _capture(d, 1)
        self.assertEqual(_names(d), ["0001-coder-s1.json"])


if __name__ == "__main__":
    unittest.main()
