import unittest

from cria.reasoning import apply_reasoning, apply_sampling, detect_served_style, infer_style


class ApplySamplingTests(unittest.TestCase):
    """Sampling is translated per backend dialect — a llama.cpp-only knob must never 400 or silently
    vanish on a cloud backend (the same portability fix as reasoning)."""

    P = {"temperature": 0.1, "top_p": 0.95, "top_k": 64, "repeat_penalty": 1.1,
         "presence_penalty": 1.5, "min_p": 0.0, "max_tokens": 4096}

    def _apply(self, style):
        b = {}
        apply_sampling(b, self.P, style)
        return b

    def test_chat_template_passes_all_natively(self):
        self.assertEqual(self._apply("chat_template"),
                         {"temperature": 0.1, "top_p": 0.95, "top_k": 64, "min_p": 0.0,
                          "repeat_penalty": 1.1, "presence_penalty": 1.5,
                          "max_tokens": 4096})

    def test_openrouter_keeps_extensions_and_renames_repeat_penalty(self):
        b = self._apply("openrouter")
        self.assertEqual(b["repetition_penalty"], 1.1)     # renamed to OpenRouter's name
        self.assertNotIn("repeat_penalty", b)
        self.assertIn("top_k", b)
        self.assertIn("min_p", b)

    def test_openai_drops_the_llama_only_knobs(self):
        b = self._apply("openai")
        self.assertEqual(b, {"temperature": 0.1, "top_p": 0.95,
                             "presence_penalty": 1.5, "max_tokens": 4096})
        for k in ("top_k", "min_p", "repeat_penalty", "repetition_penalty"):
            self.assertNotIn(k, b)                          # would 400 / have no equivalent

    def test_cli_none_sends_no_sampling(self):
        self.assertEqual(self._apply("none"), {})

    def test_zero_min_p_is_a_real_value_not_dropped(self):
        b = self._apply("chat_template")
        self.assertIn("min_p", b)                           # 0.0 != None
        self.assertEqual(b["min_p"], 0.0)

    def test_unset_params_are_omitted(self):
        b = {}
        apply_sampling(b, {"temperature": 0.5}, "openai")   # only temperature set
        self.assertEqual(b, {"temperature": 0.5})


class InferStyleTests(unittest.TestCase):
    def test_openrouter_host_infers_openrouter(self):
        self.assertEqual(infer_style("https://openrouter.ai/api/v1"), "openrouter")

    def test_groq_and_openai_and_unknown_infer_openai_effort(self):
        for url in ("https://api.groq.com/openai/v1", "https://api.openai.com/v1",
                    "https://any-compatible-host.example/v1"):
            self.assertEqual(infer_style(url), "openai")

    def test_none_base_url_defaults_to_openai(self):
        self.assertEqual(infer_style(None), "openai")


class DetectServedStyleTests(unittest.TestCase):
    """C41: what a served jinja template actually consumes, read from its own text — the signal
    Upstream._reconcile_reasoning_convention uses to catch a stale `reasoning_style` config line."""

    def test_nemotron_shaped_template_detects_chat_template(self):
        # The real signature from row p28's live /props: enable_thinking referenced repeatedly,
        # reasoning_effort never.
        tmpl = ("{% if enable_thinking is defined and enable_thinking %}detailed thinking on"
                "{% endif %}{% if not enable_thinking %}detailed thinking off{% endif %}"
                "{{ enable_thinking }}{{ enable_thinking }}")
        self.assertEqual(detect_served_style(tmpl), "chat_template")

    def test_bonsai2_shaped_template_detects_openai(self):
        tmpl = "{% if reasoning_effort == 'xhigh' %}...{% endif %}{{ reasoning_effort }}"
        self.assertEqual(detect_served_style(tmpl), "openai")

    def test_neither_marker_is_ambiguous(self):
        self.assertIsNone(detect_served_style("{{ messages }}{% for m in messages %}{{ m }}{% endfor %}"))

    def test_both_markers_is_ambiguous(self):
        self.assertIsNone(detect_served_style("{{ enable_thinking }}{{ reasoning_effort }}"))


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
