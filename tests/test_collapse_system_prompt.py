"""Some templates have nowhere to put a system message. cria always sent one anyway.

cria puts every instruction it writes in a `system` message — the coder frame, every judge, the
steer author, the compactor, the classifier. That is right for most chat templates and wrong for
some, and nothing in cria knew the difference: 12 construction sites across 7 files, no owner.

DeepSeek-R1's distills forced it. Their card says put everything in the user turn, and their
template shows why — it captures the system message and emits it as

    {{bos_token}}{{ns.system_prompt}}{%- for message in messages %}… '<｜User｜>' + content …

BARE, after BOS, before any role marker. The text arrives, but as an unframed preamble outside the
structure the model was trained on — and cria's system prompts run to thousands of characters. Note
also that the template's loop keeps only the LAST system message, so a second one is discarded
silently; the fold joins them instead.

A ROLE knob, not a backend one: cria's backends are ENDPOINTS and the model swaps behind them (one
llama.cpp server on :18084 serves every ladder model in turn), so a backend-level setting would
outlive the model it was set for. suite/sampling.py already writes per-model, per-role values into
cria.toml on every swap, and this rides the same path.
"""
import unittest

from cria.config import Role, _collapse_system_into_user


def _role(**kw):
    return Role(name="coder", backend="local", collapse_system_prompt=True, **kw)


class TheFoldTests(unittest.TestCase):
    def test_the_instruction_still_arrives_first(self):
        body = {"messages": [{"role": "system", "content": "SYS"},
                             {"role": "user", "content": "do the thing"}]}
        _collapse_system_into_user(body)
        self.assertEqual(body["messages"], [{"role": "user", "content": "SYS\n\ndo the thing"}])

    def test_nothing_is_dropped_when_there_are_several(self):
        """The template keeps only the last; the fold keeps all of them, in order."""
        body = {"messages": [{"role": "system", "content": "ONE"},
                             {"role": "system", "content": "TWO"},
                             {"role": "user", "content": "go"}]}
        _collapse_system_into_user(body)
        self.assertEqual(body["messages"][0]["content"], "ONE\n\nTWO\n\ngo")

    def test_a_system_only_body_still_asks_its_question(self):
        """A judge asked with system-only would otherwise lose the whole question."""
        body = {"messages": [{"role": "system", "content": "Answer YES or NO."}]}
        _collapse_system_into_user(body)
        self.assertEqual(body["messages"], [{"role": "user", "content": "Answer YES or NO."}])

    def test_it_folds_into_the_FIRST_user_turn_not_the_last(self):
        body = {"messages": [{"role": "system", "content": "SYS"},
                             {"role": "user", "content": "first"},
                             {"role": "assistant", "content": "ok"},
                             {"role": "user", "content": "second"}]}
        _collapse_system_into_user(body)
        self.assertEqual([m["content"] for m in body["messages"]],
                         ["SYS\n\nfirst", "ok", "second"])

    def test_history_order_is_preserved(self):
        body = {"messages": [{"role": "system", "content": "S"},
                             {"role": "user", "content": "u1"},
                             {"role": "assistant", "content": "a1"},
                             {"role": "tool", "content": "t1"},
                             {"role": "user", "content": "u2"}]}
        _collapse_system_into_user(body)
        self.assertEqual([m["role"] for m in body["messages"]],
                         ["user", "assistant", "tool", "user"])

    def test_a_mid_conversation_system_message_is_left_alone(self):
        """cria injects its anchors as USER turns; a system message after the conversation starts is
        the harness's, not an instruction to relocate."""
        body = {"messages": [{"role": "user", "content": "u"},
                             {"role": "system", "content": "mid"}]}
        before = [dict(m) for m in body["messages"]]
        _collapse_system_into_user(body)
        self.assertEqual(body["messages"], before)

    def test_an_empty_system_message_carries_nothing_to_move(self):
        body = {"messages": [{"role": "system", "content": "   "},
                             {"role": "user", "content": "u"}]}
        _collapse_system_into_user(body)
        self.assertEqual(body["messages"], [{"role": "user", "content": "u"}])

    def test_a_body_with_no_system_message_is_untouched(self):
        body = {"messages": [{"role": "user", "content": "u"}]}
        _collapse_system_into_user(body)
        self.assertEqual(body["messages"], [{"role": "user", "content": "u"}])

    def test_a_malformed_body_does_not_raise(self):
        for b in ({}, {"messages": None}, {"messages": []}):
            _collapse_system_into_user(b)          # must not raise


class TheKnobTests(unittest.TestCase):
    def test_off_by_default(self):
        self.assertFalse(Role(name="coder", backend="local").collapse_system_prompt)

    def test_a_role_without_it_sends_the_system_message_as_before(self):
        body = {"messages": [{"role": "system", "content": "SYS"},
                             {"role": "user", "content": "u"}]}
        Role(name="coder", backend="local").apply(body)
        self.assertEqual(body["messages"][0]["role"], "system")

    def test_a_role_with_it_folds_on_every_request(self):
        body = {"messages": [{"role": "system", "content": "SYS"},
                             {"role": "user", "content": "u"}]}
        _role().apply(body)
        self.assertEqual(body["messages"][0]["role"], "user")
        self.assertIn("SYS", body["messages"][0]["content"])

    def test_it_is_read_from_the_toml(self):
        import tomllib
        from cria import config
        cfg = tomllib.loads(
            '[backends.local]\nkind = "http"\nbase_url = "http://127.0.0.1:18084/v1"\n'
            '[roles.coder]\nbackend = "local"\ncollapse_system_prompt = true\n'
            '[roles.reasoner]\nbackend = "local"\n')
        backends = {n: config._backend(n, b) for n, b in cfg["backends"].items()}
        coder = config._role("coder", cfg["roles"]["coder"], backends)
        other = config._role("reasoner", cfg["roles"]["reasoner"], backends)
        self.assertTrue(coder.collapse_system_prompt)
        self.assertFalse(other.collapse_system_prompt)


class TheSuiteWritesItPerModelTests(unittest.TestCase):
    """NO model sets it today, r1-llama included — and that is the researched position, not an
    oversight. The card says no system prompt; the evidence is split. One of the model's own
    developers measured a system prompt at temp 0.7 as "close to the 'no system prompt'" result and
    another user reports it working fine, against one credible report of the model "hung up
    repeatedly second guessing itself in a loop". cria also never sends a second system message —
    527 of 527 captured bodies — so the multi-message discard is hypothetical here. Turning it on
    for r1-llama's first run would confound the question that model is on the ladder to answer.

    This test exists so enabling it is a DELIBERATE edit with a reason attached, not a default that
    drifted in."""

    def test_nothing_enables_it_yet(self):
        import sys, pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "suite"))
        import sampling
        for model, roles in sampling.MODEL_SAMPLING.items():
            for role, knobs in roles.items():
                self.assertNotIn("collapse_system_prompt", knobs,
                                 f"{model}/{role} enables the fold — record WHY here")

    def test_a_stale_value_from_the_previous_model_is_dropped(self):
        import sys, pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "suite"))
        import sampling
        self.assertIn("collapse_system_prompt", sampling.KNOBS)

    def test_it_would_be_written_as_a_TOML_boolean_not_a_python_one(self):
        """`True` is not valid TOML and cria's loader would fail on the file it was handed. Tested
        against a synthetic model so it holds the day a real one turns the fold on."""
        import sys, pathlib, tempfile, tomllib, shutil
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "suite"))
        import sampling
        src = pathlib.Path.home() / ".cria" / "cria.toml"
        if not src.exists():
            self.skipTest("no cria.toml on this box")
        sampling.MODEL_SAMPLING["_toml_bool_probe"] = {
            r: {"temperature": 0.6, "collapse_system_prompt": True}
            for r in ("coder", "reasoner", "classifier", "compactor")}
        try:
            tmp = pathlib.Path(tempfile.mkdtemp()) / "cria.toml"
            shutil.copy(src, tmp)
            sampling.apply("_toml_bool_probe", tmp)
            self.assertIn("collapse_system_prompt = true", tmp.read_text())
            parsed = tomllib.load(open(tmp, "rb"))       # must round-trip
            self.assertIs(parsed["roles"]["coder"]["collapse_system_prompt"], True)
        finally:
            sampling.MODEL_SAMPLING.pop("_toml_bool_probe", None)


if __name__ == "__main__":
    unittest.main()


class TheThirdReasoningConventionTests(unittest.TestCase):
    """Some models toggle reasoning with a SENTENCE, not a parameter.

    cria knew two conventions, both top-level body keys: `chat_template_kwargs.enable_thinking` and
    an effort field. NVIDIA's Llama-3.1-Nemotron-Nano toggles on the literal system line
    `detailed thinking on` / `off` — the first model on the ladder whose reasoning cannot be driven
    by any parameter at all. The convention is the MODEL's, not the endpoint's: the same llama.cpp
    server on :18084 serves parameter-toggled models the rest of the week, so the role names it.
    """

    def _apply(self, reasoning, msgs):
        from cria.config import Role
        body = {"messages": msgs}
        Role(name="coder", backend="local", think_protocol="system_directive",
             reasoning=reasoning).apply(body)
        return body["messages"]

    FRAME = [{"role": "system", "content": "CODER FRAME"}, {"role": "user", "content": "go"}]

    def test_on_and_off_are_the_cards_exact_words(self):
        from cria import reasoning
        self.assertEqual(reasoning.system_directive("on"), "detailed thinking on")
        self.assertEqual(reasoning.system_directive("off"), "detailed thinking off")

    def test_it_prepends_and_keeps_the_frame(self):
        out = self._apply("on", [dict(m) for m in self.FRAME])
        self.assertEqual(out[0]["content"], "detailed thinking on\n\nCODER FRAME")

    def test_unset_leaves_the_models_own_default_alone(self):
        for r in (None, "auto"):
            out = self._apply(r, [dict(m) for m in self.FRAME])
            self.assertEqual(out[0]["content"], "CODER FRAME")

    def test_a_body_with_no_system_message_gets_one(self):
        out = self._apply("off", [{"role": "user", "content": "go"}])
        self.assertEqual(out[0], {"role": "system", "content": "detailed thinking off"})

    def test_it_does_not_stack_on_repeat(self):
        out = self._apply("on", [{"role": "system", "content": "detailed thinking on\n\nFRAME"},
                                 {"role": "user", "content": "g"}])
        self.assertEqual(out[0]["content"].count("detailed thinking on"), 1)

    def test_no_body_parameter_is_written_for_this_style(self):
        """The switch is text; writing a parameter too would be a second, contradictory signal."""
        from cria import reasoning
        body = {}
        reasoning.apply_reasoning(body, "on", "system_directive")
        self.assertEqual(body, {})

    def test_every_other_model_is_untouched(self):
        from cria.config import Role
        body = {"messages": [dict(m) for m in self.FRAME]}
        Role(name="coder", backend="local", reasoning="on").apply(body)
        self.assertEqual(body["messages"][0]["content"], "CODER FRAME")

    def test_the_suite_writes_the_protocol_and_clears_it_on_swap(self):
        import sys, pathlib, tempfile, tomllib, shutil
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "suite"))
        import sampling
        src = pathlib.Path.home() / ".cria" / "cria.toml"
        if not src.exists():
            self.skipTest("no cria.toml on this box")
        tmp = pathlib.Path(tempfile.mkdtemp()) / "cria.toml"
        shutil.copy(src, tmp)
        sampling.apply("nemotron-nano", tmp)
        self.assertEqual(tomllib.load(open(tmp, "rb"))["roles"]["coder"]["think_protocol"],
                         "system_directive")
        sampling.apply("qwen35", tmp)                       # a model that does not use it
        self.assertNotIn("think_protocol", tomllib.load(open(tmp, "rb"))["roles"]["coder"])

    def test_folding_the_system_prompt_would_delete_the_switch(self):
        """Why nemotron-nano must never set collapse_system_prompt. Pinned so the interaction is
        recorded rather than rediscovered: the fold runs AFTER, so the directive survives into the
        user turn — but on a model whose template reads the SYSTEM slot for it, that is a loss."""
        from cria.config import Role
        body = {"messages": [dict(m) for m in self.FRAME]}
        Role(name="coder", backend="local", think_protocol="system_directive",
             reasoning="on", collapse_system_prompt=True).apply(body)
        self.assertEqual(body["messages"][0]["role"], "user")
        self.assertIn("detailed thinking on", body["messages"][0]["content"])


class StrictRoleAlternationTests(unittest.TestCase):
    """Meta's Llama chat-template lineage enforces alternation literally:

        {%- if (message['role'] in ['user','tool']) != (loop.index0 % 2 == 0) -%}
          {{- raise_exception('Conversation roles must alternate between user/tool and assistant')

    cria's whole anchor mechanism is consecutive user turns, so a Llama-lineage model rejects it
    outright. Measured on Llama-3.1-Nemotron-Nano: the FIRST coder call — system plus three user
    turns — returned 400 twice and the run died in 24 seconds with two calls.

    Nothing on the ladder had hit it because Qwen, Gemma and Nemotron-H templates carry zero
    alternation guards (checked in the GGUFs). Note the two Nemotrons are unrelated: nemotron-elastic
    is NVIDIA's own mamba-hybrid architecture, nemotron-nano is a Llama-3.1 derivative and inherits
    Meta's template convention.

    Every shape below was verified against the LIVE server: 400 before, 200 after.
    """
    from cria.config import Role as _R
    S = {"role": "system", "content": "detailed thinking on\n\nFRAME"}
    U = staticmethod(lambda t: {"role": "user", "content": t})
    A = staticmethod(lambda t: {"role": "assistant", "content": t})
    TC = {"role": "assistant", "content": None,
          "tool_calls": [{"id": "c1", "type": "function",
                          "function": {"name": "read_file", "arguments": '{"p":"a"}'}}]}
    T = {"role": "tool", "tool_call_id": "c1", "content": "file body"}

    def _merged(self, msgs):
        """The real pipeline: the role sets the hint, the WIRE performs the merge.

        It used to happen inside `Role.apply`, and that placement is what let nemotron-nano run
        1786243834 400 six times — focustrim appends a user-side note after the role is applied, so
        the merge had already run. `Upstream._prep` is now the one place it happens, as the last
        message transform; this helper mirrors that pair so the properties below still describe
        what actually reaches the model."""
        from cria import massage
        from cria.config import Role
        body = {"messages": [dict(m) for m in msgs]}
        Role(name="coder", backend="local", merge_consecutive_turns=True).apply(body)
        self.assertTrue(body.get(massage.MERGE_TURNS_KEY), "the role must carry the hint")
        return massage.merge_for_alternation(body["messages"])

    def _alternates(self, msgs):
        rest = msgs[1:] if msgs and msgs[0]["role"] == "system" else msgs
        for i, m in enumerate(rest):
            if (m["role"] in ("user", "tool")) != (i % 2 == 0):
                return False
        return True

    def test_the_body_that_actually_crashed_the_run(self):
        out = self._merged([self.S, self.U("AGENTS"), self.U("task"), self.U("⟦ctx:steer⟧ do X")])
        self.assertTrue(self._alternates(out))
        self.assertEqual(len(out), 2)

    def test_no_anchor_text_is_lost(self):
        out = self._merged([self.S, self.U("AGENTS"), self.U("task"), self.U("⟦ctx:steer⟧ do X")])
        for piece in ("AGENTS", "task", "⟦ctx:steer⟧ do X"):
            self.assertIn(piece, out[1]["content"])

    def test_a_tool_result_followed_by_an_anchor(self):
        """The same violation, and the one merging by ROLE alone would miss — the template treats
        `tool` as a user turn, so tool+user is already two on the same side."""
        out = self._merged([self.S, self.U("task"), self.TC, self.T, self.U("⟦ctx:checks⟧ green")])
        self.assertTrue(self._alternates(out))
        self.assertIn("file body", out[-1]["content"])
        self.assertIn("⟦ctx:checks⟧ green", out[-1]["content"])

    def test_a_merged_run_keeps_the_role_of_its_first_message(self):
        """So a leading tool result keeps its <TOOL_RESPONSE> framing."""
        out = self._merged([self.S, self.U("t"), self.TC, self.T, self.U("anchor")])
        self.assertEqual(out[-1]["role"], "tool")

    def test_two_assistant_text_turns_merge(self):
        out = self._merged([self.S, self.U("a"), self.A("x"), self.A("y"), self.U("b")])
        self.assertTrue(self._alternates(out))
        self.assertIn("x", out[2]["content"]); self.assertIn("y", out[2]["content"])

    def test_a_tool_CALL_turn_is_never_folded(self):
        """A structured emission is not text — folding either side of it would corrupt the call."""
        out = self._merged([self.S, self.U("a"), self.TC, self.T, self.A("done"), self.U("next")])
        tc = [m for m in out if m.get("tool_calls")]
        self.assertEqual(len(tc), 1)
        self.assertEqual(tc[0]["tool_calls"][0]["function"]["name"], "read_file")

    def test_an_already_alternating_body_is_untouched(self):
        msgs = [self.S, self.U("a"), self.TC, self.T, self.A("done"), self.U("next")]
        self.assertEqual(len(self._merged(msgs)), len(msgs))

    def test_order_is_never_changed(self):
        out = self._merged([self.S, self.U("one"), self.U("two"), self.A("mid"), self.U("three")])
        self.assertLess(out[1]["content"].index("one"), out[1]["content"].index("two"))

    def test_off_by_default_and_other_models_untouched(self):
        from cria.config import Role
        body = {"messages": [self.S, self.U("a"), self.U("b")]}
        Role(name="coder", backend="local").apply(body)
        self.assertEqual(len(body["messages"]), 3)

    def test_the_suite_sets_it_for_nemotron_nano_only(self):
        import sys, pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "suite"))
        import sampling
        self.assertIn("merge_consecutive_turns", sampling.KNOBS)
        for model, roles in sampling.MODEL_SAMPLING.items():
            for role, knobs in roles.items():
                want = model == "nemotron-nano"
                self.assertEqual(knobs.get("merge_consecutive_turns", False), want, f"{model}/{role}")
