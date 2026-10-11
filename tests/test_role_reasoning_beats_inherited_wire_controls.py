"""A role's explicit reasoning setting is authoritative over an inherited harness control in a
different convention. Incident: phi4 A2 coder call 0011 carried Codex's `reasoning_effort: "none"`
AND the configured `chat_template_kwargs.enable_thinking: true`; llama.cpp reads reasoning_effort
AFTER enable_thinking, so the configured ON silently lost. Fixture = that saved wire body
(messages/tools trimmed)."""
import copy
import json
import pathlib
import unittest

from cria.config import Role

_FIX = json.loads((pathlib.Path(__file__).parent / "fixtures"
                   / "phi4_a2_coder_0011_controls.request.json").read_text())


class _Rlog:
    def __init__(self):
        self.events = []

    def emit(self, name, **kw):
        self.events.append((name, kw))


def _harness_body(**controls):
    """The body as the harness sent it: the fixture minus cria's own reasoning write."""
    b = copy.deepcopy(_FIX)
    b.pop("chat_template_kwargs")
    b.pop("reasoning_effort")
    b.update(controls)
    return b


def _enable(b):
    return (b.get("chat_template_kwargs") or {}).get("enable_thinking")


class RoleBeatsInherited(unittest.TestCase):
    def test_fixture_is_the_contradiction(self):
        self.assertEqual((_FIX["reasoning_effort"], _enable(_FIX)), ("none", True))

    def test_configured_on_beats_inherited_none(self):
        b, rl = _harness_body(reasoning_effort="none"), _Rlog()
        Role(name="coder", backend="local", reasoning="on").apply(b, rlog=rl)
        self.assertIs(_enable(b), True)
        self.assertNotIn("reasoning_effort", b)
        self.assertEqual(rl.events[0][0], "reasoning.inherited_control_overridden")
        self.assertEqual(rl.events[0][1]["dropped"], {"reasoning_effort": "none"})

    def test_configured_off_beats_inherited_effort(self):
        for eff in ("high", "medium"):
            b = _harness_body(reasoning_effort=eff)
            Role(name="coder", backend="local", reasoning="off").apply(b)
            self.assertIs(_enable(b), False)
            self.assertNotIn("reasoning_effort", b)

    def test_configured_openai_style_beats_inherited_enable_thinking(self):
        b = _harness_body(chat_template_kwargs={"enable_thinking": True, "x": 1})
        Role(name="c", backend="b", reasoning="off", think_protocol="openai").apply(b)
        self.assertEqual(b["reasoning_effort"], "none")
        self.assertEqual(b["chat_template_kwargs"], {"x": 1})
        b = _harness_body(chat_template_kwargs={"enable_thinking": True})
        Role(name="c", backend="b", reasoning="off", think_protocol="openai").apply(b)
        self.assertNotIn("chat_template_kwargs", b)

    def test_no_configured_setting_is_byte_identical(self):
        for r in (None, "auto"):
            b = copy.deepcopy(_FIX)
            before = json.dumps(b)
            rl = _Rlog()
            Role(name="coder", backend="local", reasoning=r).apply(b, rlog=rl)
            self.assertEqual(json.dumps(b), before)
            self.assertEqual(rl.events, [])

    def test_body_without_reasoning_fields_is_unaffected(self):
        b, rl = _harness_body(), _Rlog()
        Role(name="coder", backend="local", reasoning="on").apply(b, rlog=rl)
        self.assertEqual(rl.events, [])
        self.assertEqual(b["chat_template_kwargs"], {"enable_thinking": True})

    def test_consistent_inherited_control_unchanged_and_silent(self):
        b, rl = _harness_body(chat_template_kwargs={"enable_thinking": True}), _Rlog()
        Role(name="coder", backend="local", reasoning="on").apply(b, rlog=rl)
        self.assertEqual(b["chat_template_kwargs"], {"enable_thinking": True})
        self.assertEqual(rl.events, [])


if __name__ == "__main__":
    unittest.main()
