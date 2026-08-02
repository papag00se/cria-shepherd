"""An ALTERNATION between two finding-sets defeats every "same as last time" check cria has."""
import unittest

from cria import loop, prompts


class WindowTests(unittest.TestCase):
    def test_the_window_is_long_enough_for_an_A_B_A_cycle(self):
        self.assertGreaterEqual(loop.GATE_SIGNATURE_WINDOW, 3)


class DetectionTests(unittest.TestCase):
    """Reproduces the walked case: 'fixture self not found' and 'undefined name self' traded places
    while every individual fix was correct for the error it was shown."""

    A = "test.py:1: fixture 'self' not found"
    B = "test.py:5: undefined name 'self'"

    def feed(self, seq):
        """Mirror the detector's arithmetic over a sequence of gate signatures."""
        prior, fired = [], []
        for sig in seq:
            if sig in prior and prior[-1] != sig:
                fired.append(sig)
            if not prior or prior[-1] != sig:
                prior.append(sig)
                del prior[:-loop.GATE_SIGNATURE_WINDOW]
        return fired

    def test_A_B_A_fires(self):
        self.assertTrue(self.feed([self.A, self.B, self.A]))

    def test_the_same_finding_twice_running_does_NOT_fire(self):
        # That is `gate_stalled`'s job, and it already exists — this must not double-report it.
        self.assertFalse(self.feed([self.A, self.A, self.A]))

    def test_steady_progress_never_fires(self):
        self.assertFalse(self.feed(["e1", "e2", "e3", "e4", "e5"]))

    def test_a_long_cycle_still_fires(self):
        self.assertTrue(self.feed([self.A, self.B, "c", self.A]))

    def test_it_keeps_firing_while_the_cycle_continues(self):
        self.assertGreaterEqual(len(self.feed([self.A, self.B, self.A, self.B, self.A])), 2)


class NotePropertyTests(unittest.TestCase):
    def test_the_note_names_the_real_mechanism(self):
        t = prompts.load("gate_oscillating")
        self.assertIn("each other's cause", t)
        self.assertIn("smaller change", t)

    def test_it_does_NOT_dictate_code_or_a_filename(self):
        t = prompts.load("gate_oscillating")
        for banned in ("```", "def ", "import ", ".py"):
            self.assertNotIn(banned, t)

    def test_marker_namespace_and_never_the_proper_noun(self):
        t = prompts.load("gate_oscillating")
        self.assertIn("⟦ctx:", t)
        self.assertNotIn("cria", t.lower())


class RideAlongTests(unittest.TestCase):
    def test_the_note_never_replaces_the_checker_findings(self):
        # It is APPENDED to the reason, so the checker's own words stay first and whole.
        import inspect
        src = inspect.getsource(loop.Loop._renudge)
        self.assertIn('reason = reason + "\\n\\n" + sess.oscillation_note', src)
        self.assertIn('sess.oscillation_note = ""', src)   # consumed → fires once, not forever
