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


class SpentOnPrintNotOnBuildTests(unittest.TestCase):
    """THE bug, twice over. The first two attempts set the once-per-process flag inside the BUILDER,
    which `_route` called on every routed turn — while five separate renderers can each decline to
    print what the builder returned:

      * a tool-call-only turn: `wrap_stream` holds its pending lines until the first content delta,
        which never comes;
      * `inject_buffered` returns the body untouched when content is empty;
      * an upstream error 502s the turn;
      * a keyed cloud provider has no /props, so there are no lines;
      * the Responses adapter — the API Codex actually speaks — renders only a route STRING and
        throws the lines away.

    Any one of those spent the process's only chance and the operator saw nothing, ever. Measured on
    the day's own log: 359 of 372 requests were Responses turns, and not one carried a banner.

    The fix is structural, not another patched path: ONE emitter (`_finalize`, which every surface
    returning a completion goes through), and the flag is spent at the moment the lines are
    prepended."""

    def test_the_flag_is_not_spent_by_building(self):
        import inspect
        from cria import server
        h = next(v for v in vars(server).values()
                 if isinstance(v, type) and hasattr(v, "_take_connect_lines"))
        src = inspect.getsource(h._take_connect_lines)
        # the flag is set AFTER the lines are known non-empty, on the way out
        self.assertLess(src.index("if not lines:"), src.index("_connect_done = True"))

    def test_there_is_exactly_one_emitter(self):
        import inspect
        from cria import server
        src = inspect.getsource(server)
        self.assertEqual(src.count("_take_connect_lines(rlog)"), 1,
                         "a second emitter is what caused this bug twice")

    def test_the_indicator_no_longer_carries_it(self):
        """Dead wiring misleads the next reader; the Indicator path is gone, not just unused."""
        import dataclasses
        from cria.indicators import Indicator
        self.assertNotIn("connect", {f.name for f in dataclasses.fields(Indicator)})

    def test_it_asks_the_CODERs_endpoint_not_the_shared_default(self):
        """A role may carry its own base_url, so the shared upstream can be a different server than
        the one doing the work (#5b)."""
        import inspect
        from cria import server
        h = next(v for v in vars(server).values()
                 if isinstance(v, type) and hasattr(v, "_coder_endpoint"))
        self.assertIn('endpoint_for("coder")', inspect.getsource(h._coder_endpoint))

    def test_no_loaded_model_means_no_banner_rather_than_a_config_label(self):
        import types as _t
        from cria import server
        h = next(v for v in vars(server).values()
                 if isinstance(v, type) and hasattr(v, "_take_connect_lines"))
        up = _t.SimpleNamespace(props=lambda r: {"chat_template": "tool_calls"},
                                loaded_model=lambda r: None)
        fake = _t.SimpleNamespace(server=_t.SimpleNamespace(
            _connect_done=False, router=None, upstream=up,
            cfg=_t.SimpleNamespace(routing=_t.SimpleNamespace(roles={}))))
        fake._coder_endpoint = lambda: h._coder_endpoint(fake)
        rlog = _t.SimpleNamespace(emit=lambda *a, **k: None)
        self.assertEqual(h._take_connect_lines(fake, rlog), [])
        self.assertFalse(fake.server._connect_done, "a silent turn must not spend the one shot")

    def test_a_real_banner_spends_the_shot_exactly_once(self):
        import types as _t
        from cria import server
        h = next(v for v in vars(server).values()
                 if isinstance(v, type) and hasattr(v, "_take_connect_lines"))
        up = _t.SimpleNamespace(
            props=lambda r: {"chat_template": TOOLS_BRANCH, "chat_template_caps": CAPS_GOOD},
            loaded_model=lambda r: "qwen35_9b_q6")
        fake = _t.SimpleNamespace(server=_t.SimpleNamespace(
            _connect_done=False, router=None, upstream=up,
            cfg=_t.SimpleNamespace(routing=_t.SimpleNamespace(roles={}))))
        fake._coder_endpoint = lambda: h._coder_endpoint(fake)
        rlog = _t.SimpleNamespace(emit=lambda *a, **k: None)
        first = h._take_connect_lines(fake, rlog)
        self.assertTrue(first and "qwen35_9b_q6" in first[0])
        self.assertEqual(h._take_connect_lines(fake, rlog), [], "printed twice")


class TruthfulnessRepairsTests(unittest.TestCase):
    def test_a_server_answering_only_supports_tool_calls_is_not_called_broken(self):
        """The guard accepted either capability key while the formula demanded `supports_tools`, so
        such a build printed a red 'no tool-call branch' over a template that plainly has one."""
        out = compat.probe(props(TOOLS_BRANCH, {"supports_tool_calls": True}))
        self.assertEqual([g for g, l, _ in out if l == "tools"], [compat.OK])

    def test_the_mirror_case_also_passes(self):
        out = compat.probe(props(TOOLS_BRANCH, {"supports_tools": True}))
        self.assertEqual([g for g, l, _ in out if l == "tools"], [compat.OK])

    def test_an_explicit_denial_is_still_believed(self):
        out = compat.probe(props(TOOLS_BRANCH, {"supports_tools": False}))
        self.assertEqual([g for g, l, _ in out if l == "tools"], [compat.BROKEN])

    def test_turn_order_is_not_claimed_green_without_a_template(self):
        """caps but no chat_template → a green asserted from absence of evidence."""
        labels = [l for _, l, _ in compat.probe(props("", CAPS_GOOD))]
        self.assertNotIn("turn order", labels)
        self.assertIn("turn order", [l for _, l, _ in compat.probe(props(TOOLS_BRANCH, CAPS_GOOD))])



class ATransientMissMustNotKillTheBannerTests(unittest.TestCase):
    """`suite/run.py` starts the llama service and restarts cria immediately after, so the first
    turns land while the model is still LOADING and both /props and /v1/models refuse the
    connection. Caching that failure permanently — which the first cut did — killed the banner for
    the whole run, silently. This file's own `_PROPS_RETRY_EVERY` comment already names the
    scenario: "as ordinary as cria restarting while llama.cpp is still loading its model."
    Observed live on the mellum2 swap."""

    def _up(self, answers):
        """An Upstream whose urlopen fails until `answers` says otherwise."""
        from unittest import mock
        from cria.upstream import Upstream
        import io, urllib.error
        up = Upstream("http://x")
        state = {"i": 0}

        def fake(req, timeout=None):
            i = state["i"]; state["i"] += 1
            if not answers[min(i, len(answers) - 1)]:
                raise urllib.error.URLError("connection refused")
            return io.BytesIO(b'{"chat_template":"tool_calls","chat_template_caps":{}}')
        fake.__enter__ = None
        return up, mock.patch("cria.upstream.urllib.request.urlopen",
                              side_effect=lambda r, timeout=None: _CM(fake(r, timeout)))

    def test_props_retries_after_a_refused_connection(self):
        import types as _t
        up, patcher = self._up([False, True])
        rlog = _t.SimpleNamespace(emit=lambda *a, **k: None)
        with patcher:
            self.assertIsNone(up.props(rlog))          # server still loading
            self.assertIsNotNone(up.props(rlog))       # …and it comes back

    def test_a_successful_props_is_never_re_probed(self):
        import types as _t
        up, patcher = self._up([True])
        rlog = _t.SimpleNamespace(emit=lambda *a, **k: None)
        with patcher:
            first = up.props(rlog)
            self.assertIs(up.props(rlog), first)

    def test_a_cloud_endpoint_is_still_never_probed(self):
        import types as _t
        from unittest import mock
        from cria.upstream import Upstream
        up = Upstream("http://x", api_key="sk-test")
        rlog = _t.SimpleNamespace(emit=lambda *a, **k: None)
        with mock.patch("cria.upstream.urllib.request.urlopen",
                        side_effect=AssertionError("must not probe")):
            self.assertIsNone(up.props(rlog))
            self.assertIsNone(up.loaded_model(rlog))


class _CM:
    def __init__(self, f): self._f = f
    def __enter__(self): return self._f
    def __exit__(self, *a): return False


if __name__ == "__main__":
    unittest.main()
