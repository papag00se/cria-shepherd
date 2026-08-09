"""What the steer author SEES, and how much of what it says is just that read back.

Two faults, one call, both measured on mellum2 run 1786302864.

IMITATION. Call 0060 was shown tool-call syntax 50× and the harness's `Chunk ID / Wall time /
Process exited with code / Output:` envelope 24×, then asked in one sentence at the very end for a
directive. It answered with a fabricated `exec_command(...)` followed by an invented Chunk ID, wall
time, exit code and `addr1q…` address — and cria delivered that to the coder as a steer, in cria's
own voice, telling it a resolver worked that had never once returned an address.

Not an anecdote: over 717 reasoner calls in the captures, a prompt demonstrating 0-9 such shapes was
answered by imitating one 1% of the time, 10-29 3%, 30-59 **8%**. cria's own source already records
this for the compaction path — "a weak model continues the pattern and answers with a tool call,
whatever the system prompt says" — where the fix was to FLATTEN the history. This path was already
flat and still failed, because flattening kept the SYNTAX.

PROVENANCE. Call 0134 read the real endpoint response — `tools":[{"name":"get_handle"…}]` — and
correctly told the coder to use `get_handle`. Call 0166 reversed it, citing "the MCP endpoint only
supports search_handles". That was not evidence: it was the CODER's own stuck reasoning, quoted back
into the prompt under a heading cria wrote, while the real response was still in the same prompt 67
times. The reversal began a four-way flip-flop that cost 83 edits and the run.

The second is the worse of the two because it FEEDS BACK — cria's wrong answer becomes the grounds
for cria's next wrong answer. So cria's own prior output is now marked in the transcript, and the
prompt ranks its sections by authority instead of merely naming them.
"""
import re
import unittest

from cria import loop, prompts, selfcompact

TOOL_SHAPES = re.compile(r"\b\w+\(\{|\bexec_command\(|\bedit_file\(|\bwrite_file\(")
OUTPUT_TEMPLATE = re.compile(r"Chunk ID:|Process exited with code|Wall time:|Original token count:")

SESSION = [
    {"role": "user", "content": "Resolve an Ada Handle to a Cardano address."},
    {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
        "name": "exec_command", "arguments": '{"cmd": "python live_test.py", "shell": "bash"}'}}]},
    {"role": "tool", "tool_call_id": "c1", "content":
        "Chunk ID: 368902\nWall time: 0.0000 seconds\nProcess exited with code 127\n"
        "Original token count: 12\nOutput:\n/bin/bash: line 1: python: command not found"},
]


class NothingLeftToCopyTests(unittest.TestCase):
    def test_the_default_rendering_still_demonstrates_the_syntax(self):
        """The measurement's baseline — unchanged for the summarizer, which has its own base rate
        still to be taken (#15)."""
        plain = selfcompact.serialize(SESSION)
        self.assertTrue(TOOL_SHAPES.search(plain))
        self.assertTrue(OUTPUT_TEMPLATE.search(plain))

    def test_defanged_has_no_tool_call_template(self):
        self.assertIsNone(TOOL_SHAPES.search(selfcompact.serialize(SESSION, defang=True)))

    def test_defanged_has_no_output_envelope_template(self):
        self.assertIsNone(OUTPUT_TEMPLATE.search(selfcompact.serialize(SESSION, defang=True)))

    def test_every_fact_survives(self):
        """Defanging removes the SHAPE, never the content — a supervisor still needs all of it."""
        out = selfcompact.serialize(SESSION, defang=True)
        for fact in ("exec_command", "python live_test.py", "127", "python: command not found"):
            with self.subTest(fact=fact):
                self.assertIn(fact, out)

    def test_the_exit_code_is_stated_once_not_twice(self):
        out = selfcompact.serialize(SESSION, defang=True)
        self.assertIn("→ exit 127", out)
        self.assertEqual(out.count("127"), 1, "the code is restated by the envelope line")

    def test_it_is_substantially_smaller(self):
        plain = selfcompact.serialize(SESSION)
        lean = selfcompact.serialize(SESSION, defang=True)
        self.assertLess(len(lean), len(plain))

    def test_a_message_with_neither_text_nor_calls_is_dropped(self):
        self.assertEqual(selfcompact.serialize([{"role": "assistant", "content": ""}], defang=True), "")


class CriasOwnVoiceIsMarkedTests(unittest.TestCase):
    """A previous steer re-entering as evidence is a feedback loop: cria's wrong answer becomes the
    grounds for cria's next wrong answer, more confidently each round."""

    def test_a_prior_steer_is_marked_not_evidence(self):
        out = loop._mark_own_notes("[03] the task/context said: ⟦ctx:steer⟧ use search_handles")
        self.assertIn("EARLIER NOTE FROM THIS SYSTEM", out)
        self.assertIn("not evidence", out)

    def test_a_cria_marker_line_is_marked(self):
        from cria.indicators import SENTINEL
        out = loop._mark_own_notes(f"[04] the coder said: {SENTINEL} steered the coder — flail")
        self.assertIn("EARLIER NOTE FROM THIS SYSTEM", out)

    def test_a_rollup_is_marked(self):
        out = loop._mark_own_notes(f"[05] {selfcompact.SUMMARY_MARKER} earlier turns summarised")
        self.assertIn("EARLIER NOTE FROM THIS SYSTEM", out)

    def test_real_evidence_is_left_alone(self):
        real = "[06] → exit 2: ImportError while importing test module"
        self.assertEqual(loop._mark_own_notes(real), real)

    def test_the_coders_own_words_are_left_alone(self):
        """Marked as unreliable by the PROMPT's ranking, not by this — they are the coder's, not
        cria's, and mislabelling them as cria's output would be its own false fact."""
        line = "[07] the coder said: the endpoint only supports search_handles"
        self.assertEqual(loop._mark_own_notes(line), line)

    def test_empty_is_empty(self):
        self.assertEqual(loop._mark_own_notes(""), "")


class ThePromptRanksItsSourcesTests(unittest.TestCase):
    """Naming a section is not enough — 0166 read a section correctly labelled 'ITS RECENT PRIVATE
    REASONING' and still treated it as fact. The label has to carry a WEIGHT, the way the fetch
    ledger's already does ('trust these over any note or reasoning claiming a fetch failed')."""

    TEXT = prompts.load("steer_diagnose_user")

    def test_it_states_an_order_of_authority(self):
        self.assertIn("NOT equally reliable", self.TEXT)

    def test_the_coders_thinking_is_marked_as_belief(self):
        self.assertIn("what the coder BELIEVES, not what is true", self.TEXT)
        self.assertIn("unverified", self.TEXT)

    def test_its_own_earlier_notes_are_ranked_last_and_barred(self):
        self.assertIn("never evidence", self.TEXT)

    def test_every_placeholder_survives(self):
        for k in ("{{TRIGGER}}", "{{SESSION}}", "{{DISK}}", "{{TRUTH}}", "{{REASONING}}"):
            with self.subTest(k=k):
                self.assertIn(k, self.TEXT)

    def test_the_author_still_gets_its_sentinel_and_its_ask(self):
        self.assertIn("ON_TRACK", self.TEXT)
        self.assertIn("short unstick directive", self.TEXT)


class TheSteerAuthorUsesBothTests(unittest.TestCase):
    def test_the_session_is_defanged_and_marked(self):
        import inspect
        src = inspect.getsource(loop.author_steer)
        self.assertIn("defang=True", src)
        self.assertIn("_mark_own_notes(", src)


if __name__ == "__main__":
    unittest.main()
