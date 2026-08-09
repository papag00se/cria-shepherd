"""The connect banner — cria says up front whether it can drive the model behind the endpoint.

Two models proved the need by failing in ways their own chat templates announced before the first
token: nemotron-nano (strict user/assistant alternation — cria's anchors are consecutive user turns,
so the FIRST coder call 400'd, and the run died in 24 seconds) and r1-llama (no tools branch at all
— 30 calls, ZERO assistant turns). Both facts sit in `/props`, which cria was already fetching for
the context window and reading exactly one field of.

IT REPORTS, IT NEVER GATES (#19: a model that breaks the harness is a resilience requirement).
Every check here changes one line of text and nothing else.

WHICH CHECKS EXIST IS A MEASURED DECISION (#15). Four were screened against every ladder model's
real GGUF template. Two discriminate and shipped; two fired on models that score 4/4 and were
deleted — see the tests below, which pin the deletions so they are not re-added on a hunch.
"""
import unittest

from cria import compat

# The two checks that shipped, as real template fragments.
ALTERNATION = ("{%- if (message['role'] in ['user','tool']) != (loop.index0 % 2 == 0) -%}"
               "{{- raise_exception('Conversation roles must alternate between user/tool and assistant') -}}")
TOOLS_BRANCH = "{%- if message.get('tool_calls') is not none -%}<TOOLCALL>[{%- endfor -%}"

CAPS_GOOD = {"supports_tools": True, "supports_tool_calls": True, "supports_system_role": True}


def props(template="", caps=None, n_ctx=None):
    p = {"chat_template": template}
    if caps is not None:
        p["chat_template_caps"] = caps
    if n_ctx:
        p["default_generation_settings"] = {"n_ctx": n_ctx}
    return p


class AWorkingModelIsQuietTests(unittest.TestCase):
    """gemma4 scores 4/4/4/4. Its banner must be two lines of green — anything else is noise on a
    model that works, which is the failure mode this whole file exists to avoid."""

    def test_two_lines_all_green(self):
        lines = compat.banner(props(TOOLS_BRANCH, CAPS_GOOD, 49152), model="gemma4")
        self.assertEqual(len(lines), 2)
        self.assertIn("cria connected · gemma4 · 49,152 ctx", lines[0])
        self.assertNotIn(compat.BROKEN, lines[1])
        self.assertNotIn(compat.HANDLED, lines[1])

    def test_no_detail_lines_when_everything_passes(self):
        for line in compat.banner(props(TOOLS_BRANCH, CAPS_GOOD), model="m"):
            self.assertNotIn("—", line.replace("·", ""))


class TheTwoRealIncompatibilitiesTests(unittest.TestCase):
    def test_strict_alternation_is_flagged(self):
        """nemotron-nano, run 1786243834: this is the line that would have replaced two dead runs."""
        lines = compat.banner(props(ALTERNATION + TOOLS_BRANCH, CAPS_GOOD), model="nemotron-nano")
        self.assertIn(compat.BROKEN, " ".join(lines))
        self.assertIn("strict alternation", " ".join(lines))
        self.assertIn("merge_consecutive_turns", " ".join(lines))

    def test_the_same_model_reads_HANDLED_once_cria_is_merging(self):
        lines = compat.banner(props(ALTERNATION + TOOLS_BRANCH, CAPS_GOOD),
                              model="nemotron-nano", merge_turns=True)
        joined = " ".join(lines)
        self.assertIn(compat.HANDLED, joined)
        self.assertNotIn(compat.BROKEN, joined)
        self.assertIn("merging consecutive turns", joined)

    def test_a_template_with_no_tool_branch_is_flagged(self):
        """r1-llama: 0/4, 30 calls, zero assistant turns — readable before the first one."""
        lines = compat.banner(props("{% for m in messages %}{{m.content}}{% endfor %}"), model="r1")
        self.assertIn(compat.BROKEN, " ".join(lines))
        self.assertIn("no tool-call branch", " ".join(lines))

    def test_the_capability_flag_wins_over_the_template_scan(self):
        """The server's own answer is authoritative; the scan is the fallback for older builds."""
        lines = compat.banner(props(TOOLS_BRANCH, {**CAPS_GOOD, "supports_tools": False}), model="m")
        self.assertIn("no tool-call branch", " ".join(lines))


class DeletedChecksStayDeletedTests(unittest.TestCase):
    """Both of these were built, measured against real ladder templates, and removed. They are
    pinned because each looks obviously correct on paper and fires on a model that scores 4/4.

    * gemma4 and qwopus both render an unclosed tag for an EMPTY tool_calls list — and cria has
      never sent that shape (0 of 330,415 captured assistant turns), so the hazard cannot fire.
    * qwopus double-encodes `arguments` passed as a JSON string — and cria sends strings every time
      (20,325 of 20,325 sampled), yet qwopus scores 4/4, so llama.cpp is normalising them first.
      Warning about it would state something the evidence contradicts (#5b)."""

    GEMMA_SHAPED = TOOLS_BRANCH + "{%- if loop.last -%}]</TOOLCALL>{%- endif -%}"
    QWOPUS_SHAPED = TOOLS_BRANCH + '{{ tool_call.function.arguments | tojson }}'

    def test_the_empty_tool_calls_shape_is_not_flagged(self):
        joined = " ".join(compat.banner(props(self.GEMMA_SHAPED, CAPS_GOOD), model="gemma4"))
        self.assertNotIn(compat.BROKEN, joined)
        self.assertNotIn("unclosed", joined)

    def test_the_arguments_encoding_shape_is_not_flagged(self):
        joined = " ".join(compat.banner(props(self.QWOPUS_SHAPED, CAPS_GOOD), model="qwopus"))
        self.assertNotIn(compat.BROKEN, joined)
        self.assertNotIn("double-encod", joined)


class SilenceWhenItWouldBeGuessingTests(unittest.TestCase):
    def test_no_props_says_nothing(self):
        for p in (None, {}, "not a dict", {"unrelated": 1}):
            self.assertEqual(compat.banner(p, model="m"), [], repr(p))

    def test_probe_returns_empty_rather_than_inventing_checks(self):
        self.assertEqual(compat.probe(None), [])
        self.assertEqual(compat.probe({}), [])

    def test_system_role_is_only_reported_when_the_server_answers_it(self):
        """No flag → no line. cria does not infer a system slot from template text."""
        labels = [l for _, l, _ in compat.probe(props(TOOLS_BRANCH))]
        self.assertNotIn("system role", labels)
        labels = [l for _, l, _ in compat.probe(props(TOOLS_BRANCH, CAPS_GOOD))]
        self.assertIn("system role", labels)


class ItRidesTheMarkerRailTests(unittest.TestCase):
    """The banner must be human-only: rendered by the harness, stripped before the model re-reads
    the turn. That is the contract every ⟦cria⟧ line already has, and the banner must not be the
    one that leaks task-irrelevant text into the model's context."""

    def test_the_lines_carry_no_marker_of_their_own(self):
        """indicators owns the rail — a line that pre-marked itself would double-prefix."""
        from cria.indicators import SENTINEL
        for line in compat.banner(props(TOOLS_BRANCH, CAPS_GOOD), model="m"):
            self.assertNotIn(SENTINEL, line)

    def test_a_marked_banner_is_stripped_from_history(self):
        from cria import indicators
        lines = compat.banner(props(ALTERNATION + TOOLS_BRANCH, CAPS_GOOD), model="nemotron-nano")
        decorated = "\n".join(indicators.MARKER + l for l in lines) + "\n\nThe real answer.\n"
        out, n = indicators.strip_history([{"role": "assistant", "content": decorated}])
        self.assertEqual(n, len(lines))
        self.assertEqual(out[0]["content"].strip(), "The real answer.")
        self.assertNotIn("cria connected", out[0]["content"])


class TheIndicatorCarriesItTests(unittest.TestCase):
    def test_the_field_exists_and_defaults_to_nothing(self):
        from cria.indicators import Indicator
        self.assertIsNone(Indicator(True, True, "m").connect)

    def test_both_render_paths_emit_it(self):
        import inspect
        from cria import indicators
        self.assertIn("indic.connect", inspect.getsource(indicators.wrap_stream))
        self.assertIn("indic.connect", inspect.getsource(indicators.inject_buffered))

    def test_the_operator_can_turn_it_off(self):
        from cria.config import IndicatorsConfig
        self.assertTrue(IndicatorsConfig().connect)
        self.assertFalse(IndicatorsConfig(connect=False).connect)


if __name__ == "__main__":
    unittest.main()
