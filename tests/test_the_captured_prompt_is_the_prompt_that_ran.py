"""A capture that drops a template-branching key is a different prompt than the one that ran.

`Upstream._render_prompt` asks the server's `/apply-template` for the flat string the model
tokenizes, and its docstring calls that "literally 'what the model sees'". It forwarded `messages`,
`tools` and `chat_template_kwargs` — and not `reasoning_effort`, which Bonsai 2's chat template
branches on:

    {%- set resolved_reasoning_effort = reasoning_effort|default('xhigh') %}
    {%- if resolved_reasoning_effort == 'xhigh' %} ... {%- elif ... == 'low' %}

Verified against the live server, same messages, only the key changed:

    low   -> "Reasoning effort is set to low. Keep your thinking brief and focused..."
    xhigh -> "Reasoning effort is set to xhigh. Please think carefully through the task,
              validate key assumptions, consider plausible alternatives..."

Because the template DEFAULTS to xhigh, every capture rendered xhigh whatever was sent. A walk of
those captures reads a live knob as dead — which is exactly what happened on 2026-09-19: the
captures said `xhigh` while the wire body said `low`, and the wire body was right.

This is 5b inside the evidence a walk is conducted on, which is worse than 5b on the wire: the wire
can be re-read, but a walker who trusts the capture has no signal that it is wrong.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cria import upstream  # noqa: E402


class _FakeUpstream:
    """Just enough of Upstream to exercise _render_prompt's payload construction."""

    def __init__(self):
        self.seen: dict | None = None
        self._base_url = "http://127.0.0.1:0"

    _render_prompt = upstream.Upstream._render_prompt


def _payload_for(body: dict, monkeypatch) -> dict:
    captured = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"prompt": "rendered"}).encode()

    def fake_urlopen(req, timeout=None):
        captured.update(json.loads(req.data.decode()))
        return _Resp()

    monkeypatch.setattr(upstream.urllib.request, "urlopen", fake_urlopen)
    _FakeUpstream()._render_prompt(body)
    return captured


def test_reasoning_effort_reaches_apply_template(monkeypatch):
    """THE REGRESSION: the key the template branches on must be forwarded."""
    p = _payload_for({"messages": [{"role": "user", "content": "hi"}],
                      "reasoning_effort": "low"}, monkeypatch)
    assert p.get("reasoning_effort") == "low", (
        f"reasoning_effort was dropped; the capture would render the template's xhigh default "
        f"and misreport what the model saw. payload={p}"
    )


def test_the_existing_keys_are_still_forwarded(monkeypatch):
    p = _payload_for({"messages": [{"role": "user", "content": "hi"}],
                      "tools": [{"type": "function", "function": {"name": "t"}}],
                      "chat_template_kwargs": {"enable_thinking": True}}, monkeypatch)
    assert p["messages"] and p["tools"]
    assert p["chat_template_kwargs"] == {"enable_thinking": True}


def test_absent_reasoning_effort_is_not_invented(monkeypatch):
    """A body that never set it must not gain one — the capture mirrors the body, it does not
    editorialise. Sending an explicit null could also trip a strict template."""
    p = _payload_for({"messages": [{"role": "user", "content": "hi"}]}, monkeypatch)
    assert "reasoning_effort" not in p, p
