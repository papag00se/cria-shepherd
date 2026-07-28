"""Live status ticker — the pipeline's phase boundaries, streamed to the HUMAN as they happen.

At 27B speeds the first minutes of a run are a black box: classify → planner gather rounds →
drafting → judges → coder steps, all internal non-streamed calls, nothing on the wire but
heartbeats (operator: "for the first 7 mins there was no feedback"). Every one of those calls
already announces itself through the request's rlog — this maps a CURATED set of event kinds to
one-line human status, which the server streams as it happens.

The lines ride cria's ⟦cria⟧ marker rail: rendered and persisted by the harness, STRIPPED from
inbound history (indicators.strip_history) so the model never reads them — the same proven path
the banner and the reasoning fold use. Deterministic text from plumbing that already exists; no
new model calls, no new information shown to the coder.
"""

from __future__ import annotations

from .indicators import MARKER

# kind -> template. {f} placeholders come from the event's own fields; a missing field kills the
# line (silence over a broken template). Curated and SPARSE on purpose: phase transitions and
# per-round beats, never per-token or per-request spam.
_LINES = {
    "route.classify": "classifying the request",
    "plan.gather": "research · {tool}",
    "plan.research_nudge": "research · nudging the planner to read a real source",
    "plan.drafted": "drafting the plan",
    "plan.submitted": "plan ready · {steps} steps",
    "plan.missing_deliverables": "plan coverage · handing back ({missing})",
    "plan.noise_dropped": "plan checks · dropped {count} noise step(s)",
    "plan.noise_uncovered": "plan checks · refused a drop that uncovered deliverables",
    "loop.item": "step {step}/{total}",
    "loop.replan": "replanning the remaining steps",
    "loop.replan_uncovered": "replan refused · it dropped deliverables",
    "loop.probe": "running the repo's checks",
    "loop.verify_inspect": "judge · inspecting the workspace",
    "loop.done_confirm": "confirming the pass",
    "loop.done_critic": "completion check",
    "loop.satisfaction_confirm": "confirming completion",
    # Per-ACTION lines (operator: a file write happened with no visible indicator — the harness
    # renders the lowered call as an opaque sentinel blob). Narrated at the lowering choke point.
    "writeproxy.lowered": None,  # handled by _action_line (needs per-tool wording)
    "loop.truncated": "write cut off — retrying in smaller pieces",
    "loop.truncated_dropped": "partial write refused",
}

_ACTION_LINES = {
    "write_file": "writing {target}",
    "edit_file": "editing {target}",
    "read_file": "reading {target}",
    "list_dir": "listing {target}",
    "web_fetch": "fetching {detail}",
    "web_search": "searching · {detail}",
}


def _action_line(fields: dict) -> str | None:
    tpl = _ACTION_LINES.get(str(fields.get("tool") or ""))
    if tpl is None:
        return f"{MARKER}{fields.get('tool')}"
    try:
        line = tpl.format(target=fields.get("target") or "?", detail=fields.get("detail") or "?")
    except (KeyError, IndexError):
        return None
    return f"{MARKER}{line}"

# Fallback for the one kind that fires on EVERY model call: announce it by the call's PHASE, so a
# slow internal call (a 27B judge at ~7 tok/s) shows as itself rather than as silence. Consecutive
# duplicates are deduped by the writer, so repeated same-phase calls tick once.
_PHASE_LINES = (
    ("planner", "planning · thinking"),
    ("coder", "coder · working"),
    ("critic-confirm", "confirming the pass"),
    ("critic", "verifying the step"),
    ("satisfaction-confirm", "confirming completion"),
    ("satisfaction", "completion check"),
    ("self-compact-refold", "condensing the session summary"),
    ("self-compact", "compacting history"),
    ("classifier", "classifying"),
    ("compactor", "summarizing"),
    ("reasoner", "reasoning"),
)


def line_for(kind: str, phase: str | None, fields: dict) -> str | None:
    """The ⟦cria⟧ status line for an rlog event, or None for the (many) kinds that stay silent."""
    if kind == "writeproxy.lowered":
        return _action_line(fields)
    tpl = _LINES.get(kind)
    if tpl is not None:
        try:
            return f"{MARKER}{tpl.format(**fields)}"
        except (KeyError, IndexError):
            return None  # a template's field vanished upstream — silence over a broken line
    if kind == "upstream.request" and phase:
        for prefix, text in _PHASE_LINES:
            if phase.startswith(prefix):
                return f"{MARKER}{text}"
    return None


class StatusWriter:
    """Dedupes consecutive identical lines and hands the rest to ``write(text)``. The write callable
    owns transport (an SSE delta on the wire); failures are swallowed — a status line must never
    break the request it narrates."""

    def __init__(self, write) -> None:
        self._write = write
        self._last: str | None = None
        self.lines = 0

    def on_event(self, kind: str, phase: str | None, fields: dict) -> None:
        line = line_for(kind, phase, fields)
        if line is None or line == self._last:
            return
        self._last = line
        try:
            self._write(line)
            self.lines += 1
        except Exception:  # noqa: BLE001 — narration must never break the narrated request
            pass
