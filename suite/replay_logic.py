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

from cria import (execcheck, loop, massage, probegate, probeparse,  # noqa: E402
                  prompts, selfcompact, webfetch)

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


CHECKS = {
    "oscillation": check_oscillation,
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
