"""Has the reading a step asks for actually been done?

WHY THIS EXISTS. Two fabliq runs of the same task, same code, same model, failed from opposite
sides of the same hole:

  * PLANNER-ON (run 1785804243). The plan's step 1 was "Research the Ada Handles API documentation
    by fetching the GitHub repo root directory". That fetch is denied, so the step could never be
    satisfied, and the step critic correctly refused it forever: 114 of 195 calls went to step 1 and
    the run never reached step 2. Along the way the coder DID fetch `https://api.handle.me` and got
    HTTP 200 — the answer was one hop away — then went back to guessing GitHub URLs, 27 of them at a
    repository that does not exist.
  * PLANNER-OFF (run 1785805694). No plan step said "research", so nothing did. **Zero web_fetch
    calls in 237.** The coder wrote a resolver, unit tests, a live test and a README against
    `api.handle.me/v1/handle/` with fields `address`/`holder`/`totalHandles` — an API it invented
    whole. It scored 1/4 and the ceiling was structural: the resolver cannot resolve.

So a research step with no exit traps the run, and no research step at all lets it code against an
API nobody read. What was missing both times is the thing this module is: a way to ASK whether the
reading happened, grounded in what cria actually holds.

WHAT MAKES THE ANSWER TRUSTWORTHY is that the expensive half is deterministic. cria already records
every fetch that came back and what was parsed out of it (``loop._extract_fetches`` → url → status,
routes, response shapes). :func:`grounded_sources` filters that to the fetches that actually DEFINED
something. If nothing did, the verdict is NOT_DONE without a model call at all — no reasoner can
talk cria into believing a spec was read when the ledger holds no routes and no fields. Only when
real sources exist does a reasoner judge whether they answer THIS step (#8: deterministic code
gathers the facts, the reasoner judges them).

DIRECTION OF FAILURE. The one action this drives is CLEARING a research step, so an unparseable or
missing verdict is NOT_DONE — the step stays open and the ordinary step critic still governs it
(#13: fail closed on completion). The cost of that asymmetry is a few more turns; the cost of the
other direction is a deliverable built on an invented API, which is exactly what run 1785805694
shipped.
"""
from __future__ import annotations

from . import prompts
from .jsontext import extract_json_object, strip_think

# Coder turns between checks. A research step that is already satisfied should not burn a whole
# window proving it (114 calls in run 1785804243), and one that is genuinely unfinished should not
# pay a reasoner call every turn (#3 — silence over noise). Ten is the operator's cadence.
RESEARCH_CHECK_EVERY = 10

DONE, NOT_DONE, NOT_RESEARCH = "DONE", "NOT_DONE", "NOT_RESEARCH"


def grounded_sources(ledger: dict) -> list[tuple[str, str, str]]:
    """``(url, routes, shapes)`` for the fetches that came back 2xx AND defined something.

    A page that answered but yielded no routes and no response fields is NOT a source here. That
    distinction is the whole point: in run 1785804243 the ledger was injected into all 115 coder
    prompts and every line of it read "this page answered, but no endpoint definitions were found in
    it". Five HTTP 200s and nothing read. Counting those as research done would clear the step on the
    strength of the coder having successfully loaded a home page."""
    out = []
    for url, entry in (ledger or {}).items():
        status, routes, shapes = (tuple(entry) + ("", "", ""))[:3]
        if str(status).strip().startswith("2") and (str(routes).strip() or str(shapes).strip()):
            out.append((url, str(routes), str(shapes)))
    return out


def _sources_block(sources: list[tuple[str, str, str]]) -> str:
    lines = []
    for url, routes, shapes in sources:
        lines.append(f"- {url}")
        if routes.strip():
            lines.append(f"    routes it defines: {routes.strip()}")
        if shapes.strip():
            lines.append(f"    response fields it defines: {shapes.strip()}")
    return "\n".join(lines)


def step_reading_verdict(ask, task: str, step: str, sources: list[tuple[str, str, str]]) -> str:
    """``DONE`` / ``NOT_DONE`` / ``NOT_RESEARCH`` for one step against what has really been read.

    THREE-VALUED ON PURPOSE, and the third value is what keeps this from being a second completion
    judge. This runs on whatever step is in flight, and most steps are not asking for reading at all
    — "write the unit tests" is finished by writing tests, not by fetching anything. A two-valued
    question would force such a step into DONE or NOT_DONE and either answer would be cria ruling on
    work it was not asked about. ``NOT_RESEARCH`` is the escape, and it is the common answer.

    NO MODEL CALL when the ledger holds nothing. Not an optimisation — a guarantee: with no parsed
    routes and no parsed fields there is no evidence any reading happened, so there is nothing for a
    judge to weigh and no way for a confident wrong answer to clear the step.

    Unreadable answer → ``NOT_DONE``, the direction that leaves the step open."""
    if not sources:
        return NOT_DONE
    ans = ask(prompts.load("research_done"),
              prompts.render("research_done_user", task=task, step=step,
                             sources=_sources_block(sources)))
    obj = extract_json_object(strip_think(ans or ""))
    if not isinstance(obj, dict):
        return NOT_DONE
    verdict = str(obj.get("verdict", "")).strip().upper()
    return verdict if verdict in (DONE, NOT_DONE, NOT_RESEARCH) else NOT_DONE


# A step longer than this is not a step — it is the model writing the plan, or the work, or prose
# about both. Bounded rather than trimmed: an over-long answer is REFUSED (no step), never cut down
# to size, because half a sentence is a different instruction from the one the model wrote.
STEP_MAX_CHARS = 400


def authored_research_step(ask, task: str, domain: str) -> str:
    """ONE reading step for ``task``, written by the MODEL — "" when it does not produce a usable one.

    THE AUTHORSHIP IS THE POINT. cria may notice, deterministically, that the task names an external
    source; it may not decide what reading that source requires. The first version of this function
    rendered the step from a cria template, which is cria writing plan steps — the practice this repo
    retired, and the operator's correction: the model authors the step, cria only asks for it (#8 —
    deterministic code gathers the fact, the model does the judging).

    NO PATHS. The prompt forbids naming a URL path, a file, or an endpoint, and this refuses an answer
    that names one anyway. That is the exact defect that cost run 1785804243 its whole window: its
    step said "by fetching the GitHub repo root directory", a source that returns denied, so the step
    could never be satisfied and 114 of 195 calls died against it. A step that names WHAT to learn
    cannot be unsatisfiable that way; a step that names WHERE can.

    SAFE NULL, NOT A FALLBACK. An empty, over-long, or path-naming answer yields "" and the caller
    simply builds the plan it would have built before. cria never substitutes its own sentence for
    the one the model failed to write."""
    text = " ".join((ask(prompts.load("research_step"),
                         prompts.render("research_step_user", task=task, domain=domain))
                     or "").split())
    if not text or len(text) > STEP_MAX_CHARS:
        return ""
    lowered = text.lower()
    if "://" in lowered or any(p in lowered for p in ("openapi.json", "swagger", ".yml", ".yaml")):
        return ""      # it named a path anyway — the one thing the prompt forbids
    return text
