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


# ---- B1: the proxy (L1-L3 coder) path logs the override ---------------------------------------
import types
from unittest import mock


class ProxyPathLogs(unittest.TestCase):
    def test_produce_completion_applies_role_with_rlog(self):
        from cria import server as srv
        from cria.server import CriaHandler
        role = Role(name="coder", backend="local", reasoning="on")
        h = CriaHandler.__new__(CriaHandler)
        h.server = types.SimpleNamespace(
            cfg=types.SimpleNamespace(routing=types.SimpleNamespace(
                roles={"coder": role}, context_fixes=False, engagement_level=1)))
        sent = []

        class _Provider:
            def chat(self, body, rlog):
                sent.append(copy.deepcopy(body))
                return json.dumps({"choices": [{"message": {"role": "assistant", "content": "ok"},
                                                "finish_reason": "stop"}]})

        body = _harness_body(reasoning_effort="none")
        rl = _Rlog()
        with mock.patch.object(srv, "_recognize_compaction", return_value=False), \
                mock.patch.object(srv, "_report_context_usage"), \
                mock.patch.object(h, "_classify", return_value=None), \
                mock.patch.object(h, "_engages_loop", return_value=False), \
                mock.patch.object(h, "_route", return_value=(_Provider(), types.SimpleNamespace(role="coder"))), \
                mock.patch.object(h, "_focus_trim", side_effect=lambda b, r: (b, None)), \
                mock.patch.object(h, "_translate_out", side_effect=lambda c, k, r: c), \
                mock.patch.object(h, "_finalize", side_effect=lambda c, k, r: c):
            h._produce_completion(body, rl, "sess")
        self.assertIs(_enable(sent[0]), True)
        self.assertNotIn("reasoning_effort", sent[0])
        ev = [e for e in rl.events if e[0] == "reasoning.inherited_control_overridden"]
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0][1]["dropped"], {"reasoning_effort": "none"})
        self.assertIs(ev[0][1]["agreed"], False)

    def test_event_is_info_when_the_dropped_control_agreed(self):
        b = _harness_body(reasoning_effort="high")
        rl = _Rlog()
        Role(name="coder", backend="local", reasoning="on").apply(b, rlog=rl)
        self.assertIs(rl.events[0][1]["agreed"], True)
        self.assertEqual(rl.events[0][1]["level"], "info")

    def test_shared_chat_template_kwargs_dict_is_not_mutated(self):
        shared = {"enable_thinking": True, "x": 1}
        b = _harness_body(chat_template_kwargs=shared)
        Role(name="c", backend="b", reasoning="off", think_protocol="openai").apply(b)
        self.assertEqual(shared, {"enable_thinking": True, "x": 1})
        shared2 = {"enable_thinking": True, "x": 1}
        b = _harness_body(chat_template_kwargs=shared2)
        Role(name="c", backend="l", reasoning="off").apply(b)
        self.assertEqual(shared2, {"enable_thinking": True, "x": 1})
        self.assertEqual(b["chat_template_kwargs"], {"enable_thinking": False, "x": 1})


# ---- B2: through Upstream._prep, with the served template stubbed -----------------------------
from cria.upstream import Upstream

_TEMPLATES = {
    "no_marker": "{{ messages }}",
    "enable_thinking": "{% if enable_thinking %}think{% endif %}",
    "reasoning_effort": "{% if reasoning_effort == 'x' %}.{% endif %}{{ reasoning_effort }}",
}


class _Props:
    def __init__(self, tmpl):
        self._p = json.dumps({"chat_template": tmpl}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, *a):
        return self._p


def _wire(role, tmpl, **controls):
    up = Upstream("http://x", context_window=8192)
    up._loaded_model = "m"
    b = _harness_body(**controls)
    role.apply(b)
    with mock.patch("cria.upstream.urllib.request.urlopen", return_value=_Props(tmpl)):
        data, _, _ = up._prep(b, False, _Rlog())
    return json.loads(data)


class ThroughPrep(unittest.TestCase):
    def _assert_one_convention(self, w, on):
        has_ct = "enable_thinking" in (w.get("chat_template_kwargs") or {})
        has_ef = "reasoning_effort" in w
        self.assertNotEqual(has_ct, has_ef, w)      # exactly one convention on the wire
        if has_ct:
            self.assertIs(w["chat_template_kwargs"]["enable_thinking"], on)
        else:
            self.assertEqual(w["reasoning_effort"] != "none", on)

    def test_every_served_template_gets_one_convention_with_the_roles_value(self):
        for name, tmpl in _TEMPLATES.items():
            for reasoning, on in (("on", True), ("off", False)):
                for inherited in ("none", "high"):
                    with self.subTest(template=name, role=reasoning, inherited=inherited):
                        w = _wire(Role(name="coder", backend="l", reasoning=reasoning), tmpl,
                                  reasoning_effort=inherited)
                        self._assert_one_convention(w, on)

    def test_openai_styled_role_on_each_template(self):
        for name, tmpl in _TEMPLATES.items():
            with self.subTest(template=name):
                w = _wire(Role(name="c", backend="b", reasoning="on", think_protocol="openai"), tmpl,
                          chat_template_kwargs={"enable_thinking": False})
                self._assert_one_convention(w, True)


if __name__ == "__main__":
    unittest.main()
