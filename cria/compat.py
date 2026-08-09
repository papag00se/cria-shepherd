"""Is the model behind this endpoint one cria can actually drive? — the connect banner.

WHY THIS EXISTS. nemotron-nano spent two runs and 8 minutes of wall clock proving something its
chat template said up front: it enforces strict user/assistant alternation, and cria's whole anchor
mechanism is consecutive user turns. The first run died in 24 seconds on a 400. Before it,
DeepSeek-R1-Distill spent 30 calls and ZERO assistant turns proving something ITS template also
said up front: no tools branch at all, so it can never emit a tool call. Both facts were readable
from `/props` before the first token was generated. Nobody read them, so both cost a run and a walk.

WHAT IT IS NOT. It never gates. Principle 19 is explicit that a model which breaks the harness is a
resilience REQUIREMENT, not grounds to drop it — so this REPORTS, and cria goes on to drive the
model exactly as before. A check that came back red on a model the operator wants to run must cost
them nothing but a line of text.

WHICH CHECKS EARN A LINE, and the measurement behind each (principle 15 — base-rate it before you
build it). Four candidates were screened against every ladder model's real GGUF template plus the
two retired ones. Only these two discriminate:

  * TOOLS BRANCH — flags r1-llama (its template has no tools branch: measured 0 tool calls in 30
    coder turns), clean on all 9 standing models.
  * TURN ORDER — flags nemotron-nano (the alternation guard), clean on all 9. cria HANDLES this one
    when the role sets ``merge_consecutive_turns``, so it reports 🟡 handled rather than 🔴 broken.

Two more were built, measured, and DELETED, which is the useful half of the exercise:

  * "empty tool_calls renders an unclosed tag" — true of gemma4 and qwopus, both of which score
    4/4. cria never sends that shape (0 of 330,415 captured assistant turns), so the hazard cannot
    fire and the line would be pure noise on two working models (#3, silence over noise).
  * "arguments double-encoded when passed as a JSON string" — true of qwopus, which scores 4/4.
    cria does send arguments as strings (20,325 of 20,325 sampled), so llama.cpp is evidently
    normalizing them before the template sees them. A warning the evidence contradicts is a false
    fact (#5b).

A check that fires on a model which demonstrably works is not a check, it is a footgun with a
green tick next to it.
"""
from __future__ import annotations

# Status glyphs. Deliberately plain — a coloured circle reads at a glance in any terminal and
# carries no meaning a colour-blind reader loses (the label says the same thing in words).
OK, HANDLED, BROKEN = "🟢", "🟡", "🔴"


def probe(props: dict | None, *, merge_turns: bool = False) -> list[tuple[str, str, str]]:
    """``(glyph, label, detail)`` per check, from a llama.cpp ``/props`` payload.

    ``merge_turns`` is the coder role's ``merge_consecutive_turns`` — the knob that makes a strict
    template survivable — so the banner can distinguish "this model would break" from "this model
    would break and cria is already handling it".

    Returns [] when there is nothing to report on (no props, or a payload with neither capability
    flags nor a template — a cloud endpoint, or a server too old to expose them). Saying nothing is
    always allowed; saying something unfounded is not."""
    if not isinstance(props, dict):
        return []
    caps = props.get("chat_template_caps")
    tmpl = props.get("chat_template")
    if not isinstance(caps, dict) and not isinstance(tmpl, str):
        return []
    caps = caps if isinstance(caps, dict) else {}
    tmpl = tmpl if isinstance(tmpl, str) else ""

    out: list[tuple[str, str, str]] = []

    # TOOLS. The capability flag is the server's own answer and is preferred; the template scan is
    # the fallback for a build that predates chat_template_caps. cria's coder path is ~100% tool
    # calls, so a model without this cannot do the job at all — the r1-llama outcome.
    if "supports_tools" in caps or "supports_tool_calls" in caps:
        # Absent key → True, so a server that answers only ONE of the pair is not read as a denial.
        # The earlier form demanded `supports_tools` while the guard accepted either, which made a
        # build exposing only `supports_tool_calls` print a red 'no tool-call branch' over a template
        # that plainly has one — a false fact about a working model, the exact outcome this module
        # was written to avoid (#5b).
        has_tools = bool(caps.get("supports_tools", True)) and bool(caps.get("supports_tool_calls", True))
    else:
        has_tools = ("tools" in tmpl) or ("tool_calls" in tmpl)
    out.append((OK, "tools", "") if has_tools else
               (BROKEN, "tools", "this template has no tool-call branch — the model cannot emit one"))

    # TURN ORDER. Meta's Llama lineage raises on non-alternating roles; cria's ⟦ctx:…⟧ anchors are
    # consecutive user turns, so the FIRST coder call is already a violation.
    # Reported ONLY when there is a template to read. A /props carrying capability flags but no
    # chat_template would otherwise yield a green asserted from absence of evidence — cria stating a
    # fact it never checked (#5b). No template, no line.
    strict = ("must alternate" in tmpl) or ("loop.index0 % 2" in tmpl)
    if not tmpl:
        pass
    elif not strict:
        out.append((OK, "turn order", ""))
    elif merge_turns:
        out.append((HANDLED, "turn order", "strict alternation — merging consecutive turns"))
    else:
        out.append((BROKEN, "turn order",
                    "strict alternation — consecutive turns are rejected; set merge_consecutive_turns"))

    # SYSTEM ROLE. Only reported when the server actually answers it; cria puts every instruction it
    # writes in a system message, and a template with nowhere to put one silently drops the frame.
    if "supports_system_role" in caps:
        if caps.get("supports_system_role"):
            out.append((OK, "system role", ""))
        else:
            out.append((HANDLED if props.get("_collapse_system") else BROKEN, "system role",
                        "no system slot — fold it into the first user turn (collapse_system_prompt)"))
    return out


def banner(props: dict | None, *, model: str = "", merge_turns: bool = False,
           collapse_system: bool = False) -> list[str]:
    """The connect lines, WITHOUT the marker prefix — the caller adds it (indicators owns the rail).

    Two lines at most: what cria connected to, and one glyph run of the checks. Terse on purpose —
    this rides in front of the operator's first answer of the session, every session."""
    if isinstance(props, dict) and collapse_system:
        props = {**props, "_collapse_system": True}
    checks = probe(props, merge_turns=merge_turns)
    if not checks:
        return []
    head = f"cria connected · {model}" if model else "cria connected"
    n_ctx = (props.get("default_generation_settings") or {}).get("n_ctx") if isinstance(props, dict) else None
    if isinstance(n_ctx, int) and n_ctx > 0:
        head += f" · {n_ctx:,} ctx"
    lines = [head, " ".join(f"{g} {label}" for g, label, _ in checks)]
    # A red or handled check earns its own explanatory line; a clean run stays two lines (#3).
    lines += [f"{g} {detail}" for g, _, detail in checks if detail]
    return lines
