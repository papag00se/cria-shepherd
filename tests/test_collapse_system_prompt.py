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
