import unittest

from cria.reasoning import apply_reasoning, infer_style


class InferStyleTests(unittest.TestCase):
    def test_openrouter_host_infers_openrouter(self):
        self.assertEqual(infer_style("https://openrouter.ai/api/v1"), "openrouter")

    def test_groq_and_openai_and_unknown_infer_openai_effort(self):
        for url in ("https://api.groq.com/openai/v1", "https://api.openai.com/v1",
                    "https://any-compatible-host.example/v1"):
            self.assertEqual(infer_style(url), "openai")

    def test_none_base_url_defaults_to_openai(self):
        self.assertEqual(infer_style(None), "openai")


class ApplyReasoningTests(unittest.TestCase):
    """The portable on/off (and explicit effort tokens) land in each backend's own shape, and only
    that backend's keys are written — never a mix a strict endpoint would reject."""

    def test_openai_on_off(self):
        b = {}
        apply_reasoning(b, "on", "openai")
        self.assertEqual(b, {"reasoning_effort": "medium"})
        b = {}
        apply_reasoning(b, "off", "openai")
        self.assertEqual(b, {"reasoning_effort": "none"})

    def test_openai_explicit_token_passthrough(self):
        for tok in ("minimal", "low", "medium", "high", "none"):
            b = {}
            apply_reasoning(b, tok, "openai")
            self.assertEqual(b, {"reasoning_effort": tok})

    def test_openrouter_on_uses_effort_off_disables(self):
        b = {}
        apply_reasoning(b, "on", "openrouter")
        self.assertEqual(b, {"reasoning": {"effort": "medium"}})
        b = {}
        apply_reasoning(b, "off", "openrouter")
        self.assertEqual(b, {"reasoning": {"enabled": False}})  # a genuine off, not a min-effort

    def test_chat_template_toggles_enable_thinking(self):
        b = {}
        apply_reasoning(b, "on", "chat_template")
        self.assertEqual(b, {"chat_template_kwargs": {"enable_thinking": True}})
        b = {}
        apply_reasoning(b, "off", "chat_template")
        self.assertEqual(b, {"chat_template_kwargs": {"enable_thinking": False}})

    def test_chat_template_preserves_other_kwargs(self):
        b = {"chat_template_kwargs": {"foo": 1}}
        apply_reasoning(b, "off", "chat_template")
        self.assertEqual(b["chat_template_kwargs"], {"foo": 1, "enable_thinking": False})

    def test_none_style_and_auto_and_unset_are_noops(self):
        # style "none" — honest passthrough for a backend whose control we don't model
        b = {}
        apply_reasoning(b, "on", "none")
        self.assertEqual(b, {})
        # "auto"/None reasoning — leave the backend's own default alone, on every style
        for style in ("openai", "openrouter", "chat_template", "none"):
            for rsn in ("auto", None):
                b = {}
                apply_reasoning(b, rsn, style)
                self.assertEqual(b, {}, f"{rsn!r}/{style} should be a no-op")


if __name__ == "__main__":
    unittest.main()
