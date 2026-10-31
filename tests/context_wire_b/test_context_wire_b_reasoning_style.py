"""Reasoning and sampling knobs land in the dialect the backend (and its served template) actually reads, and only that dialect's keys."""
import json
from unittest import mock

from context_wire_b_helpers import Rlog, rows
from cria.reasoning import apply_reasoning, apply_sampling, detect_served_style, infer_style
from cria.upstream import Upstream

SAMPLING = {"temperature": 0.1, "top_p": 0.95, "top_k": 64, "repeat_penalty": 1.1, "presence_penalty": 1.5, "min_p": 0.0, "max_tokens": 4096}
NEMOTRON = "{% if enable_thinking is defined and enable_thinking %}on{% endif %}{{ enable_thinking }}{{ enable_thinking }}"
BONSAI = "{% if reasoning_effort == 'xhigh' %}...{% endif %}{{ reasoning_effort }}"

def applied(fn, *args, body=None):
    fn(body := {} if body is None else body, *args)
    return body

def test_reasoning_and_sampling_translate_per_backend_without_mixing_dialects():
    """A llama.cpp-only knob must never 400 or vanish on a cloud backend, and off must be a real off (not minimal effort)."""
    assert applied(apply_reasoning, "on", "openai") == {"reasoning_effort": "medium"} and applied(apply_reasoning, "off", "openai") == {"reasoning_effort": "none"}
    assert applied(apply_reasoning, "off", "openrouter") == {"reasoning": {"enabled": False}} and applied(apply_reasoning, "low", "openai") == {"reasoning_effort": "low"}
    assert applied(apply_reasoning, "off", "chat_template", body={"chat_template_kwargs": {"foo": 1}}) == {"chat_template_kwargs": {"foo": 1, "enable_thinking": False}}
    assert all(applied(apply_reasoning, r, s) == {} for r in ("auto", None) for s in ("openai", "openrouter", "chat_template", "none")) and applied(apply_reasoning, "on", "none") == {}
    assert applied(apply_sampling, SAMPLING, "chat_template") == SAMPLING and applied(apply_sampling, SAMPLING, "none") == {}
    router = applied(apply_sampling, SAMPLING, "openrouter")
    assert router["repetition_penalty"] == 1.1 and "repeat_penalty" not in router and router["top_k"] == 64
    assert applied(apply_sampling, SAMPLING, "openai") == {"temperature": 0.1, "top_p": 0.95, "presence_penalty": 1.5, "max_tokens": 4096}
    assert [infer_style(u) for u in ("https://openrouter.ai/api/v1", "https://api.groq.com/openai/v1", None)] == ["openrouter", "openai", "openai"]
    assert [detect_served_style(t) for t in (NEMOTRON, BONSAI, "{{ messages }}", "{{ enable_thinking }}{{ reasoning_effort }}")] == ["chat_template", "openai", None, None]

@rows([({"reasoning_effort": "none"}, NEMOTRON, {"chat_template_kwargs": {"enable_thinking": False}}),         # row p28: reasoning never turned off, 37,719 tokens burned for zero content
       ({"reasoning_effort": "medium"}, NEMOTRON, {"chat_template_kwargs": {"enable_thinking": True}}),
       ({"chat_template_kwargs": {"enable_thinking": False}}, BONSAI, {"reasoning_effort": "none"}),
       ({"chat_template_kwargs": {"enable_thinking": False}}, NEMOTRON, None),                                    # matching: left alone, silent
       ({"reasoning_effort": "none"}, "{{ messages }}", None)])                                                   # ambiguous template: the explicit config choice wins
def test_the_wire_corrects_a_knob_the_served_template_demonstrably_ignores(knob, template, corrected):
    """[backends.local] reasoning_style='openai' outlived a swap to a model reading enable_thinking; the wire is the last point that has read the served template."""
    up, log = Upstream("http://x", context_window=8192), Rlog()
    up._loaded_model, body = "m", {**knob, "messages": [{"role": "user", "content": "hi"}]}
    reply = mock.MagicMock(__enter__=lambda s: s, __exit__=lambda *a: False, read=lambda: json.dumps({"chat_template": template}).encode())
    with mock.patch("cria.upstream.urllib.request.urlopen", return_value=reply):
        up._prep(body, False, log)
    assert {k: v for k, v in body.items() if k not in ("messages", "model")} == (corrected or knob)
    assert [k for k, _ in log.events] == (["reasoning.convention_autocorrect"] if corrected else [])
    cloud = {"reasoning_effort": "none", "messages": body["messages"]}
    with mock.patch("cria.upstream.urllib.request.urlopen", side_effect=AssertionError("must not probe a keyed endpoint")):
        Upstream("http://x", api_key="sk-test")._prep(cloud, False, log)
    assert cloud["reasoning_effort"] == "none"
