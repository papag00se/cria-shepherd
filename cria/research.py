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

import re

from . import denial, jsontext, prompts
from .jsontext import extract_json_object, strip_think

# Coder turns between checks. A research step that is already satisfied should not burn a whole
# window proving it (114 calls in run 1785804243), and one that is genuinely unfinished should not
# pay a reasoner call every turn (#3 — silence over noise). Ten is the operator's cadence.
RESEARCH_CHECK_EVERY = 10

DONE, NOT_DONE, NOT_RESEARCH = "DONE", "NOT_DONE", "NOT_RESEARCH"


def sources_read(ledger: dict, messages: list | None = None) -> list[tuple[str, str, str]]:
    """Everything really READ this session — the web documents that defined something, AND the files
    on disk that were opened and came back with content.

    RESEARCH IS NOT ONLY WEB. The first version of this module counted web fetches alone, which made
    the whole check inert for every other kind of reading a task can require: files already in the
    workspace, a library's own source, a schema on disk, a data set, a tool's `--help`. For those the
    ledger is empty, so the verdict was permanently NOT_DONE — the check could never clear the step it
    exists to clear, which is the trap it was built to remove, one class over.

    The rule is the same for both kinds and it is what keeps this honest: a source counts only when
    the read RETURNED SOMETHING. For a web document that means 2xx with routes or response fields
    actually parsed out of it — a page that answered and defined nothing is not research (run
    1785804243's ledger was five HTTP 200s reading "no endpoint definitions were found in it"). For a
    file it means the read produced content cria did not refuse and that was not empty. An attempted
    read is not a read."""
    out = list(grounded_sources(ledger))
    for path, size in files_read(messages or []):
        out.append((path, "", f"{size} chars read from disk"))
    return out


def files_read(messages: list) -> list[tuple[str, int]]:
    """``(path, chars)`` for each distinct file this session actually read, largest read per path.

    Reads the CALL for the path and its paired RESULT for the content, because only the pair carries
    both. A refusal (cria's own denial marker) is not a read, and neither is an empty result: both are
    the shapes that made a coder believe it had seen a file it had not."""
    calls: dict[str, str] = {}
    got: dict[str, int] = {}
    for m in messages or []:
        for tc in (m.get("tool_calls") or []):
            fn = tc.get("function") or {}
            if str(fn.get("name", "")) not in _READ_TOOLS:
                continue
            args = fn.get("arguments")
            try:
                d = jsontext.loads(args) if isinstance(args, str) else (args or {})
            except (ValueError, TypeError, AttributeError):
                d = {}
            path = d.get("path") or d.get("file") or d.get("filename")
            if isinstance(path, str) and path.strip() and tc.get("id"):
                calls[tc["id"]] = path.strip()
        if m.get("role") == "tool" and m.get("tool_call_id") in calls:
            body = m.get("content")
            if isinstance(body, list):
                body = "".join(str(p.get("text", "")) for p in body if isinstance(p, dict))
            body = body if isinstance(body, str) else ""
            if body.strip() and not denial.is_denied(body):
                path = calls[m["tool_call_id"]]
                got[path] = max(got.get(path, 0), len(body))
    return sorted(got.items())


# The read-shaped tools by name. Shell reads (`cat`, `grep`) are deliberately NOT here: cria lowers
# its own file tools THROUGH shell, so a shell result cannot be attributed to a path without parsing
# the command line, and a wrong attribution would report a file as read that never was. Under-count,
# and say so, rather than guess (#5b).
_READ_TOOLS = ("read_file", "view_file", "open_file", "cat_file")


def fetch_succeeded(status) -> bool:
    """Did this ledger entry actually return something?

    ONE OWNER for the question, because the status has TWO spellings and reading only one of them
    silently disabled a whole guard. A ledger built from the live window carries the RENDERED
    ``"HTTP 200"``; a session's durable ledger can carry the bare int ``200``. `grounded_sources`
    tested ``startswith("2")``, which matches the bare int and NEVER matches ``"HTTP 200"`` — so
    every window-derived entry was invisible and the research exit answered NOT_DONE on a ledger
    full of parsed routes. Journal, every firing today: ``loop.research_check … sources=0``, while
    the same prompt carried ``api.handle.me/openapi.json → HTTP 200`` with ``resolved_addresses{ada}``
    parsed out of it. Scan for the code instead of matching a prefix; loop._fetch_succeeded delegates
    here so the two cannot drift apart again."""
    m = re.search(r"\d{3}", str(status if status is not None else ""))
    return bool(m) and 200 <= int(m.group(0)) < 300


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
        if fetch_succeeded(status) and (str(routes).strip() or str(shapes).strip()):
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


def authored_research_step(ask, task: str, *, domain: str = "", files: str = "") -> str:
    """ONE reading step for ``task``, written by the MODEL — "" when the task needs no reading.

    THE AUTHORSHIP IS THE POINT. cria may gather the facts; it may not decide what reading a task
    requires. The first version rendered this step from a cria template, which is cria writing plan
    steps — the practice this repo retired, and the operator's correction: the model authors it.

    AND THE MODEL DECIDES WHETHER THERE IS ONE. The version before this only asked when the task's
    own words contained a DOMAIN, which quietly defined research as a web thing. Research is reading,
    whatever the source: files already in the workspace, a schema on disk, a library's source, a data
    set, a tool's `--help`. A domain is a fact cria can establish alone, so it is passed as context
    when there is one — but the question is now "does this task need something read first?", and
    ``NONE`` is a first-class answer that yields no step.

    NO GUESSED LOCATIONS. The prompt forbids naming a path the task did not name, and this refuses an
    answer that names one anyway — unless the task named it too, in which case it is the user's own
    word and not a guess. That is the exact defect that cost run 1785804243 its whole window: its
    step said "by fetching the GitHub repo root directory", which returns denied, so the step could
    never be satisfied. A step naming WHAT to learn cannot be unsatisfiable that way; one naming
    WHERE can.

    A DEFECTIVE SENTENCE IS RE-ASKED ONCE, WITH THE DEFECT NAMED — the same courtesy every other
    refusal in this codebase already pays. A malformed tool call is re-prompted with the parse error;
    a missed edit is re-asked with the file's real text; this refusal used to just shrug, and on its
    first live outing that shrug cost the run its research entirely: fabliq restated the whole task
    ("Write a Python script that accepts an Ada Handle… includes unit tests… and adds a README"),
    cria refused it, and the run coded an invented API having read nothing. Observed rate before the
    retry: 2 usable steps in 4 asks. One retry, never more — a model that restates twice is answering
    from its defaults and a third ask is the same coin flip again.

    SAFE NULL, NOT A FALLBACK. NONE, an empty answer, or a retry that is still defective yields ""
    and the caller builds the plan it would have built anyway. cria never substitutes a sentence of
    its own."""
    context = []
    if domain:
        context.append(f"A SOURCE THE TASK NAMES: {domain}")
    if files:
        context.append(f"FILES ALREADY IN THE WORKING DIRECTORY:\n{files}")
    ctx_block = "\n\n".join(context)
    # WHICH QUESTION depends on what cria can prove. A domain in the task's own words is a FACT — the
    # task names an external source — so asking a small model to re-decide it invites the answer
    # fabliq gave on the first live run: NONE, for a task whose own sentence says "using the Ada
    # Handles API (api.handle.me)". cria settles what it can settle and asks only what it cannot
    # (#8). With no domain, whether anything must be read is a genuine judgement — files on disk, a
    # library's source, a data set — and the model makes it, NONE included.
    system = prompts.load("research_step_known" if domain else "research_step")
    text = " ".join((ask(system,
                     prompts.render("research_step_user", task=task, context=ctx_block))
                     or "").split())
    if not text or _is_none(text):
        return ""   # NONE is an ANSWER, not a defect; an empty reply leaves nothing to correct
    defect = step_defect(text, task, instruction=system)
    if defect is None:
        return text
    retry = " ".join((ask(system,
                      prompts.render("research_step_retry", task=task, context=ctx_block,
                                     answer=text, defect=defect))
                      or "").split())
    if not retry or _is_none(retry) or step_defect(retry, task, instruction=system) is not None:
        return ""
    return retry


def step_defect(text: str, task: str, instruction: str = "") -> str | None:
    """Why this sentence cannot be the reading step — a plain-words reason for the retry prompt to
    quote — or None when it can. Each reason is the lesson of a run that paid for it:

    * BUILD verb — fabliq, asked for a reading step, wrote back the entire task ("Write a Python
      script… includes unit tests… and adds a README"). As a first plan item that is strictly worse
      than none: two steps that both say "do the whole job". A reading step produces nothing.
    * a LOCATION the task never named — run 1785804243's step said "by fetching the GitHub repo root
      directory", which returns denied, so the step could never be satisfied and 114 of 195 calls
      died against it. A step naming WHAT to learn cannot be unsatisfiable that way; WHERE can.
    * over-LONG — a paragraph is the model writing the plan or the work, not one step.
    * THIRD-PERSON "the coder" — nemotron-nano run 1786243834 echoed the authoring instruction back
      as the step: "Read the external source … AND INSTRUCT THE CODER to identify …". The step is
      handed TO the coder; a sentence about the coder tells the executing model it is NOT the coder,
      and that run's coder spent 81 calls saying so ("it involves verifying the completion of a task
      created by another model") and wrote nothing. Measured over all 106 authored steps on disk:
      only the two echo steps contain the phrase.
    * the INSTRUCTION'S OWN CLOSING CLAUSE — the same echo carried "Output nothing else." into the
      step, an author-facing constraint that reads as a gag order to the coder executing it (that
      run's coder went silent for seven straight calls). The clause is derived from the live prompt
      text (`_instruction_tail`), so rewording the prompt file moves the matcher with it. Measured:
      3 echoes carry it, 0 of the 103 legitimate steps do.

    These are refusals of cria's OWN injected content, failing in the safe direction — no step, the
    plan cria would have built anyway (a defective first answer still gets its one named retry).
    Not a judgement about the coder's work, which is where a lexical rule would be out of place
    (#9); "the coder" and the closing clause are both cria's own strings, compared against cria's
    own prompt, and `tests/test_step_echo_defect.py` pins the sync so a prompt rename breaks loudly."""
    if len(text) > STEP_MAX_CHARS:
        return "it is far longer than one step"
    lowered, task_l = text.lower(), (task or "").lower()
    if re.search(r"(?i)\bthe coder\b", text):
        return ("it speaks about the coder in the third person — this sentence is handed TO the "
                "coder, who cannot execute an instruction addressed to someone else")
    tail = _instruction_tail(instruction)
    if tail and tail in " ".join(lowered.split()):
        return (f"it restates the planning instructions ('{tail}') instead of authoring a step — "
                "those words are addressed to the step's author, not to the coder")
    for token in _LOCATION_TOKENS:
        if token in lowered and token not in task_l:
            return ("it names a location the task itself never named, which the coder may be "
                    "unable to reach")
    for pat, what in _GUESS_SHAPES:
        m = pat.search(text)
        if m and m.group(0).lower() not in task_l:
            return (f"it bakes in {what} ('{m.group(0)}') that the task itself never named — a "
                    "guessed route or requirement becomes an instruction the coder cannot satisfy")
    if any(re.search(rf"\b{v}\b", lowered) for v in _PRODUCTION_VERBS):
        return ("it is a build instruction — its verb tells the coder to produce something "
                "rather than to read")
    return None


def _is_none(text: str) -> bool:
    return text.strip().upper().rstrip(".") == "NONE"


def _instruction_tail(instruction: str) -> str:
    """The closing clause of the authoring instruction, normalized for containment matching.

    By construction that clause is author-facing — both instruction prompts end on the output
    constraint ("…and output nothing else." / "Output only that sentence or NONE.") and neither
    ends on the step's content, which the instruction states mid-sentence. Deriving it from the
    live prompt text keeps the matcher and the prompt from drifting apart: reword the prompt and
    the matcher follows. Under 3 words → "" (no arm), so a radically restructured prompt fails
    toward not-matching rather than matching prose it never contained."""
    lines = [ln for ln in (instruction or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    norm = " ".join(lines[-1].lower().split())
    tail = re.split(r"[;,:]", norm)[-1].strip(" .")
    for lead in ("and ", "or "):
        if tail.startswith(lead):
            tail = tail[len(lead):]
    return tail if len(tail.split()) >= 3 else ""


# Verbs that make a sentence a BUILD instruction rather than a reading one. Refusing on these costs
# nothing when wrong: the plan simply has no reading step, exactly as before this feature existed.
_PRODUCTION_VERBS = ("write", "writes", "create", "creates", "add", "adds", "implement", "implements",
                     "build", "builds", "generate", "generates", "produce", "produces", "modify")


# Location-shaped tokens: naming one the TASK did not name is a guess, and a guessed location is what
# makes a step unsatisfiable. Present in the task too → the user named it, so it is a fact, not a guess.
_LOCATION_TOKENS = ("://", "openapi.json", "swagger", ".yml", ".yaml", ".json")

# The auth arm is shared with the STEER channel (loop._steer_auth_refuted): the same disease was
# walked there five runs later (1785866157 steer 0191 invented "your API key" and told the coder to
# keep a task-required live test mocked), so both channels trigger off ONE shape definition.
AUTH_SHAPE = re.compile(r"(?i)\b(?:authenticated|authentication|auth token|api[- ]?key|bearer token)\b")

# Guess SHAPES the token list above cannot see — same refusal contract (cria vetting its OWN
# authored step, fail-safe: no step = the plan cria would have built anyway), each arm silenced
# when the task's own text carries the match. Walked 2026-08-04, run
# ada-handles_gemma4_codex_poff_1785860144: the authored step read "the result of an AUTHENTICATED
# GET request to api.handle.me/v1/handles/{handle}" for a task naming only the bare domain — the
# run spent 38 of its 61 calls chasing the invented /v1/ route, a login endpoint that does not
# exist, and the auth scheme the step asserted.
_GUESS_SHAPES = (
    (re.compile(r"\{\w+\}"), "a braced path template"),
    (re.compile(r"/v\d+/"), "a versioned API path"),
    (AUTH_SHAPE, "an authentication requirement"),
)
