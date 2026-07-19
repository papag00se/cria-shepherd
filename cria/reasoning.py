"""Translate cria's portable reasoning on/off into whatever parameter shape a backend
understands. There is NO single cross-vendor standard for controlling a model's thinking,
so cria keeps ONE portable knob (a role's ``reasoning = "on" | "off"``) and this module maps
it to each backend's convention at send time:

  * ``chat_template`` — llama.cpp / vLLM / SGLang. A ``chat_template_kwargs.enable_thinking``
    boolean baked into the prompt template (plus, for OFF, a nothink prefill for models that
    narrate in ``content`` — that message-mutation stays in ``LocalRole.apply``). LOCAL default.

  * ``openai`` — OpenAI, Groq, Fireworks, Together, and most OpenAI-compatible gateways: a
    top-level ``reasoning_effort`` string. Values ``"low" | "medium" | "high"``; ``"none"``
    disables on providers that accept it (Groq). OpenAI's own disable token is ``"minimal"``
    — set the role's ``reasoning = "minimal"`` explicitly for api.openai.com.

  * ``openrouter`` — openrouter.ai's unified object: ``reasoning: {effort | max_tokens |
    enabled}``. cria emits ``{"effort": …}`` to enable and ``{"enabled": false}`` to disable
    (a genuine off, unlike the effort-only providers).

  * ``none`` — emit nothing. Honest passthrough for a backend whose reasoning control cria
    doesn't model: the endpoint's own default governs, rather than silently sending a knob it
    ignores.

A role's ``reasoning`` value is portable ("on"/"off"), but an explicit effort token
("minimal"/"low"/"medium"/"high"/"none") is passed through VERBATIM for the effort-shaped
styles — so an operator targeting a specific provider can name its exact level.
"""

from __future__ import annotations

# The effort tokens the OpenAI/OpenRouter families understand, passed through verbatim when a
# role names one directly (rather than the portable "on"/"off").
EFFORT_TOKENS = frozenset({"minimal", "low", "medium", "high", "none"})

# What the PORTABLE values mean for an effort-shaped backend. "off" -> "none" (Groq/OpenRouter
# honor it; api.openai.com wants "minimal", which an operator sets explicitly). Not env vars —
# these are protocol constants, one per portable value.
_ON_EFFORT = "medium"
_OFF_EFFORT = "none"


def infer_style(base_url: str | None) -> str:
    """The reasoning convention to assume for an endpoint when the provider didn't set one
    explicitly. openrouter.ai has its own object shape; every other OpenAI-compatible host
    (OpenAI, Groq, Fireworks, Together, …) takes ``reasoning_effort``."""
    if base_url and "openrouter.ai" in base_url.lower():
        return "openrouter"
    return "openai"


def _effort_for(reasoning: str) -> str | None:
    """Resolve a role's ``reasoning`` to an effort token, or None for 'leave it to the backend'."""
    if reasoning in EFFORT_TOKENS:
        return reasoning  # an explicit level, named by the operator — passed through verbatim
    if reasoning == "on":
        return _ON_EFFORT
    if reasoning == "off":
        return _OFF_EFFORT
    return None  # "auto"/None/unknown → don't touch the request


def apply_reasoning(body: dict, reasoning: str | None, style: str) -> None:
    """Attach ``reasoning`` to ``body`` in the given backend's convention, in place. A no-op when
    reasoning is unset/"auto" or the style is ``none``. Only ONE convention's keys are written,
    so a body never carries a mix that a strict endpoint would reject.

    NOTE: the ``chat_template`` OFF nothink prefill (a message mutation) is NOT done here — it
    stays in ``LocalRole.apply`` where the messages are owned. This function only writes the
    top-level reasoning parameter(s)."""
    if reasoning in (None, "auto"):
        return
    if style == "none":
        return
    if style == "chat_template":
        body.setdefault("chat_template_kwargs", {})["enable_thinking"] = reasoning != "off"
        return
    effort = _effort_for(reasoning)
    if effort is None:
        return
    if style == "openrouter":
        body["reasoning"] = {"enabled": False} if effort == "none" else {"effort": effort}
    else:  # "openai" and any other effort-shaped OpenAI-compatible gateway
        body["reasoning_effort"] = effort
