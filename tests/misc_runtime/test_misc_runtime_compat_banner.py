"""The connect banner states what cria found and what it reshaped - it reports, it never gates."""
import types

import pytest

from cria import compat, server

ALTERNATION = "{%- if (message['role'] in ['user','tool']) != (loop.index0 % 2 == 0) -%}{{- raise_exception('must alternate') -}}"
TOOLS = "{%- if message.get('tool_calls') is not none -%}<TOOLCALL>[{%- endfor -%}"
GOOD = {"supports_tools": True, "supports_tool_calls": True, "supports_system_role": True}
NO_SYSTEM = {**GOOD, "supports_system_role": False}
LOG = types.SimpleNamespace(emit=lambda *a, **k: None)


def props(template="", caps=None, n_ctx=None):
    p = {"chat_template": template, **({"chat_template_caps": caps} if caps is not None else {})}
    return {**p, "default_generation_settings": {"n_ctx": n_ctx}} if n_ctx else p


@pytest.mark.parametrize("payload,kwargs,glyph,said", [
    (props(TOOLS, GOOD, 49152), {}, None, "gemma4 · 49,152 ctx"),                       # a working model: two quiet lines
    (props(ALTERNATION + TOOLS, GOOD), {}, compat.BROKEN, "merge_consecutive_turns"),   # nemotron-nano: first call 400'd
    (props(ALTERNATION + TOOLS, GOOD), {"merge_turns": True}, compat.HANDLED, "merging consecutive turns"),
    (props("{{m.content}}"), {}, compat.BROKEN, "no tool-call branch"),                 # r1-llama: 30 calls, zero assistant turns
    (props(TOOLS, NO_SYSTEM), {"collapse_system": True}, compat.HANDLED, "fold it into"),
    (props(TOOLS, {"supports_tool_calls": True}), {}, None, "tools"),                   # one key of the pair is not a denial
])
def test_the_banner_names_what_is_broken_or_handled_and_a_clean_model_stays_quiet(payload, kwargs, glyph, said):
    lines = compat.banner(payload, model="gemma4", **kwargs)
    assert said in " ".join(lines) and (len(lines) == 2) is (glyph is None)
    assert (glyph in lines[1]) if glyph else (compat.BROKEN not in lines[1] and compat.HANDLED not in lines[1])


def test_no_usable_props_says_nothing_rather_than_guessing():
    assert all(compat.banner(p, model="m") == [] for p in (None, {}, "not a dict", {"unrelated": 1}))
    assert "turn order" not in [label for _, label, _ in compat.probe(props("", GOOD))]


def handler(up):
    fake = types.SimpleNamespace(server=types.SimpleNamespace(
        _connect_done=False, router=None, upstream=up, cfg=types.SimpleNamespace(routing=types.SimpleNamespace(roles={}))))
    fake._coder_endpoint = lambda: server.CriaHandler._coder_endpoint(fake)
    return fake


def test_the_one_shot_banner_is_spent_when_printed_not_when_built():
    """Spent while building, a renderer then declined to print (Responses adapter: 359 of 372 requests, no banner)."""
    for p, model in ((props(TOOLS, GOOD), None), ({"unrelated": 1}, "qwen35_9b_q6")):  # no loaded model / nothing to say
        fake = handler(types.SimpleNamespace(props=lambda r, p=p: p, loaded_model=lambda r, m=model: m))
        assert server.CriaHandler._take_connect_lines(fake, LOG) == [] and fake.server._connect_done is False
    fake = handler(types.SimpleNamespace(props=lambda r: props(TOOLS, GOOD), loaded_model=lambda r: "qwen35_9b_q6"))
    assert "qwen35_9b_q6" in server.CriaHandler._take_connect_lines(fake, LOG)[0]
    assert server.CriaHandler._take_connect_lines(fake, LOG) == []
