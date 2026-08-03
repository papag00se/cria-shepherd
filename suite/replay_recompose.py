#!/usr/bin/env python3
"""Recompose a captured prompt through cria's CURRENT code and ask the model BOTH versions.

The two existing harnesses each answer half a question and neither answers this one:

    suite/replay_logic.py   captured calls through cria's deterministic logic, no model.
                            "Would the guard fire?" — never "did it help".
    suite/replay.py         captured bodies sent to the model unchanged, under a settings matrix.
                            "Do these sampling knobs help?" — it replays the OLD prompt, so a fix
                            that changes what the model READS is invisible to it.

Every fix in this cycle changes what the model reads. This harness takes a captured call's ORIGINAL
INPUTS — the raw checker output, the spilled document, the repeated action, the read_file arguments —
runs them through the composition function cria uses TODAY, splices the new text into the exact body
that was sent, and asks the model both — each twice, at the captured call's own sampling, because a
weak model moves on its own and one reply per side cannot tell that apart from the change. Then it
prints the lot, with the reply the model gave at capture time, for a human to read.

    python3 suite/replay_recompose.py --fix repeat-body --n 2 --detail
    python3 suite/replay_recompose.py --fix gate-verbatim --dry-run     # build cases, no model

WHAT THIS DELIBERATELY DOES NOT DO — it does not score which reply is better. There is no metric here
that decides an improvement. This repo has been burned repeatedly by scorers that ended up measuring
themselves (principle 23b's table of five consecutive wrong measurements; a base-rate scorer earlier
today reported 0 of 125 because it matched the wrong label). What it prints instead is: the two
prompts diffed, the two replies in full, and a handful of cheap DETERMINISTIC FACTS about each reply —
did it call the same tool, did it name the same path, is it byte-identical, would this edit's
old_string actually be found in the file on disk. A fact is checkable; a verdict is not. The verdict
is yours, after reading.

RECOMPOSITION IS THROUGH THE REAL CODE. Every ``new`` string below comes out of the function cria
calls in production — ``webfetch.fetch_nav``, ``prompts.render("redirect_canned", …)``,
``probegate.clean_gate_output``, ``writeproxy.translate_outbound`` — driven on inputs read off disk.
Where a fix's effect cannot be reproduced that way the case is SKIPPED with its reason printed, never
approximated: an approximated prompt measures the approximation.

Read-only: no workspace is touched (the archived copies are read, and cwd is restored), no result is
fed back into a run, nothing is restarted. Model calls go DIRECTLY to the model server, like
replay.py, so nothing here depends on cria's routing.
"""
import argparse
import difflib
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field

SUITE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(SUITE.parent))
sys.path.insert(0, str(SUITE))

import replay_logic  # noqa: E402 — sibling harness: ONE owner for "which runs have evidence"
from cria import (loop, probegate, probeparse, prompts, shelltool,  # noqa: E402
                  webfetch, writeproxy)

BASE = "http://127.0.0.1:18084"
CHAT = f"{BASE}/v1/chat/completions"
MODELS = f"{BASE}/v1/models"
REQUEST_TIMEOUT_S = 900
# Sampling knobs a captured body may or may not carry. When it carries them they are used as-is (the
# call's OWN settings — this harness asks about the PROMPT, so the settings must not also vary);
# when it carries none, temperature 0.
_SAMPLING = ("temperature", "top_p", "top_k", "min_p", "repeat_penalty", "presence_penalty",
             "frequency_penalty", "seed")
_PATH_ARGS = ("path", "file_path", "filename", "target_file", "url")

# Why a run yielded no case. A recomposer that cannot reach a fix's inputs SAYS SO — a silent zero
# reads as "the fix never applies" when it means "the evidence is not on disk", and that is the one
# answer this harness must never give (replay_logic.around's rule, applied to a whole recomposer).
NOTES: list = []


# ---------------------------------------------------------------------------------------------
# a case: one captured call, the text as SHIPPED, and the text cria's current code composes


@dataclass
class Case:
    fix: str
    call: pathlib.Path            # the captured request body (…/NNNN-coder-s1.json)
    model: str                    # the model the capture ran against
    body: dict                    # the exact body cria sent
    old: str                      # the bytes that shipped, read off disk
    new: str                      # what cria's code composes from the same inputs TODAY
    why: str                      # how the recomposition was driven, for the reader
    ws: pathlib.Path | None = None
    facts: dict = field(default_factory=dict)   # fix-specific deterministic checks (see FACTS)

    @property
    def session(self) -> str:
        return self.call.parent.name


@contextmanager
def _cwd(path):
    """Run a block with cwd at ``path`` (cria's spill guards ask the filesystem about relative
    paths), then put it back. Nothing here writes."""
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


def coder_bodies(cap: pathlib.Path):
    """(path, body) for every coder request in a capture dir, in call order."""
    for f in sorted(cap.glob("*coder*.json")):
        if f.name.endswith(".response.json"):
            continue
        try:
            b = (json.loads(f.read_text()).get("body") or {})
        except (OSError, ValueError):
            continue
        if b.get("messages"):
            yield f, b


def captured_reply(call: pathlib.Path) -> dict:
    """The message the model actually returned for this call, from disk — the third column."""
    resp = call.with_name(call.name.replace(".json", ".response.json"))
    try:
        j = json.loads(resp.read_text())
    except (OSError, ValueError):
        return {}
    return ((j.get("choices") or [{}])[0].get("message")) or {}


def captured_model(call: pathlib.Path) -> str:
    """The model id the SERVER answered as for this call — the authority on what the capture ran
    against. The request body often carries the harness's own name for the endpoint ("cria")."""
    resp = call.with_name(call.name.replace(".json", ".response.json"))
    try:
        return json.loads(resp.read_text()).get("model") or ""
    except (OSError, ValueError):
        return ""


def _msg_text(m: dict) -> str:
    c = m.get("content")
    if isinstance(c, list):
        return "".join(str(p.get("text", "")) for p in c if isinstance(p, dict))
    return c if isinstance(c, str) else ""


def substitute(body: dict, old: str, new: str) -> tuple[dict, int]:
    """The captured body with ``old`` replaced by ``new`` wherever a message carries it, and the
    number of messages changed. Everything else — tools, order, ids, sampling — is untouched, so the
    ONLY difference the model sees is the recomposed text."""
    out, hits = [], 0
    for m in body.get("messages", []):
        c = m.get("content")
        if isinstance(c, str) and old in c:
            out.append({**m, "content": c.replace(old, new)})
            hits += 1
        elif isinstance(c, list) and any(old in str(p.get("text", "")) for p in c
                                         if isinstance(p, dict)):
            out.append({**m, "content": [
                ({**p, "text": p["text"].replace(old, new)}
                 if isinstance(p, dict) and old in str(p.get("text", "")) else p) for p in c]})
            hits += 1
        else:
            out.append(m)
    return {**body, "messages": out}, hits


# ---------------------------------------------------------------------------------------------
# talking to the model


def loaded_model() -> str:
    try:
        with urllib.request.urlopen(MODELS, timeout=30) as r:
            j = json.load(r)
        return ((j.get("data") or [{}])[0].get("id")) or "?"
    except Exception:  # noqa: BLE001 — an unreachable server is data, reported in the header
        return "?"


def ask(body: dict) -> dict:
    out = {k: v for k, v in body.items() if k != "stream_options"}
    out["stream"] = False
    if not any(k in out for k in _SAMPLING):
        out["temperature"] = 0.0
    req = urllib.request.Request(CHAT, data=json.dumps(out).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as r:
        payload = json.load(r)
    return ((payload.get("choices") or [{}])[0].get("message")) or {}


# ---------------------------------------------------------------------------------------------
# deterministic FACTS about a reply. Observations only — a fact is checkable against bytes on disk.
# None means "the question does not apply to this reply", never a default answer.


def calls_of(msg: dict) -> list[tuple[str, dict]]:
    out = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except ValueError:
            args = {}
        out.append((fn.get("name") or "?", args if isinstance(args, dict) else {}))
    return out


def signature(msg: dict) -> str:
    """A reply's identity for the byte-identical check: content plus every tool call, verbatim."""
    return (msg.get("content") or "") + json.dumps(msg.get("tool_calls") or [], sort_keys=True)


def named_paths(msg: dict) -> set:
    return {str(a[k]) for _n, a in calls_of(msg) for k in _PATH_ARGS if a.get(k)}


def base_facts(msg: dict) -> dict:
    return {"tools": [n for n, _a in calls_of(msg)],
            "paths": sorted(named_paths(msg)),
            "reply_chars": len(msg.get("content") or ""),
            "thinking_chars": len(msg.get("reasoning_content") or "")}


def _fact_spill(case: Case, msg: dict) -> dict:
    """Does the reply still try to swallow the whole document — and does it use the outline?"""
    url = case.facts.get("url", "")
    target = case.facts.get("target", "")
    base = os.path.basename(target)
    whole_read = any(n in ("read_file", "list_dir") and base in json.dumps(a)
                     and not (a.get("start_line") or a.get("end_line")) for n, a in calls_of(msg))
    refetch = any(n == "web_fetch" and str(a.get("url", "")) == url for n, a in calls_of(msg))
    blob = signature(msg)
    routes = [r for r in case.facts.get("routes", []) if r and r in blob]
    return {"whole_read_of_spill": whole_read, "refetches_the_url": refetch,
            "echoes_the_<keyword>_placeholder": "<keyword>" in blob,
            "names_a_real_route_from_the_outline": routes[:6]}


def _fact_repeat(case: Case, msg: dict) -> dict:
    """Does the reply hand the same body back under any name? Byte containment, not similarity."""
    probe = case.facts.get("body_probe", "")
    writes = [a for n, a in calls_of(msg) if n in ("write_file", "edit_file")]
    return {"re-emits the quoted body": bool(probe) and any(probe in json.dumps(a) for a in writes),
            "write_targets": sorted({str(a.get("path") or a.get("file_path") or "") for a in writes})}


def _fact_edit_matches_disk(case: Case, msg: dict) -> dict:
    """Would this edit's old_string actually be FOUND in the file? The gate-verbatim defect was the
    coder copying cria's de-indented copy of a source line into an old_string that could never
    match — four failed edits in a row. The archived workspace holds the real file, so this is a
    fact, not an opinion. None when the reply proposes no edit."""
    res = {}
    for n, a in calls_of(msg):
        if n != "edit_file":
            continue
        old = a.get("old_string") or a.get("old") or ""
        p = a.get("path") or a.get("file_path") or ""
        if not old or not p or case.ws is None:
            continue
        f = case.ws / os.path.basename(str(p))
        if not f.is_file():
            continue
        try:
            res[os.path.basename(str(p))] = old in f.read_text(errors="replace")
        except OSError:
            continue
    return {"edit_old_string_is_in_the_real_file": res or None}


def _fact_import(case: Case, msg: dict) -> dict:
    """Does the reply delete or rewrite an import line? The advisory-gate defect was the coder
    removing a module-level import to satisfy a style warning, shipping a NameError."""
    touched = []
    for n, a in calls_of(msg):
        old = str(a.get("old_string") or a.get("old") or "")
        if n == "edit_file" and re.search(r"^\s*(import |from \S+ import )", old, re.M):
            touched.append(old.strip().splitlines()[0][:60])
    return {"edits_an_import_line": touched or None}


def _fact_missing_file(case: Case, msg: dict) -> dict:
    """Does the reply go back to the path that is not there, and do the paths it names exist? The
    defect was cria calling a nonexistent file empty, and the coder's own reasoning recording it as
    "the file was empty or couldn't be found" — so where it looks NEXT is the thing to watch."""
    asked = case.facts.get("path", "")
    paths = named_paths(msg)
    on_disk = sorted(p for p in paths if case.ws is not None
                     and (case.ws / os.path.basename(p)).exists())
    return {"asks_for_the_same_missing_path": asked in paths if asked else None,
            "paths_that_exist_in_the_archived_workspace": on_disk}


FACTS = {
    "spill-outline": _fact_spill,
    "repeat-body": _fact_repeat,
    "gate-verbatim": _fact_edit_matches_disk,
    "advisory-gate": _fact_import,
    "missing-file-read": _fact_missing_file,
}


# ---------------------------------------------------------------------------------------------
# the recomposers. One per fix. Each returns Cases whose `new` came out of cria's own code.


def _anchors(fragment: str, placeholder: str, tail: int = 25) -> tuple[str, str]:
    """The literal text a prompt fragment puts around ``placeholder`` — anchored on cria's own file,
    never a copy of its wording (replay_logic.around's rule, applied to a load_map fragment)."""
    left, right = fragment.split(placeholder)
    return left, right[:tail]


def cases_spill_outline(row, cap, ws, limit):
    """The re-fetch refusal, recomposed through :func:`webfetch.fetch_nav` itself.

    The refusal that shipped named a file and said "grep it". Today's carries the document's routes
    and response-field shapes. Driving the REAL entry point needs the state cria held in-process: the
    parsed document. That is reconstructible without inventing anything, because cria wrote the very
    same document to the workspace — the archived spill file IS the doc, so it is re-parsed with
    cria's own parser, put back in the cache with cria's own ``_cache_put``, and ``fetch_nav`` is
    called exactly as the coder's web_fetch would call it. It returns before any network I/O (the
    already-spilled branch), so nothing is fetched.

    Skipped, with the reason printed, when the spill file is gone or does not re-parse — an outline
    cria could not build from the real bytes is one it must not be credited with (rule 5b).

    The fix's SIBLING site — writeproxy's spill-file read steer — is not recomposed here. It carries
    the same ``outline_for_spill_path`` text into the same conversation slot, so the model-facing
    difference is the one already under test; a second case of the identical text would add prompts,
    not evidence. The refusal is also the larger population (1,438 of the 2,102 carrying calls)."""
    if ws is None:
        return []
    frag = prompts.load_map("webfetch_guards")["fetch_repeat_spilled"]
    pre, post = _anchors(frag, "{{URL}}")
    rx = re.compile(re.escape(pre) + r"(\S+)" + re.escape(post))
    out = []
    seen_urls = set()
    for call, body in coder_bodies(cap):
        if len(out) >= limit:
            break
        hit = None
        for m in body.get("messages", []):
            t = _msg_text(m)
            if replay_logic.SPILL_REFUSAL in t and rx.search(t):
                hit = (t, rx.search(t).group(1))
                break
        if not hit:
            continue
        old, url = hit
        if url in seen_urls:            # one case per document per run — the refusal is durable and
            continue                    # rides in every later prompt; N copies teach nothing new
        target = webfetch._spill_name(url)
        spill = ws / target.lstrip("./")
        if not spill.is_file():
            print(f"  · skip {call.name}: the spilled document is not in the archive ({target})")
            seen_urls.add(url)
            continue
        text = spill.read_text(errors="replace")
        reduced, parsed = webfetch.reduce_for_cache(text, "application/json", url)
        if parsed is None:
            print(f"  · skip {call.name}: the spilled document does not re-parse — cria could not "
                  f"have built an outline from it either")
            seen_urls.add(url)
            continue
        webfetch.clear_cache()
        webfetch._cache_put(url, 200, "application/json", reduced, parsed, False)
        webfetch.note_fetch_spill(case_session := call.parent.name, url, target)
        with _cwd(ws):
            new = webfetch.fetch_nav(url, session=case_session, workspace_root=os.getcwd())
        webfetch.clear_cache()
        routes = webfetch._endpoint_routes(parsed) or []
        out.append(Case("spill-outline", call, row.get("model", "?"), body, old, new,
                        f"fetch_nav re-driven on the archived spill of {url}", ws,
                        {"url": url, "target": target, "routes": routes}))
        seen_urls.add(url)
    return out


def cases_repeat_body(row, cap, ws, limit):
    """The repetition redirect, re-rendered from cria's own template with the bounded action.

    ``gs.repeat_action`` is the only thing the fix changed, so the recomposition is cria's own
    ``prompts.render("redirect_canned", …)`` twice: once with the action exactly as the prompt
    carried it, once with ``loop._clip(action, loop.REPEAT_ACTION_CHARS)`` — the clip the fix
    added, at the call site's own constant. The first render is what shipped (verified by finding
    it in the captured prompt); the second is what would ship now."""
    pre, post = replay_logic.around("redirect_canned", "{{REPEAT_ACTION}}")
    rx = re.compile(re.escape(pre) + r"(.*?)" + re.escape(post[:30]), re.S)
    out, seen = [], set()
    for call, body in coder_bodies(cap):
        if len(out) >= limit:
            break
        for m in body.get("messages", []):
            t = _msg_text(m)
            for mt in rx.finditer(t):
                action = mt.group(1)
                if len(action) <= loop.REPEAT_ACTION_CHARS or action in seen:
                    continue
                seen.add(action)
                old = prompts.render("redirect_canned", repeat_action=action, ground_truth="")
                if old not in t:        # the template moved since this run — say so, never guess
                    print(f"  · skip {call.name}: the shipped redirect no longer re-renders from "
                          f"the current template")
                    continue
                new = prompts.render("redirect_canned", ground_truth="",
                                     repeat_action=loop._clip(action, loop.REPEAT_ACTION_CHARS))
                probe = ""
                if (c := re.search(r'"content"\s*:\s*"(.{200,})', action, re.S)):
                    probe = c.group(1)[:200]
                out.append(Case("repeat-body", call, row.get("model", "?"), body, old, new,
                                f"redirect_canned re-rendered; the quoted action was "
                                f"{len(action)} chars, now {loop.REPEAT_ACTION_CHARS}", ws,
                                {"body_probe": probe}))
                break
            if len(out) >= limit:
                break
    return out


_EXEC_END = re.compile(r"^ (succeeded|exited \d+|failed) in .*:$")


def _raw_from_harness_log(row) -> list:
    """The RAW checker output as the HARNESS printed it, out of the run's own log.

    cria cleans the gate result before any call it captures, so on most runs the raw bytes exist in
    no capture file at all — only in the harness transcript, which records every exec command and
    everything it printed. An output block that begins with cria's own section marker IS the gate
    result. Taken as a SOURCE only: whether a block is really the one a prompt carried is settled by
    the pairing overlap printed with each case, not assumed here."""
    log = pathlib.Path(str(row.get("harness_log") or ""))
    if not log.is_file():
        return []
    out, block, collecting = [], [], False
    for ln in log.read_text(errors="replace").splitlines():
        if collecting:
            if ln == "codex" or ln.startswith("⟦cria⟧") or ln.startswith("exec"):
                collecting = False
                text = "\n".join(block).strip("\n")
                if probegate.SECTION_PREFIX in text and text not in out:
                    out.append(text)
                block = []
            else:
                block.append(ln)
            continue
        if _EXEC_END.match(ln):
            collecting, block = True, []
    return out


def _raw_gate_outputs(cap):
    """Every distinct RAW checker output the harness handed back, from the proxy captures — the
    bytes ``clean_gate_output`` reads. This is the fix's real input; the coder prompt only ever
    holds what the old code made of it."""
    seen, out = set(), []
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
            c = _msg_text(m)
            if probegate.SECTION_PREFIX in c and c not in seen:
                seen.add(c)
                out.append(c)
    return out


_HEAD = probegate.CHECKS_MARKER + " the repo's own checks report"


def _shipped_checks_blocks(body):
    """The ⟦ctx:checks⟧ error-class blocks a captured prompt actually carried, whole."""
    for m in body.get("messages", []):
        t = _msg_text(m)
        i = t.find(_HEAD)
        while i >= 0:
            end = replay_logic.BLOCK_END_RE.search(t, i)
            yield t[i:end.start() if end else len(t)].rstrip()
            i = t.find(_HEAD, i + 1)


def _finding_lines(block):
    return [ln for ln in block.split("\n")[1:] if ln.strip()]


def _gate_cases(fix, row, cap, ws, limit, differs):
    """Shared by gate-verbatim and advisory-gate: both are one function, ``clean_gate_output``, run
    over the raw checker bytes the run captured. The block that SHIPPED is read off disk; the block
    that would ship now is composed by the current cleaner; ``differs`` decides which difference
    class this fix is asking about.

    The raw output is paired to the shipped block by counting shared finding lines (compared
    stripped, since stripping is exactly what the old code did) and taking the best match. The
    pairing evidence is printed with the case, so a wrong pairing is visible rather than silent."""
    shipped_any = any(True for _f, b in coder_bodies(cap) for _ in _shipped_checks_blocks(b))
    composed = []
    for src, raws in (("a proxy capture", _raw_gate_outputs(cap)),
                      ("the harness log", _raw_from_harness_log(row))):
        for raw in raws:
            clean = probegate.clean_gate_output(raw)
            if clean and clean.startswith(_HEAD):   # the FINDINGS header, not the clean one
                composed.append((clean, src))
    if not composed:
        if shipped_any:
            NOTES.append("shipped gate findings, but the RAW checker output survives in no capture "
                         "and no complete log block (the harness log keeps only the tail of a long "
                         "exec output) — recomposing it would be inventing the checker's words")
        return []
    def _pair(old):
        """The composed block that best matches ``old``, its source, and the overlap."""
        old_lines = {ln.strip() for ln in _finding_lines(old)}
        best, score, src = None, 0, ""
        for clean, source in composed:
            shared = len({ln.strip() for ln in _finding_lines(clean)} & old_lines)
            if shared > score:
                best, score, src = clean, shared, source
        return best, score, src, len(old_lines)

    out, used = [], set()
    for call, body in coder_bodies(cap):
        blocks = list(_shipped_checks_blocks(body))
        # EVERY gate block in this prompt gets recomposed, not only the one the fix is asked about.
        # A conversation carries the same findings several turns over; leaving the earlier copies as
        # they shipped leaves the suppressed lines in front of the model and understates the fix —
        # measured, the first advisory case still saw all four findings through an older block.
        others = []
        for blk in blocks:
            b_new, _s, _src, _n = _pair(blk)
            # ``differs`` is the whole-relation test — the same guard that keeps a case from pairing
            # one gate's output against another's applies to the siblings too.
            if b_new and b_new != blk and differs(blk, b_new):
                others.append((blk, b_new))
        for old in blocks:
            if old in used:
                continue
            best, score, src, carried = _pair(old)
            if best is None or not differs(old, best):
                continue
            used.add(old)
            out.append(Case(fix, call, row.get("model", "?"), body, old, best,
                            f"clean_gate_output re-run on the raw checker output from {src}; paired "
                            f"to the shipped block on {score} shared finding lines "
                            f"(of {carried} it carried)", ws,
                            {"also": [p for p in others if p[0] != old],
                             "unpaired": len(blocks) - len(others) - 1}))
            break
    # The call whose WHOLE prompt could be recomposed is the honest one to send: a block left as it
    # shipped puts the old text back in front of the model through an older turn. Ordering, not
    # filtering — a run where nothing pairs fully still yields its best case, labelled.
    out.sort(key=lambda c: c.facts.get("unpaired", 0))
    return out[:limit]


def _differs_verbatim(old, new):
    """The shipped block is the FLATTENED copy of what the cleaner now emits: same lines once
    stripped and de-duplicated, different bytes. That is the indentation/duplication loss."""
    if old == new:
        return False
    flat, seen = [], set()
    for ln in _finding_lines(new):
        s = ln.strip()
        if s not in seen:
            seen.add(s)
            flat.append(s)
    return flat == [ln.strip() for ln in _finding_lines(old)] and flat != _finding_lines(new)


def _differs_advisory(old, new):
    """The shipped block is the SAME gate result minus what ``is_advisory`` now suppresses: every
    line the new block keeps was in the old one, and every line it dropped is advisory by cria's own
    predicate (in both forms probegate applies it).

    The whole relation is the test, not just "some advisory line vanished". A looser version paired a
    pytest failure block against an unrelated shellcheck-usage gate from the same run — 17 shared
    lines out of 57, all of them the shellcheck boilerplate — and would have sent the model a prompt
    cria never composed. Caught by reading the diff; encoded here so it cannot recur."""
    o = {ln.strip() for ln in _finding_lines(old)}
    n = {ln.strip() for ln in _finding_lines(new)}
    if not n or (n - o):        # a line the shipped block never had → a DIFFERENT gate result
        return False
    dropped = o - n
    return bool(dropped) and all(
        probeparse.is_advisory(s) or probeparse.is_advisory(probegate._LOC_PREFIX.sub("", s))
        for s in dropped)


def cases_gate_verbatim(row, cap, ws, limit):
    return _gate_cases("gate-verbatim", row, cap, ws, limit, _differs_verbatim)


def cases_advisory_gate(row, cap, ws, limit):
    return _gate_cases("advisory-gate", row, cap, ws, limit, _differs_advisory)


def cases_missing_file_read(row, cap, ws, limit):
    """The ranged read of a path that is not there, recomposed through ``translate_outbound`` and
    RUN.

    This answer is produced by a shell command cria lowers and the harness executes, so recomposing
    it in Python would be inventing the harness's output. Instead the coder's own captured
    ``read_file`` arguments go back through ``writeproxy.translate_outbound`` (with the harness's own
    shell tool, taken from the captured tools list), and the resulting command is run in an EMPTY
    scratch directory — where the path is absent exactly as it was absent in the run. What the
    command prints is what the harness would have printed.

    Absence is judged against the archived (final) workspace, as in replay_logic: a path created
    later reads as present, which under-counts rather than over-claims."""
    if ws is None:
        return []
    scratch = pathlib.Path(os.environ.get("TMPDIR", "/tmp")) / "cria-recompose-scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    root = str(row.get("workspace") or "")
    out, seen = [], set()
    for call, body in coder_bodies(cap):
        if len(out) >= limit:
            break
        msgs = body.get("messages", [])
        for i, m in enumerate(msgs):
            t = _msg_text(m)
            mt = replay_logic.PAST_EOF_RE.search(t)
            if not mt or int(mt.group(2)) or mt.group(0) in seen:
                continue
            path = mt.group(1)
            rel = path[len(root):] if root and path.startswith(root) else path
            rel = rel.lstrip("./").lstrip("/")
            if not rel or os.path.isabs(rel) or (ws / rel).exists():
                continue                # the file really was there — nothing false was said
            args = None
            for a in reversed(msgs[:i]):
                if a.get("role") == "assistant" and a.get("tool_calls"):
                    for tc in a["tool_calls"]:
                        fn = tc.get("function") or {}
                        if tc.get("id") == m.get("tool_call_id"):
                            try:
                                args = json.loads(fn.get("arguments") or "{}")
                            except ValueError:
                                args = None
                    break
            if not isinstance(args, dict) or not args.get("path"):
                print(f"  · skip {call.name}: the read_file call that produced this answer is not "
                      f"in the captured history")
                continue
            shell = shelltool.find_shell_tool(body.get("tools") or [])
            if not shell:
                print(f"  · skip {call.name}: the capture advertises no shell tool to lower into")
                continue
            comp = {"choices": [{"message": {"tool_calls": [
                {"id": "r1", "type": "function",
                 "function": {"name": "read_file", "arguments": json.dumps(args)}}]}}]}
            writeproxy.translate_outbound(comp, shell, injected={"read_file"})
            lowered = json.loads(
                comp["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
            cmd = lowered.get("cmd") or lowered.get("command")
            cmd = cmd[-1] if isinstance(cmd, list) else cmd
            got = subprocess.run(["sh", "-c", cmd], cwd=scratch, capture_output=True, text=True,
                                 timeout=30)
            new = (got.stdout or got.stderr).strip()
            seen.add(mt.group(0))
            out.append(Case("missing-file-read", call, row.get("model", "?"), body,
                            mt.group(0), new,
                            f"read_file{json.dumps(args)} lowered by translate_outbound and run "
                            f"where the path is absent", ws, {"path": str(args.get("path"))}))
            break
    return out


RECOMPOSERS = {
    "spill-outline": cases_spill_outline,
    "repeat-body": cases_repeat_body,
    "gate-verbatim": cases_gate_verbatim,
    "advisory-gate": cases_advisory_gate,
    "missing-file-read": cases_missing_file_read,
}


# ---------------------------------------------------------------------------------------------
# reporting


def difference_classes(old: str, new: str) -> list:
    """WHAT changed between a shipped ⟦ctx:checks⟧ block and the recomposed one, named — because more
    than one fix of this cycle touches that block and attribution must not be assumed. Its header
    sentence was rewritten by a DIFFERENT commit than the one that restored indentation, and a reader
    comparing replies has to know both are in play. Deterministic string facts only."""
    o, n = old.split("\n"), new.split("\n")
    if not (o[0].startswith(probegate.CHECKS_MARKER) and n[0].startswith(probegate.CHECKS_MARKER)):
        return []               # only the gate block has this line-per-finding shape
    out = []
    if o[:1] != n[:1]:
        out.append("the block's HEADER sentence differs (a separate prompt fix, not this one)")
    o_lines, n_lines = o[1:], n[1:]
    dropped = [ln.strip() for ln in o_lines if ln.strip()
               and ln.strip() not in {x.strip() for x in n_lines}]
    added = [ln.strip() for ln in n_lines if ln.strip()
             and ln.strip() not in {x.strip() for x in o_lines}]
    reindented = sum(1 for ln in n_lines if ln != ln.strip() and ln.strip() in
                     {x.strip() for x in o_lines})
    if dropped:
        out.append(f"{len(dropped)} finding line(s) no longer shipped, e.g. {dropped[0][:90]!r}")
    if added:
        out.append(f"{len(added)} line(s) now shipped that were not, e.g. {added[0][:90]!r}")
    if reindented:
        out.append(f"{reindented} line(s) keep the checker's own indentation")
    dups = len(n_lines) - len({x.strip() for x in n_lines})
    if dups > len(o_lines) - len({x.strip() for x in o_lines}):
        out.append("repeated checker lines are no longer de-duplicated away")
    return out


def show_diff(old: str, new: str, detail: bool) -> None:
    lines = list(difflib.unified_diff(old.splitlines(), new.splitlines(),
                                      "as it shipped", "as cria composes it today", lineterm="", n=1))
    if not detail and len(lines) > 60:
        lines = lines[:60] + [f"… {len(lines) - 60} more diff lines (--detail for all)"]
    for ln in lines:
        print("    " + ln)


def show_reply(label: str, msg: dict, detail: bool) -> None:
    print(f"  ── {label}")
    think = msg.get("reasoning_content") or ""
    content = msg.get("content") or ""
    cap = 100_000 if detail else 1200
    if think:
        print(f"     THINKING ({len(think)} chars): {think[:cap]}" + ("…" if len(think) > cap else ""))
    if content:
        print(f"     SAYS: {content[:cap]}" + ("…" if len(content) > cap else ""))
    for n, a in calls_of(msg):
        blob = json.dumps(a)
        print(f"     CALLS {n} {blob[:cap]}" + ("…" if len(blob) > cap else ""))
    if not think and not content and not msg.get("tool_calls"):
        print("     (empty reply)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", choices=sorted(RECOMPOSERS), action="append")
    ap.add_argument("--n", type=int, default=3, help="cases per fix (a few READ beats many counted)")
    ap.add_argument("--per-run", type=int, default=1, help="cases taken from any one captured run")
    ap.add_argument("--detail", action="store_true", help="full replies and full diffs")
    ap.add_argument("--dry-run", action="store_true", help="build cases, call no model")
    ap.add_argument("--session", help="only captures from this session id")
    ap.add_argument("--oldest-first", action="store_true",
                    help="take cases from the earliest runs (default: the most recent, which are "
                         "the ones the walks read and the ones the current model ran)")
    args = ap.parse_args()
    wanted = args.fix or sorted(RECOMPOSERS)

    live = loaded_model()
    data = replay_logic.runs()
    if not args.oldest_first:
        data = list(reversed(data))
    if args.session:
        data = [d for d in data if d[1].name == args.session]
    print(f"model server {BASE} has {live!r} loaded · {len(data)} captured runs with evidence")
    print("replies are SHOWN, never scored — the facts printed are byte checks, the reading is "
          "yours\n")

    for fix in wanted:
        print(f"{'=' * 100}\n══ {fix}\n{'=' * 100}")
        cases, unchanged, built = [], 0, 0
        NOTES.clear()
        for row, cap, ws in data:
            if len(cases) >= args.n:
                break
            try:
                got = RECOMPOSERS[fix](row, cap, ws, args.per_run)
            except Exception as e:  # noqa: BLE001 — a recomposition that fails is reported, not hidden
                print(f"  · skip {cap.name}: recomposition raised {type(e).__name__}: {e}")
                continue
            built += len(got)
            # A case whose recomposition is IDENTICAL is a real answer — the run already had the fix,
            # or the fix does not reach this call — but it costs the model nothing, so it is counted
            # and named rather than sent, and the search continues for one that DOES differ.
            for c in got:
                if c.old == c.new:
                    unchanged += 1
                    print(f"  · {c.session}/{c.call.name}: recomposed text is IDENTICAL to what "
                          f"shipped — nothing to ask the model")
                elif len(cases) < args.n:
                    cases.append(c)
        for note in sorted(set(NOTES)):
            print(f"  · {sum(1 for x in NOTES if x == note)} run(s): {note}")
        if not cases:
            print(f"  no case with a recomposed difference ({built} built, {unchanged} identical)\n")
            continue
        print(f"  {built} case(s) recomposed; {unchanged} identical to what shipped; "
              f"{len(cases)} sent to the model\n")

        for c in cases:
            body_new, hits = substitute(c.body, c.old, c.new)
            # Sibling renderings of the SAME guard elsewhere in this conversation are recomposed too
            # (see _gate_cases): leaving them as they shipped puts the old text back in front of the
            # model through an older turn and understates the fix.
            also = 0
            for o, n in c.facts.get("also") or []:
                body_new, extra = substitute(body_new, o, n)
                also += extra
            # The capture's OWN model id (what the server answered as), not the ladder's short name
            # — a replay against a different model is still informative but must be labelled.
            # The server's OWN answer is the authority (the harness sends "cria" as the model name).
            was = captured_model(c.call) or c.body.get("model") or c.model
            if was in ("cria", "", None):
                was = c.model
            print(f"── {c.session}/{c.call.name}  (captured against {was} [{c.model}]; replayed "
                  f"against {live}{'' if was == live else '  ← DIFFERENT MODEL — label the reading'})")
            sampling = {k: v for k, v in c.body.items() if k in _SAMPLING} or {"temperature": 0.0}
            print(f"   sampling (the call's own): {sampling}")
            print(f"   {c.why}")
            print(f"   the text appears in {hits} message(s) of the prompt; "
                  f"{len(c.old)} chars → {len(c.new)} chars"
                  + (f"; {also} sibling block(s) recomposed too" if also else ""))
            # Whatever could NOT be recomposed stays as it shipped, and the reader must know — else
            # the new text gets credit for a reply the old text also shaped.
            leftover = sum(_msg_text(m).count(_HEAD) for m in body_new.get("messages", []))
            if fix in ("gate-verbatim", "advisory-gate") and leftover > hits + also:
                print(f"   NOTE {leftover - hits - also} OTHER ⟦ctx:checks⟧ block(s) could not be "
                      f"paired to raw output and remain as they shipped — this call reads both")
            show_diff(c.old, c.new, args.detail)
            for cls in difference_classes(c.old, c.new):
                print(f"   · {cls}")
            if c.old == c.new:
                print("   RECOMPOSED TEXT IS IDENTICAL — this fix changes nothing the model reads "
                      "on this call; not sent.\n")
                continue
            if hits == 0:
                print("   the shipped text was not found in the body — not sent.\n")
                continue
            if args.dry_run:
                print()
                continue
            fact_fn = FACTS[fix]
            show_reply("CAPTURED at run time (from disk)", captured_reply(c.call), args.detail)
            try:
                # BOTH prompts twice. A weak model at its own sampling moves on its own, and a
                # single old reply against a single new one cannot tell that apart from the change.
                a1, a2 = ask(c.body), ask(c.body)
                b1, b2 = ask(body_new), ask(body_new)
            except Exception as e:  # noqa: BLE001
                print(f"   upstream error: {type(e).__name__}: {e}\n")
                continue
            stable = signature(a1) == signature(a2) and signature(b1) == signature(b2)
            show_reply("REPLAY of the prompt AS IT SHIPPED", a1, args.detail)
            if signature(a1) != signature(a2):
                show_reply("...the SAME old prompt, second send", a2, args.detail)
            show_reply("REPLAY of the RECOMPOSED prompt", b1, args.detail)
            if signature(b1) != signature(b2):
                show_reply("...the SAME recomposed prompt, second send", b2, args.detail)
            print("  ── facts")
            print(f"     the model is {'DETERMINISTIC' if stable else 'NOT deterministic'} here — "
                  + ("two sends of each prompt agreed" if stable else
                     "a prompt sent twice gave two different replies, so read each column as ONE "
                     "SAMPLE, not a result"))
            print(f"     replies byte-identical old vs new: {signature(a1) == signature(b1)}")
            for label, msg in (("old  #1", a1), ("old  #2", a2), ("new  #1", b1), ("new  #2", b2)):
                f = {**base_facts(msg), **fact_fn(c, msg)}
                print(f"     {label}: " + "  ".join(f"{k}={v}" for k, v in f.items()
                                                    if v not in (None, [])))
            print()


if __name__ == "__main__":
    main()
