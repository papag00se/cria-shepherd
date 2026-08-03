#!/usr/bin/env python3
"""Replay captured runs through cria's DETERMINISTIC logic — no model calls, no GPU.

Every guard shipped this cycle has two halves: a deterministic part that decides WHEN it speaks, and
(sometimes) a model call that decides WHAT it says. The deterministic half is the part that can be
wrong in a way nobody notices, and it can be settled entirely from `~/.cria/calls` — the exact bytes
cria sent, already on disk.

That matters because the alternative is a 15-to-60-minute GPU run per question, and because two of
this cycle's fixes shipped without anyone checking they would ever fire. One did not (the
checks-reattach path never triggered in the run it was built for); one fired in 85% of prompts and
changed the failure mode rather than the outcome. Both facts were available offline.

    python3 suite/replay_logic.py                 # every check, every captured run
    python3 suite/replay_logic.py --check oscillation
    python3 suite/replay_logic.py --detail        # per-run rows, not just the base rate

This answers "would it have fired, and how often", never "would it have helped" — that still needs
a real run. Knowing a guard is silent is worth a GPU hour on its own.

A check may only MEASURE cria's logic, never restate it: every one below imports the real predicate
it is asking about (probegate.clean_gate_output, probeparse.is_advisory, loop.REPEAT_ACTION_CHARS,
loop._extract_fetches, massage.is_truncated) and anchors on cria's own prompt files rather than a
copy of their wording. A check that re-implements what it measures measures itself, and this repo
has shipped that mistake more than once.
"""
import argparse
import json
import os
import pathlib
import re
import sys

SUITE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(SUITE.parent))

from cria import (execcheck, jsontext, loop, massage, planner, probegate,  # noqa: E402
                  probeparse, prompts, selfcompact, webfetch)
from cria.jsontext import extract_json_object, strip_think  # noqa: E402

RESULTS = SUITE / "results" / "results.jsonl"
STEER_RE = re.compile(r"⟦ctx:steer⟧|GROUND TRUTH — the repo's own checks fail")
BULLET_RE = re.compile(r"•\s*(.+)")

# Where a rendered block ENDS in a captured prompt: the next piece of harness chat-template
# scaffolding. Every template in the corpus closes a tool result with one of these.
BLOCK_END_RE = re.compile(r"</tool_response>|<\|im_end\|>|<end_of_turn>|<\|\"\|>|<\|tool_response\|>|\n⟦ctx:")
# cria's ranged read answering "that line is past the end" — the exact printf in writeproxy.
PAST_EOF_RE = re.compile(
    r"\(no lines in that range — (.+?) has (\d+) lines; line (\d+) is past the end of the file\)")
# The spilled-doc outline, by the markers webfetch itself writes.
OUTLINE_MARKS = (webfetch.ROUTES_MARKER, webfetch.SHAPE_MARKER, webfetch.CATALOG_MARKER)
# The two messages that send the coder to a spilled file. Both have been reworded across the corpus,
# so the anchors are the phrases common to every version — never the current template verbatim.
SPILL_REFUSAL = "too large to inline"
SPILL_READ_STEER = "is a large reference document"


def coder_prompts(cap):
    """(path, rendered prompt text) for every coder call in a capture dir, in call order."""
    for f in sorted(cap.glob("*coder*.prompt.txt")):
        try:
            yield f, f.read_text(errors="replace")
        except OSError:
            continue


def request_messages(prompt_path):
    """The exact message list cria SENT on the call whose rendered prompt is ``prompt_path``."""
    body = prompt_path.with_name(prompt_path.name.replace(".prompt.txt", ".json"))
    try:
        return json.loads(body.read_text())["body"].get("messages") or []
    except (OSError, ValueError, KeyError, TypeError):
        return []


def replies(cap):
    """(response path, completion, the tool menu THAT call advertised) for every captured reply.

    The menu is read off the paired request body rather than assumed, because it is the thing that
    decides whether a name is an action at all — a plan-only planner call advertises one tool, a
    compaction advertises none, and a check that supplied its own menu would be measuring itself."""
    for f in sorted(cap.glob("*.response.json")):
        try:
            comp = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        req = f.with_name(f.name.replace(".response.json", ".json"))
        try:
            tools = (json.loads(req.read_text()).get("body") or {}).get("tools")
        except (OSError, ValueError, AttributeError, TypeError):
            tools = None
        yield f, comp, tools


def around(template, placeholder, width=40):
    """The literal text a prompt template puts immediately BEFORE and AFTER ``placeholder`` — so a
    check anchors on cria's own wording rather than a copy of it that goes stale the next time the
    template is edited."""
    left, right = prompts.load(template).split(placeholder)
    anchors = (left[-width:], right[:width])
    if any("{{" in a or "}}" in a for a in anchors):
        # A silent 0 is the one answer this harness must never give: it reads as "the guard never
        # fires" when it means "the anchor moved". Fail loudly instead.
        raise ValueError(f"{template}: no literal anchor around {placeholder} — widen or re-anchor")
    return anchors


def runs():
    """(row, capture_dir, workspace) for every recorded run whose evidence still exists."""
    if not RESULTS.exists():
        return []
    out = []
    for line in RESULTS.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            continue
        cap = pathlib.Path(str(r.get("capture_dir") or ""))
        ws = pathlib.Path(str(r.get("archive") or "")) / "workspace"
        if cap.is_dir():
            out.append((r, cap, ws if ws.is_dir() else None))
    return out


def _signatures(cap):
    """The gate finding-states a run went through, in order, deduped consecutively."""
    states = []
    for f in sorted(cap.glob("*coder*.prompt.txt")):
        try:
            t = f.read_text(errors="replace")
        except OSError:
            continue
        bullets = BULLET_RE.findall(t)
        if not bullets:
            continue
        sig = tuple(sorted({b.strip()[:70] for b in bullets[-6:]}))
        if not states or states[-1] != sig:
            states.append(sig)
    return states


def check_oscillation(row, cap, ws):
    """Would loop's A-B-A detector have fired? Mirrors its exact condition."""
    prior, fires = [], 0
    for sig in _signatures(cap):
        if sig in prior and prior[-1] != sig:
            fires += 1
        if not prior or prior[-1] != sig:
            prior.append(sig)
            del prior[:-loop.GATE_SIGNATURE_WINDOW]
    return fires, f"{len(set(_signatures(cap)))} distinct finding-states"


def check_reattach(row, cap, ws):
    """How often the reattach fix would ACTUALLY fire — not how big its pool is.

    The first version of this check counted prompts carrying no correction, which is the population,
    not the trigger, and reported 97% for a fix whose real rate is far lower. The trigger is BOTH
    conditions together: the gate's findings are UNCHANGED since the last steer (so the old guard
    would have suppressed), AND the checker's own first line is absent from the request (so nothing
    else is carrying it). Mirrors loop._checks_already_visible exactly.
    """
    fires = 0
    last_steered = None
    for f in sorted(cap.glob("*coder*.prompt.txt")):
        try:
            t = f.read_text(errors="replace")
        except OSError:
            continue
        bullets = BULLET_RE.findall(t)
        if not bullets:
            continue
        checks = "\n".join(b.strip() for b in bullets[-6:])
        if checks == last_steered:                      # the old guard would suppress here
            first = bullets[-len(bullets)].strip().lstrip("•").strip()[:80]
            body_wo_steer = STEER_RE.split(t)[0]        # what the prompt carries APART from the steer
            if first and first not in body_wo_steer:    # ...and nothing else carries the finding
                fires += 1
        last_steered = checks
    return fires, "findings unchanged AND not otherwise visible"


def check_step_reframe(row, cap, ws):
    """How many prompts would have carried the 'it already exists, repair it' note.

    Deterministic on two facts cria already holds: the step names a file that is on disk, and the
    gate is red. Replayed here against the FINAL workspace, so it is an upper bound for a run whose
    files appeared late — stated rather than hidden.
    """
    if ws is None:
        return 0, "no archived workspace"
    fires = 0
    for f in sorted(cap.glob("*coder*.prompt.txt")):
        try:
            t = f.read_text(errors="replace")
        except OSError:
            continue
        m = re.search(r"Do ONLY this step \(\d+ of \d+\), then stop:\s*\n\s*(.+?)\n", t, re.S)
        if not m:
            continue
        if loop.step_artifacts_on_disk(m.group(1), str(ws)) and STEER_RE.search(t):
            fires += 1
    return fires, "step named an existing file while the gate was red"


def check_satisfaction_due(row, cap, ws):
    """How many periodic 'is the task done?' checks were DUE — and how many actually ran.

    The gap is the bug this cycle found: the check existed, was configured, and lived on the wrong
    driver, so a planner-ON run could sit finished for its whole budget.
    """
    drives = len(list(cap.glob("*coder*.response.json")))
    due = sum(1 for n in range(1, drives + 1) if loop.satisfaction_check_due(n, 80, 20))
    ran = len(list(cap.glob("*satisfaction*.response.json")))
    return max(due - ran, 0), f"{due} due, {ran} ran, over {drives} coder turns"


def check_execcheck(row, cap, ws):
    """What the live-execution check would have concluded from the workspace alone."""
    if ws is None:
        return 0, "no archived workspace"
    eps = execcheck.entrypoints(str(ws))
    rc = execcheck.readme_commands(str(ws))
    if not eps:
        return 1, "NO entry point — would report inconclusive"
    if not rc:
        return 1, f"entry point {eps[0]} but README documents no run command"
    return 0, f"corroborated: {eps[0]}"


def check_spill_outline(row, cap, ws):
    """How many coder calls were sent to a spilled file that cria described by FILENAME ONLY.

    The refusal ("you already fetched this, it is saved to <file>") and the spill-file read steer
    both say "go grep it". That is a riddle when the coder does not yet know what to grep FOR, and
    cria is holding the parsed document the whole time — :func:`webfetch.outline_for_url` is the fix
    that makes the refusal carry the doc's routes/keys.

    The cache that function reads is a LIVE object, so what is replayable from disk is the other
    half of the same fact: the prompt carried the refusal and carried no outline anywhere. Gated on
    the run having emitted an outline for that document at least once — that is what proves cria
    HELD one to include. Counted per prompt, matching how the original 2,074/981 measurement was
    taken (a refusal sits in the conversation for every later call, so this is context presence, not
    distinct refusals)."""
    fires = carried = with_outline = 0
    for _f, t in coder_prompts(cap):
        if SPILL_REFUSAL not in t and SPILL_READ_STEER not in t:
            continue
        carried += 1
        if any(m in t for m in OUTLINE_MARKS):
            with_outline += 1
        else:
            fires += 1
    if not with_outline:            # never saw one → cannot claim cria held one to include
        return 0, f"{carried} prompts carried a spill refusal, no outline ever built for this run"
    return fires, f"{carried} prompts carried a spill refusal/read steer, {with_outline} with an outline"


def check_repeat_body(row, cap, ws):
    """How many repetition redirects quoted back MORE than loop.REPEAT_ACTION_CHARS of the action.

    Unbounded, that quote carried the whole file body cria was telling the model to stop producing —
    "Choose a DIFFERENT next action" with 3.2 KB of the file attached, which the coder satisfied
    literally: same bytes, new filename. Deduped per run on the quoted text, since the redirect stays
    in the conversation for every later call."""
    pre, post = around("redirect_canned", "{{REPEAT_ACTION}}")
    rx = re.compile(re.escape(pre) + r"(.*?)" + re.escape(post[:30]), re.S)
    seen, over = set(), set()
    for _f, t in coder_prompts(cap):
        for m in rx.finditer(t):
            action = m.group(1)
            seen.add(action)
            if len(action) > loop.REPEAT_ACTION_CHARS:
                over.add(action)
    longest = max((len(a) for a in seen), default=0)
    return len(over), f"{len(seen)} distinct redirects, longest quoted action {longest} chars"


def _gate_findings(clean):
    """The finding LINES of a ⟦ctx:checks⟧ error-class payload (its header is one line)."""
    return clean.split("\n")[1:]


def _flattened(lines):
    """What the pre-fix cleaner shipped: every line stripped, then globally deduped."""
    out, seen = [], set()
    for ln in lines:
        s = ln.strip()
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def check_gate_verbatim(row, cap, ws):
    """How many gate results shipped DE-INDENTED and DE-DUPLICATED source lines to the coder.

    The captures hold raw checker output (the ``___CRIA_GATE_`` sections, as forwarded on the proxy
    path), so the current :func:`probegate.clean_gate_output` can be run over the very bytes cria
    read. A fire needs both halves: the current cleaner keeps indentation or a repeated line that
    flattening would destroy, AND the FLATTENED form is the one found in this run's coder prompts —
    i.e. what actually shipped was the damaged copy. That is how a pytest traceback lost the closing
    brace of the code it quoted and cria then invented a syntax error that the same gate's
    compileall had just exited 0 on."""
    seen_raw, fires, changed = set(), 0, 0
    texts = None
    for f in sorted(cap.glob("*proxy.json")):
        try:
            blob = f.read_text(errors="replace")
        except OSError:
            continue
        if probegate.SECTION_PREFIX not in blob:
            continue
        try:
            body = json.loads(blob)["body"]
        except (ValueError, KeyError, TypeError):
            continue
        for m in body.get("messages") or []:
            c = m.get("content")
            if isinstance(c, list):
                c = " ".join(str(x.get("text", "")) for x in c if isinstance(x, dict))
            if not isinstance(c, str) or probegate.SECTION_PREFIX not in c or c in seen_raw:
                continue
            seen_raw.add(c)
            clean = probegate.clean_gate_output(c)
            if not clean or "error-class problems" not in clean.split("\n")[0]:
                continue
            lines = _gate_findings(clean)
            flat = _flattened(lines)
            if flat == lines:
                continue
            changed += 1
            if texts is None:
                texts = [t for _f, t in coder_prompts(cap)]
            if any("\n".join(flat) in t for t in texts):
                fires += 1
    return fires, f"{len(seen_raw)} raw gate results, {changed} whose real lines flattening would alter"


def check_advisory_gate(row, cap, ws):
    """How many findings cria shipped as error-class problems that is_advisory now suppresses.

    ``redefinition of unused …`` and ``f-string is missing placeholders`` are style notes. Shipped
    under "the repo's own checks report these error-class problems", they sent the coder to edit
    working code — and they persisted, unchanged, for as long as the style stayed. Reads the block
    cria actually shipped and applies the CURRENT predicate (both forms probegate uses: the whole
    line, and the line with its ``file:line:col:`` prefix removed). Deduped per run on the finding
    text; the same block is re-rendered into every later prompt."""
    head = probegate.CHECKS_MARKER + " the repo's own checks report"
    suppressed, shipped = set(), set()
    for _f, t in coder_prompts(cap):
        for m in re.finditer(re.escape(head), t):
            nl = t.find("\n", m.end())
            if nl < 0:
                continue
            end = BLOCK_END_RE.search(t, nl)
            for ln in t[nl + 1:end.start() if end else len(t)].split("\n"):
                s = ln.strip()
                if not s:
                    continue
                shipped.add(s)
                if probeparse.is_advisory(s) or probeparse.is_advisory(probegate._LOC_PREFIX.sub("", s)):
                    suppressed.add(s)
    return len(suppressed), f"{len(shipped)} distinct lines shipped as error-class"


def check_missing_file_read(row, cap, ws):
    """How many ranged reads answered "has 0 lines … past the end of the file" for a path that is
    NOT on disk — cria describing a file that does not exist as an empty one.

    The unranged read of the same path says "No such file or directory", so cria held the true
    answer and served the false one; the coder's own reasoning recorded the damage ("the file was
    empty or couldn't be found"). Existence is judged against the ARCHIVED (final) workspace, so a
    path created later reads as present — an under-count, stated rather than hidden. Deduped per run
    on the answer text, since the tool result stays in the conversation."""
    if ws is None:
        return 0, "no archived workspace"
    root = str(row.get("workspace") or "")
    absent, zero = set(), set()
    for _f, t in coder_prompts(cap):
        for m in PAST_EOF_RE.finditer(t):
            path, n_lines = m.group(1), int(m.group(2))
            if n_lines:
                continue                # a real file, really read past its end
            zero.add(m.group(0))
            rel = path[len(root):] if root and path.startswith(root) else path
            rel = rel.lstrip("./").lstrip("/")
            if rel and not os.path.isabs(rel) and not (ws / rel).exists():
                absent.add(m.group(0))
    return len(absent), f"{len(zero)} distinct zero-line answers"


def check_steer_truncated(row, cap, ws):
    """How many steers were authored by a completion the model never finished.

    A cut reply is not a directive: the author hit the output cap and cria delivered the fragment to
    the coder anyway, in cria's own voice, under a prompt that asked for "a SHORT directive (under
    120 words)" — 27,000 characters of the coder's own pytest failures repeated back at it. The
    authoring call is identified by the steer_diagnose USER prompt (cria's own file), and truncation
    by :func:`massage.is_truncated` — the same predicate the fix calls."""
    anchor = prompts.load("steer_diagnose_user").splitlines()[0]
    authored = cut = 0
    for f in sorted(cap.glob("*.prompt.txt")):
        if "reasoner" not in f.name and "steer" not in f.name:
            continue
        try:
            if anchor not in f.read_text(errors="replace"):
                continue
        except OSError:
            continue
        authored += 1
        resp = f.with_name(f.name.replace(".prompt.txt", ".response.json"))
        try:
            comp = json.loads(resp.read_text())
        except (OSError, ValueError):
            continue
        if massage.is_truncated(comp):
            cut += 1
    return cut, f"{authored} steer-authoring calls"


def check_facts_anchor_absent(row, cap, ws):
    """How many coder prompts of a planner-OFF run went out with NO ⟦ctx:facts⟧ ledger while cria
    held real fetch results.

    The durable fetch ledger was wired into the plan-ON driver only, which is how every dense model
    on the ladder runs. So the coder lost the endpoints and response shapes it had already fetched
    the moment the harness compacted them away, while the reasoner kept being handed them. The
    ledger is rebuilt here with cria's own :func:`loop._extract_fetches` over the exact messages the
    capture recorded; the count is the prompts from the first one carrying a fetch onward."""
    if (row.get("planner") or "").lower() != "off":
        return 0, "planner ON — this path always had the anchor"
    pages = list(coder_prompts(cap))
    if any(selfcompact.FACTS_MARKER in t for _f, t in pages):
        return 0, "anchor present"
    for i, (f, _t) in enumerate(pages):
        ledger = loop._extract_fetches(request_messages(f))
        if ledger:
            return len(pages) - i, f"{len(ledger)} fetched urls, 0 of {len(pages)} prompts carried the anchor"
    return 0, "no fetches — an empty ledger injects nothing"


def _final_replies(cap):
    """(response path, finish_reason, the reply's text) for every captured call of a run.

    Reads the RESPONSE files, which is where a finish reason exists at all — the two checks below
    both turn on it, and a reply cut at the output cap is the one thing neither recovery may touch."""
    for f in sorted(cap.glob("*.response.json")):
        try:
            j = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        ch = (j.get("choices") or [{}])[0]
        msg = ch.get("message") or {}
        c = msg.get("content")
        if isinstance(c, list):
            c = "".join(str(p.get("text", "")) for p in c if isinstance(p, dict))
        yield f, ch.get("finish_reason"), c if isinstance(c, str) else ""


# The verdict key each judge phase answers under — cria's own three flags, keyed on the phase name
# the capture file carries. The `-noreason` suffix is covered by the prefix match below.
_VERDICT_FLAGS = (("critic-confirm", "consistent"), ("satisfaction", "satisfied"),
                  ("critic", "done"))


def check_unclosed_verdict(row, cap, ws):
    """How many judge verdicts cria threw away over an absent closing brace — and how many of those
    the one-way gate actually recovers.

    Both halves are cria's own code, never a copy of it: ``extract_json_object`` decides
    "unreadable", ``jsontext.close_unclosed_object`` decides "repairable by closers alone", and
    ``loop.verdict_from_unclosed`` decides which way it may rule. A repaired APPROVAL is counted in
    the population and NOT in the fires — that is the direction, measured rather than asserted.

    ``finish_reason: length`` never enters either half. A cut generation is refused at every call
    site before the reader is reached, so counting it here would report a fix that cannot fire."""
    repairable = fires = approvals = cut = 0
    for f, finish, text in _final_replies(cap):
        phase = f.name.split("-", 1)[-1].replace(".response.json", "")
        flag = next((v for k, v in _VERDICT_FLAGS if phase.startswith(k)), "")
        if not flag or not text.strip() or extract_json_object(text) is not None:
            continue
        obj = jsontext.close_unclosed_object(text)
        if not isinstance(obj, dict) or flag not in obj:
            continue
        if finish == "length":
            cut += 1
            continue
        repairable += 1
        if obj[flag] is False:
            fires += 1
        else:
            approvals += 1
    why = f"{repairable} unreadable judge replies a closer alone repairs"
    if approvals:
        why += f", {approvals} of them an APPROVAL the one-way gate refuses"
    if cut:
        why += f", {cut} more cut at the cap and refused before the reader"
    return fires, why


def check_replan_json_shape(row, cap, ws):
    """How many living re-derivations cria read as NOTHING while the reasoner had answered.

    The population is every call whose SYSTEM prompt is cria's own ``replan`` template — anchored on
    the template's own literal text via :func:`around`, so a reworded prompt fails loudly rather than
    quietly measuring zero. A fire is a reply the OLD shape test rejected (a dict with a non-empty
    literal ``steps`` list) that ``planner.json_steps`` — the reader cria already owned — reads.

    An EMPTY answer counts as a fire and is named separately in the reason. cria's ``replan.txt``
    asks for exactly ``[]`` when nothing remains, and the old shape test could not tell it from a
    parse miss — so it is a behaviour change of its own (the caller now re-asks judge_satisfaction
    instead of carrying a stale tail), and folding it into the silent half would be the under-count
    :func:`around` exists to refuse."""
    left, right = around("replan", "{{TRIGGER}}")
    replies = {p.name: t for p, _fin, t in _final_replies(cap)}
    fires = empties = misses = 0
    for f in sorted(cap.glob("*.json")):
        if f.name.endswith(".response.json"):
            continue
        try:
            body = json.loads(f.read_text())["body"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        msgs = body.get("messages") or []
        syst = str((msgs[0] if msgs else {}).get("content") or "")
        if left not in syst or right not in syst:
            continue
        text = replies.get(f.name.replace(".json", ".response.json"), "")
        obj = extract_json_object(strip_think(text))
        if isinstance(obj, dict) and isinstance(obj.get("steps"), list) and obj["steps"]:
            continue                    # the old shape test read this one
        got = planner.json_steps(strip_think(text))
        if got is None:
            misses += 1
        elif got:
            fires += 1
        else:
            empties += 1
    return fires + empties, (f"{fires} re-derivations the old shape test dropped, {empties} that "
                             f"answered 'nothing remains', {misses} genuinely unreadable")


# ---------------------------------------------------------------------------------------------
# A REFUSED CALL LOGGED AS A TOOL'S ANSWER.

# The refusal templates cria authors, by prompt key — the population, read from cria's own prompt
# files at replay time and never copied here. The mark that identifies a refusal at RUNTIME
# (cria.denial) cannot be replayed onto captures written before it existed, so this check anchors on
# the templates instead. That is the only half it re-derives, and it is bounded: the anchor for each
# key must be a literal span that appears in NO other template, so a closing sentence two templates
# share — `spill` (a fetch that DID run) and `fetch_repeat_spilled` (one that did not) end with the
# same paragraph — can never be counted as the wrong one. The LABELLING mechanism is not replayed at
# all; tests/test_denied_calls.py owns that.
_REFUSAL_PROMPTS = ("malformed_call_refusal", "cria_home_refusal", "external_path_refusal",
                    "external_install_refusal", "spill_read_steer", "spill_edit_refusal",
                    "edit_missing_new_string", "large_read_steer", "large_range_steer",
                    "write_refused", "search_read_denied",
                    "webfetch_guards:search_repeat", "webfetch_guards:search_repeat_inline",
                    "webfetch_guards:fetch_repeat", "webfetch_guards:fetch_repeat_failed",
                    "webfetch_guards:fetch_repeat_spilled")
_PLACEHOLDER = re.compile(r"\{\{[A-Z_]+\}\}|%%[A-Z_]+%%")
_LOG_RESULT = re.compile(r"^  -> ", re.M)
_LOG_CALL = re.compile(r"^\$ \S", re.M)


def _all_prompt_fragments():
    """Every prompt template on disk, keyed ``name`` or ``name:entry`` for the load_map files."""
    out = {}
    for p in sorted((pathlib.Path(loop.__file__).parent / "prompts").glob("*.txt")):
        raw = p.read_text(encoding="utf-8")
        out[p.stem] = raw
        if re.search(r"^[a-z_]+ = ", raw, re.M):
            for k, v in prompts.load_map(p.stem).items():
                out[f"{p.stem}:{k}"] = v
    return out


def _unique_anchors():
    """key -> the longest literal span of that template found in no OTHER template."""
    frags = _all_prompt_fragments()
    anchors = {}
    for key in _REFUSAL_PROMPTS:
        if key not in frags:
            raise ValueError(f"replay_logic: prompt {key} is gone — re-anchor rather than measure 0")
        others = [v for k, v in frags.items()
                  if k != key and not k.startswith(key + ":") and not key.startswith(k + ":")]
        best = ""
        for run in sorted((s.strip() for s in _PLACEHOLDER.split(frags[key])), key=len, reverse=True):
            for width in (120, 90, 70, 50, 35):
                cand = run[:width]
                if len(cand) >= 30 and not any(cand in o for o in others):
                    best = cand if len(cand) > len(best) else best
                    break
            if best:
                break
        if not best:
            raise ValueError(f"replay_logic: no unique anchor for {key} — widen or re-anchor")
        anchors[key] = best
    return anchors


def _result_bodies(text):
    """Each ``  -> `` result body in a rendered action log, up to the next call or result line."""
    starts = [m.start() for m in _LOG_RESULT.finditer(text)]
    bounds = sorted(set(starts) | {m.start() for m in _LOG_CALL.finditer(text)} | {len(text)})
    for s in starts:
        yield text[s + 5:next(b for b in bounds if b > s)]


def check_denied_call_logged(row, cap, ws):
    """How many JUDGE prompts were told a call cria REFUSED was what the coder's tool returned.

    ``loop._work_log`` renders a refusal as ``  -> <text>``, byte-identical to a real result, while
    ``prompts/verify.txt`` tells the critic in cria's own voice that "each ``-> ...`` line is what it
    returned". A fire is one judge prompt whose action log carries at least one refusal body.

    The reason line names the refusal COUNT separately from the prompt count, because one prompt
    routinely carries several and collapsing them would understate the evidence a judge was reading."""
    anchors = _unique_anchors()
    prompts_hit = bodies = total = 0
    for f in sorted(cap.glob("*.prompt.txt")):
        phase = f.name.split("-", 1)[-1].replace(".prompt.txt", "")
        if not phase.startswith(("critic", "satisfaction", "compactor")):
            continue
        try:
            t = f.read_text(errors="replace")
        except OSError:
            continue
        found = False
        for b in _result_bodies(t):
            total += 1
            if any(a in b for a in anchors.values()):
                bodies += 1
                found = True
        prompts_hit += bool(found)
    return prompts_hit, (f"{bodies} of {total} `-> ` result bodies in this run's judge prompts are "
                         f"a refusal cria authored")


def check_denied_call_deleted(row, cap, ws):
    """How many coder turns the work log left with a ``$`` call line and NO result line at all.

    Driven through cria's OWN ``loop._work_log`` over the captured message list — nothing here
    re-implements it. The deleted result is the search-read denial, which ``_is_cria_scaffolding``
    used to strip: that removes the RESULT and keeps the CALL, so a judge sees a read that appears to
    have returned nothing about a file still on disk. Arguably worse than the mislabel above, and the
    reason the note is labelled now rather than deleted."""
    turns = holes = 0
    for f in sorted(cap.glob("*.json")):
        if f.name.endswith(".response.json") or "coder" not in f.name:
            continue
        try:
            msgs = json.loads(f.read_text())["body"].get("messages") or []
        except (OSError, ValueError, KeyError, TypeError):
            continue
        lines = loop._work_log(msgs).splitlines()
        n = sum(1 for i, ln in enumerate(lines)
                if ln.startswith("$ ") and not (lines[i + 1:i + 2] or [""])[0].startswith("  -> "))
        if n:
            turns += 1
            holes += n
    return turns, f"{holes} call lines with no result line, over this run's coder turns"


def check_repeated_verdict_key(row, cap, ws):
    """How many model replies repeat a key whose FIRST value is a real answer cria was discarding.

    ``jsontext._first_wins`` resolved a repeated key to its first NON-EMPTY value using Python
    truthiness, so a JSON ``false`` read as nothing-said and a later ``true`` replaced it. Both
    readings are driven here — ``jsontext.loads`` against the stdlib's last-wins — so this measures
    the parser, never a copy of it. A fire is a reply where the two now disagree AND the key is one
    cria acts on.

    IT REPORTS 0/86 TODAY, AND THAT IS A POPULATION FACT, NOT A RATE. This harness's population is
    the runs recorded in ``suite/results/results.jsonl``; ``~/.cria/calls`` holds more session
    directories than that (127 vs 86 at the time of writing), including the run that motivated the
    fix — 20260803T112245 call 0157-critic, a step critic that wrote ``"done": false`` and then
    ``"done": true`` in the same object and was read as an APPROVAL. Scanning every captured payload
    on the box directly: 24,196 texts, 73 repeated keys, 4 with a falsy-but-real first value, of
    which that one is the only key cria acts on. The check stays here so the number moves on its own
    once the row lands."""
    fires = other = 0
    for _f, _fin, text in _final_replies(cap):
        for span in _object_spans(text):
            try:
                mine = jsontext.loads(span)
                theirs = json.loads(span)
            except ValueError:
                continue
            if mine == theirs:
                continue
            keys = [k for k in mine if mine.get(k) != theirs.get(k)]
            if any(k in ("done", "satisfied", "consistent", "steps", "missing") for k in keys):
                fires += 1
            else:
                other += 1
    return fires, f"{other} more disagree on a key cria does not read"


def _object_spans(text):
    """Every brace-balanced object span in ``text`` — the same spans cria's own reader scans."""
    i = (text or "").find("{")
    while i != -1:
        depth, in_str, esc = 0, False, False
        for j in range(i, len(text)):
            c = text[j]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    yield text[i:j + 1]
                    break
        i = text.find("{", i + 1)
_REASONING_DEBRIS = ("<|tool_call_start|>", "<|tool_call_end|>", "<tool_call>", "</tool_call>",
                     "<function=", "</function>", "<|tool_call>")


def check_reasoning_tool_call(row, cap, ws):
    """How many replies came back LOST — no text, no tool_calls — while holding a tool call in
    ``reasoning_content``, the one channel llama.cpp's parser never reads.

    The number reported is what cria RECOVERS, produced by running the real predicate
    (:func:`massage.recover_reasoning_tool_calls`) over the captured completion with the tool menu
    that call actually advertised. Nothing here re-implements the parser or its gates; the checker
    only counts what cria's own function did.

    The "why" carries the denominator, the REFUSALS, and the count of recoveries that REPEAT one
    already made in the same run. That last number is the one to watch: it is not a cost of the
    recovery but a measure of how long the loop stayed stuck, and it should FALL as the guards that
    can only see forwarded calls start seeing them."""
    recovered = refused = lost = repeats = 0
    seen = set()
    for _f, comp, tools in replies(cap):
        msg = ((comp.get("choices") or [{}])[0].get("message")) or {}
        rc = msg.get("reasoning_content") or msg.get("reasoning") or ""
        if not isinstance(rc, str) or not any(d in rc for d in _REASONING_DEBRIS):
            continue
        if msg.get("tool_calls") or massage.content_text(msg.get("content")).strip():
            continue                      # not a lost turn — the call or an answer came through
        lost += 1
        after = massage.recover_reasoning_tool_calls(json.loads(json.dumps(comp)), tools, None)
        tcs = ((after.get("choices") or [{}])[0].get("message") or {}).get("tool_calls")
        if not tcs:
            refused += 1
            continue
        recovered += 1
        fp = tuple((tc["function"]["name"], tc["function"]["arguments"]) for tc in tcs)
        if fp in seen:
            repeats += 1
        seen.add(fp)
    return recovered, (f"{lost} lost reply(s) whose reasoning carried tool-call dialect; "
                       f"{refused} refused (no complete call, or off this call's menu); "
                       f"{repeats} recovery(ies) repeated an earlier one in this run")


def check_call_syntax_tool_call(row, cap, ws):
    """How many replies came back with a tool call written in `content` as CALL SYNTAX —
    ``edit_file({"path": …})`` — and no tool call anywhere cria could see.

    The number reported is what cria RECOVERS, produced by running the real entry point
    (:func:`massage.recover_leaked_tool_calls`) over the captured completion with the tool menu that
    call actually advertised. Nothing here re-implements the parser or its gates; the checker only
    counts what cria's own function did, and reads the tools off the paired request body — a check
    that supplied its own menu would be measuring itself.

    The "why" carries the REFUSALS separately, because they are the half that must not drift. A
    reply cut at the output cap is refused outright: one 123 KB truncated reply in this corpus parses
    into 252 `edit_file` calls, and forwarding a runaway generation is the failure this recovery must
    never become. The population line is the denominator — replies that were lost with a JSON object
    sitting in their content — so a rate can be read off it rather than guessed at."""
    recovered = refused_cut = lost = calls = 0
    for f, comp, tools in replies(cap):
        choice = (comp.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        if msg.get("tool_calls"):
            continue
        text = massage.content_text(msg.get("content"))
        if not text.strip() or extract_json_object(text) is None:
            continue
        lost += 1
        got, _left = massage._call_syntax_calls(text, tools)
        if not got:
            continue
        if choice.get("finish_reason") == "length":
            refused_cut += 1
            continue
        after = massage.recover_leaked_tool_calls(json.loads(json.dumps(comp)), tools, None)
        tcs = ((after.get("choices") or [{}])[0].get("message") or {}).get("tool_calls")
        if tcs:
            recovered += 1
            calls += len(tcs)
    return recovered, (f"{lost} lost reply(s) holding a JSON object; {calls} call(s) recovered; "
                       f"{refused_cut} refused (the reply was cut at the output cap)")


CHECKS = {
    "oscillation": check_oscillation,
    "call-syntax-tool-call": check_call_syntax_tool_call,
    "unclosed-verdict": check_unclosed_verdict,
    "replan-json-shape": check_replan_json_shape,
    "denied-call-logged": check_denied_call_logged,
    "denied-call-deleted": check_denied_call_deleted,
    "repeated-verdict-key": check_repeated_verdict_key,
    "reasoning-tool-call": check_reasoning_tool_call,
    "reattach": check_reattach,
    "step-reframe": check_step_reframe,
    "satisfaction": check_satisfaction_due,
    "execcheck": check_execcheck,
    "spill-outline": check_spill_outline,
    "repeat-body": check_repeat_body,
    "gate-verbatim": check_gate_verbatim,
    "advisory-gate": check_advisory_gate,
    "missing-file-read": check_missing_file_read,
    "steer-truncated": check_steer_truncated,
    "facts-anchor-absent": check_facts_anchor_absent,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", choices=sorted(CHECKS), action="append")
    ap.add_argument("--detail", action="store_true")
    args = ap.parse_args()
    wanted = args.check or sorted(CHECKS)

    data = runs()
    print(f"replaying {len(data)} captured runs through cria's deterministic logic "
          f"— no model calls\n")
    for name in wanted:
        fn = CHECKS[name]
        fired = 0
        rows = []
        for row, cap, ws in data:
            try:
                n, why = fn(row, cap, ws)
            except Exception as e:  # noqa: BLE001
                n, why = 0, f"replay error: {type(e).__name__}"
            if n:
                fired += 1
            rows.append((row.get("model", "?"), row.get("score"), n, why))
        pct = 100 * fired / max(len(data), 1)
        print(f"── {name}: would fire on {fired}/{len(data)} runs ({pct:.0f}%)")
        if args.detail:
            for model, score, n, why in rows:
                if n:
                    sc = f"{score:.0f}/4" if score is not None else "—"
                    print(f"     {model:17s} {sc:>5s}  x{n:<3d} {why}")
        print()


if __name__ == "__main__":
    main()
