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


class ItReachesTheDRIVEPathTests(unittest.TestCase):
    """The bug this class exists for: the banner shipped wired ONLY into the Indicator that
    `_route` builds — and when cria's loop engages (every suite run, every real coding turn)
    `_produce_stream` returns before `_route` is ever reached. It was verified with a curl, which
    takes the proxy path, so it looked correct and was invisible in production. Same
    one-path-not-its-twin shape as four other faults fixed this week.

    `_finalize` is this file's stated single completion-finalization chokepoint and the drive path
    does go through it, so that is where the banner is emitted; the Indicator keeps the streaming
    proxy covered, and one shared flag stops a double print."""

    def test_finalize_emits_the_banner(self):
        import inspect
        from cria import server
        src = inspect.getsource(server.CriaHandler._finalize) if hasattr(server, "CriaHandler") else ""
        if not src:
            handler = next(v for k, v in vars(server).items()
                           if isinstance(v, type) and hasattr(v, "_finalize"))
            src = inspect.getsource(handler._finalize)
        self.assertIn("_connect_lines", src,
                      "the drive path's chokepoint does not emit the connect banner")

    def test_it_is_gated_on_visible_output(self):
        """A header-only completion is stored and re-summarized by the harness as if it were the
        model's answer — the lesson inject_buffered records in full."""
        import inspect
        from cria import server
        handler = next(v for k, v in vars(server).items()
                       if isinstance(v, type) and hasattr(v, "_finalize"))
        src = inspect.getsource(handler._finalize)
        i = src.index("_connect_lines")
        self.assertIn("_has_visible_output", src[:i],
                      "the banner must not turn an empty turn into a visible one")

    def test_one_shot_flag_is_shared_by_both_paths(self):
        import inspect
        from cria import server
        handler = next(v for k, v in vars(server).items()
                       if isinstance(v, type) and hasattr(v, "_connect_lines"))
        src = inspect.getsource(handler._connect_lines)
        self.assertIn("_connect_done", src)
        self.assertIn("self.server", src, "the flag must live on the SERVER, not the per-request handler")



class TheBannerNamesTheREALModelTests(unittest.TestCase):
    """`_finalize` runs BEFORE `_compute_banner` on the Responses path, so the connect banner is the
    FIRST thing that needs the loaded-model name — and on that turn the private `_loaded_model`
    attribute is still the unset sentinel. Reading it directly printed a config backend label on the
    one banner the process ever emits, which is the "config label that may not match" the neighbouring
    code warns about (#5b). The public accessor fetches and caches instead."""

    def test_it_uses_the_public_accessor_not_the_private_attribute(self):
        import inspect
        from cria import server
        handler = next(v for v in vars(server).values()
                       if isinstance(v, type) and hasattr(v, "_connect_model"))
        src = inspect.getsource(handler._connect_model)
        self.assertIn("loaded_model(rlog)", src)
        self.assertNotIn('getattr(self.server.upstream, "_loaded_model"', src)

    def test_it_falls_back_only_when_the_server_did_not_answer(self):
        import types as _t
        from cria import server
        handler = next(v for v in vars(server).values()
                       if isinstance(v, type) and hasattr(v, "_connect_model"))
        rlog = _t.SimpleNamespace(emit=lambda *a, **k: None)
        role = _t.SimpleNamespace(backend="local")
        fake = _t.SimpleNamespace(server=_t.SimpleNamespace(
            upstream=_t.SimpleNamespace(loaded_model=lambda r: "qwen35_9b_q6"),
            cfg=_t.SimpleNamespace(routing=_t.SimpleNamespace(roles={"coder": role}))))
        self.assertEqual(handler._connect_model(fake, rlog), "qwen35_9b_q6")
        fake.server.upstream.loaded_model = lambda r: None
        self.assertEqual(handler._connect_model(fake, rlog), "local")


if __name__ == "__main__":
    unittest.main()
