"""The ONE owner of every bound whose size stands in for "how much fits in the window".

A fixed number tuned on one model's window is wrong on every other: a 16,384-token reply cap is a
third of a 49,152-token window and the WHOLE window of a 16K model (a compaction lens reserved its
whole cap as reply room and the floor swapped 53-215 evidence turns for a digest before the lens read
them); a 48,000-character trigger is three-quarters of a 16K window and a rounding error on 262K.

Each such bound is a :class:`Cap`: an ``int`` EQUAL TO TODAY'S VALUE that also knows its name. A caller
that has no window in hand just carries it; every place that needs the number resolves it against the
window of the model that will actually ANSWER:

* a Cap placed in a request body (``max_tokens`` / ``cria_output_reserve``) is resolved by
  ``Upstream._prep`` against that Upstream's own measured window — the last point before
  serialization, so a classifier or reasoner role on a different server is sized by ITS window
  (principle 24: a wire invariant is enforced at the wire);
* in-process arithmetic (the self-compaction tail / recompact / refold sizes, the distiller's piece size) calls
  :func:`resolve` with the window it already measured.

``cap = clamp(reference * window // REFERENCE_WINDOW, floor, ceiling)``. At the 49,152-token window the
caps were tuned on, that is EXACTLY the old constant (``tests/test_window_caps.py`` proves it for the
whole table). An UNKNOWN window — never discovered, or only a guess — yields the reference value, i.e.
the old behaviour: unknown is not small (docs/principles.md). An operator override (a role's
``max_tokens`` / ``output_reserve``) is an ``int`` and is never rescaled.

What does NOT belong here, and why, is written down next to the lint that enforces it
(``tests/test_no_new_unmarked_bounds.py``): harness/OS transport limits, safety/time/resource bounds,
one-word reply reserves and measured prompt-frame sizes do not move with the window.
"""
from __future__ import annotations

from . import bodykeys

#: The window every reference value was tuned on (ornith1.5_9b, llama.cpp ``--ctx-size 49152``).
REFERENCE_WINDOW = 49_152

# Body fields a Cap may ride in. Both are token counts of the window.
_BODY_FIELDS = ("max_tokens", bodykeys.OUTPUT_RESERVE)


class Cap(int):
    """An ``int`` equal to the reference value, remembering which bound it is.

    Subclassing ``int`` is deliberate: any consumer that does not resolve it (a fake upstream, a log
    line, ``json.dumps``) sees exactly today's number, so an unresolved Cap can only ever behave as
    the old constant did.
    """

    def __new__(cls, value: int, name: str = ""):
        self = super().__new__(cls, value)
        self.name = name
        return self

    def __getnewargs__(self):          # copy / deepcopy / pickle rebuild through __new__
        return (int(self), self.name)

    def __repr__(self):
        return f"Cap({self.name}={int(self)})"


# name -> (reference value at REFERENCE_WINDOW, floor, ceiling). Each row says what the bound IS.
_SPECS: dict[str, tuple[int, int, int]] = {
    # A runaway guard on a judge/classifier reply (classify.JUDGE_MAX_TOKENS). Floor: measured p99 of a
    # judge's reasoning+verdict is 8,192 tokens, and a judge that hits its cap answers NOTHING, so a
    # small window still gets 6,144. Ceiling: a guard, not a budget — 2x is already "well above where
    # real judgements land", and nothing else stops a runaway non-streamed call.
    "judge_reply": (16_384, 6_144, 32_768),
    # A prose briefing / rollup / compaction summary reply (loop.SUMMARIZE_MAX_TOKENS, ROLLUP_MAX_TOKENS).
    "summary_reply": (8_192, 3_072, 32_768),
    # The step/completion critic's reply, which may first inspect with read-only tools (loop._judge_completion).
    "critic_reply": (8_192, 3_072, 32_768),
    # The planner's plan reply (planner._reason_once): same job and size as a summary reply.
    "plan_reply": (8_192, 3_072, 32_768),
    # One chunked-distillation extraction call's reply room (handoffdistill.EXTRACT_REPLY_TOKENS). The
    # piece it extracts from grows with the window, so its facts do.
    "extract_reply": (4_096, 2_048, 16_384),
    # Reply room the floor holds back when a request names neither output_reserve nor max_tokens
    # (contextfloor.DEFAULT_GEN_RESERVE).
    "gen_reserve": (4_096, 2_048, 16_384),
    # The self-compaction working-set sizes, in ESTIMATED tokens (chars/4) — selfcompact.*_TOKENS. There is
    # deliberately NO trigger here: when to compact is a predicate over measured room (selfcompact.view_room /
    # expected_growth), not a share of the window.
    "selfcompact_keep_tail": (6_000, 1_500, 36_000),
    "selfcompact_recompact": (4_000, 1_000, 24_000),
    "selfcompact_refold": (6_000, 1_500, 36_000),
    # Dependency-surface notes appended to build-tool results (returnedpolicies), in BYTES. One surface: sized by
    # the measured real surfaces (decimal 4,645 B, toml 3,152 B, commons-csv 7,007 B) — the floor keeps a
    # surface like decimal's WHOLE on a small window (a smaller budget truncated the member list before
    # `Round`, the very member that contradicts the invented one the note exists to catch). The SUM of notes
    # one request carries: 24 KB is ~two thirds of a 16K window's bytes, so it scales with the window; the
    # floor still holds one whole surface plus a pointer, the ceiling is a runaway bound.
    "dependency_surface": (6_000, 4_800, 12_000),
    "dependency_notes": (24_000, 8_000, 96_000),
    # Composed-evidence block size, in CHARACTERS (evidencesummary.EVIDENCE_BLOCK_CHARS): the unit the
    # floor drops oldest-first, so it is a granularity of "what fits".
    "evidence_block": (6_000, 2_000, 36_000),
}


def _cap(name: str) -> Cap:
    return Cap(_SPECS[name][0], name)


JUDGE_REPLY = _cap("judge_reply")
SUMMARY_REPLY = _cap("summary_reply")
CRITIC_REPLY = _cap("critic_reply")
PLAN_REPLY = _cap("plan_reply")
EXTRACT_REPLY = _cap("extract_reply")
GEN_RESERVE = _cap("gen_reserve")
SELFCOMPACT_KEEP_TAIL = _cap("selfcompact_keep_tail")
SELFCOMPACT_RECOMPACT = _cap("selfcompact_recompact")
SELFCOMPACT_REFOLD = _cap("selfcompact_refold")
DEPENDENCY_SURFACE = _cap("dependency_surface")
DEPENDENCY_NOTES = _cap("dependency_notes")
EVIDENCE_BLOCK = _cap("evidence_block")

for _name, (_ref, _lo, _hi) in _SPECS.items():
    assert _lo <= _ref <= _hi, _name

NAMES = tuple(_SPECS)


def scaled(cap: Cap, window: int | None) -> int:
    """``cap`` at ``window`` real tokens; the reference value when the window is unknown."""
    reference, floor, ceiling = _SPECS[cap.name]
    if not isinstance(window, int) or isinstance(window, bool) or window <= 0:
        return reference
    return max(floor, min(ceiling, reference * window // REFERENCE_WINDOW))


def resolve(value, window: int | None):
    """A Cap becomes its plain ``int`` at ``window``; anything else (an explicit operator or caller
    value, ``None``) passes through untouched."""
    return scaled(value, window) if isinstance(value, Cap) else value


def has_caps(body: dict) -> bool:
    return any(isinstance(body.get(field), Cap) for field in _BODY_FIELDS)


def resolve_body(body: dict, window: int | None) -> dict:
    """``body`` with its Cap fields resolved against ``window``. The same object when it carries none,
    so a body without Caps ships byte-identical and costs nothing."""
    if not has_caps(body):
        return body
    return {**body, **{field: resolve(body[field], window)
                       for field in _BODY_FIELDS if isinstance(body.get(field), Cap)}}


def known_window(owner, rlog) -> int | None:
    """The real window of ``owner`` (an ``Upstream``), or None when unknown or only guessed: without a
    measurement nothing can be sized, and unknown is never read as small."""
    resolver = getattr(owner, "_resolve_window", None)
    if not callable(resolver):
        return None
    window = resolver(rlog)
    return None if getattr(owner, "_window_guessed", False) else window


def window_of(chat_fn, rlog) -> int | None:
    """The real window of the Upstream behind ``chat_fn`` (a bound ``Upstream.chat``, or a closure
    carrying ``.upstream``): the model that will actually answer."""
    return known_window(getattr(chat_fn, "__self__", None) or getattr(chat_fn, "upstream", None), rlog)
