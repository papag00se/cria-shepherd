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

ASK THE MODEL THAT HAD THE PROBLEM. ``--same-model`` groups the cases by the model each capture ran
against and loads that model before sending, one swap per model. Without it every case is answered by
whatever happens to be on the GPU, and a reply from a different model is not evidence about the model
that shipped the defect — it is not even the same chat template. The first run of this harness did
exactly that and its "no behavioural change" readings had to be thrown away.

Read-only: no workspace is touched (the archived copies are read, and cwd is restored), no result is
fed back into a run, and cria is never restarted. The MODEL SERVER on :18084 is restarted by
``--same-model`` — that is the point of the flag — and whatever was loaded when it started is put back
at the end. Model calls go DIRECTLY to the model server, like replay.py, so nothing here depends on
cria's routing.
"""
import argparse
import atexit
import difflib
import json
import os
import pathlib
import re
import signal
import subprocess
import sys
import tomllib
import urllib.request
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field

SUITE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(SUITE.parent))
sys.path.insert(0, str(SUITE))

import ladder_status  # noqa: E402 — ONE owner for "which model is blocked on its build"
import replay_logic  # noqa: E402 — sibling harness: ONE owner for "which runs have evidence"
import run as ladder_run  # noqa: E402 — ONE owner for model name -> systemd unit, and the swap
from cria import (loop, probegate, probeparse, prompts, shelltool,  # noqa: E402
                  webfetch, writeproxy)

# The fleet's launch config: the ONE place that says which served model id a fleet name answers as.
# Read rather than copied, so a re-quantised model cannot silently break attribution here.
FLEET_TOML = pathlib.Path.home() / ".config" / "llama-fleet" / "models.toml"
# How many of a run's coder replies are read to corroborate the ladder row's model. One run is one
# model by construction, so this is a cross-check, not a scan.
CORROBORATE_CALLS = 8
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


def served_model(resp: pathlib.Path) -> str:
    """The model id the SERVER answered as, read off a captured RESPONSE file."""
    try:
        return json.loads(resp.read_text()).get("model") or ""
    except (OSError, ValueError):
        return ""


def captured_model(call: pathlib.Path) -> str:
    """The model id the SERVER answered as for this call — the authority on what the capture ran
    against. The request body often carries the harness's own name for the endpoint ("cria")."""
    return served_model(call.with_name(call.name.replace(".json", ".response.json")))


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


# ---------------------------------------------------------------------------------------------
# WHICH MODEL PRODUCED THIS CAPTURE, and how to put it back on the GPU
#
# Two independent records answer the first question and they are cross-checked rather than picked
# between. The ladder row is the ATTRIBUTION: `suite/run.py` swaps the model, then runs, then writes
# the row, so the row's `model` is the runner's own statement of what was loaded. The capture's
# `.response.json` carries the id the SERVER answered as, which is the model itself speaking — but
# only on the runs whose harness did not send its own name for the endpoint (older captures answer
# "cria"). Where both exist they must agree; a conflict excludes the run rather than choosing.


def fleet_aliases() -> dict:
    """served-model-id -> ladder model name, read off the fleet's own launch config.

    ``models.toml`` maps a fleet name to the ``alias`` its server answers as; ``run.SERVICES`` maps
    the LADDER's name for a model to its systemd unit, which is ``llama-<fleet name>…``. Joining the
    two gives id -> ladder name with no hand-written table to drift."""
    try:
        fleet = tomllib.loads(FLEET_TOML.read_text()).get("models") or {}
    except (OSError, ValueError):
        return {}
    out = {}
    for fleet_name, spec in fleet.items():
        alias = (spec or {}).get("alias")
        if not alias:
            continue
        for ladder_name, svc in ladder_run.SERVICES.items():
            if svc.startswith(f"llama-{fleet_name}"):
                out[alias] = ladder_name
    return out


def origin_model(row, cap, aliases) -> tuple:
    """(ladder model name, how it is known) for a captured run, or (None, why not).

    Never guesses: a run whose two records disagree, or whose row names no model, is excluded with
    its reason, because a case sent to the wrong model answers a question nobody asked."""
    claimed = str(row.get("model") or "")
    # The first coder replies are enough: a run cannot span two models — `run.py` swaps once, before
    # the harness starts — so this is corroboration of the row, not a search for a mid-run change.
    served = {served_model(f) for f in sorted(cap.glob("*coder*.response.json"))[:CORROBORATE_CALLS]}
    served = {s for s in served if s and s != "cria"}
    known = {aliases[s] for s in served if s in aliases}
    unknown = served - set(aliases)
    if not claimed:
        return None, "the ladder row names no model"
    if unknown:
        return None, (f"the server answered as {sorted(unknown)}, which the fleet config does not "
                      f"name — cannot corroborate")
    if len(known) > 1:
        return None, f"the captures answer as more than one model: {sorted(known)}"
    if known and next(iter(known)) != claimed:
        return None, (f"the ladder row says {claimed} but the server answered as "
                      f"{next(iter(known))} — conflicting records")
    return claimed, ("corroborated by the server's own id" if known else
                     "the ladder runner's record (the server echoed the harness name)")


def ensure_loaded(name: str, aliases: dict) -> tuple:
    """Put ``name`` on the GPU. Returns (ok, message). Uses the ladder runner's own swap so there is
    ONE implementation of "one model at a time on this card"."""
    want = [a for a, n in aliases.items() if n == name]
    if loaded_model() in want:
        return True, f"{name} already loaded"
    if name not in ladder_run.SERVICES:
        return False, f"no systemd unit is configured for {name}"
    try:
        ladder_run.swap_model(name)
    except Exception as e:  # noqa: BLE001 — a model that will not load is a reported skip, not a crash
        return False, f"{name} did not come up: {type(e).__name__}: {e}"
    got = loaded_model()
    if want and got not in want:
        return False, f"asked for {name}, the server answers as {got!r}"
    return True, f"{name} loaded ({got})"


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
    """A reply's identity for the byte-identical check: everything the MODEL produced — its
    reasoning, its answer, and each tool call's name and arguments.

    The tool call's ``id`` is deliberately excluded. llama.cpp mints a fresh 32-character random id
    for every response (verified against the live server: three sends of one prompt at temperature 0
    returned identical arguments under three different ids), so it is the server's handle, not the
    model's output. Including it made every reply that called a tool differ from itself — which is
    exactly what the first run of this harness reported: EVERY case "non-deterministic" and EVERY
    old/new pair "not byte-identical". Both were this line, not the model. A harness that measures
    its own transport is rule 12's mistake at the measurement layer."""
    parts = [msg.get("reasoning_content") or "", msg.get("content") or ""]
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        parts.append(json.dumps({"name": fn.get("name"), "arguments": fn.get("arguments")},
                                sort_keys=True))
    return "\x1f".join(parts)


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
    """The gate-verbatim defect was the coder copying cria's DE-INDENTED copy of a source line into
    an ``edit_file`` old_string that could never match the file — four failed edits in a row.

    Two facts, both byte checks. First: does the edit quote a line out of the checks block at all
    (that is the copying, and it is measured against the block THIS prompt carried). Second: is the
    old_string present in the archived workspace file — which is the FINAL state of that run, not
    the state at this call, so it is named as such and is evidence only when True."""
    quoted, on_disk = [], {}
    block_lines = [ln.strip() for ln in case.old.split("\n")[1:] if len(ln.strip()) >= 20]
    for n, a in calls_of(msg):
        if n != "edit_file":
            continue
        old = str(a.get("old_string") or a.get("old") or "")
        p = str(a.get("path") or a.get("file_path") or "")
        if not old:
            continue
        quoted += [ln[:60] for ln in block_lines if ln in old]
        f = (case.ws / os.path.basename(p)) if (case.ws and p) else None
        if f is not None and f.is_file():
            try:
                on_disk[os.path.basename(p)] = old in f.read_text(errors="replace")
            except OSError:
                pass
    return {"edit_quotes_a_line_from_the_checks_block": quoted or None,
            "old_string_in_the_FINAL_archived_file": on_disk or None}


_IMPORT_LINE = re.compile(r"^([ \t]*)((?:import |from \S+ import ).*)$", re.M)


def _fact_import(case: Case, msg: dict) -> dict:
    """Does the reply delete an import line? The advisory-gate defect was the coder removing a
    module-level import to satisfy a style warning, shipping a NameError.

    "Touched an import" is not that defect — it fires on any edit whose old_string happens to span
    the import block, and reading four such replies showed every one of them harmless. What answers
    the question is the DIFFERENCE: an import present in ``old_string`` and absent from
    ``new_string`` is one this edit removes. The indentation is kept because it is the whole
    distinction — deleting a module-level ``import json`` ships a NameError, while collapsing a
    duplicate copy of it nested inside ``if __name__`` is the correct fix for that same warning, and
    the two are indistinguishable once the leading whitespace is stripped."""
    touched, removed = [], []
    for n, a in calls_of(msg):
        if n != "edit_file":
            continue
        old = str(a.get("old_string") or a.get("old") or "")
        new = str(a.get("new_string") or a.get("new") or "")
        was = {(m.group(1), m.group(2).strip()) for m in _IMPORT_LINE.finditer(old)}
        now = {(m.group(1), m.group(2).strip()) for m in _IMPORT_LINE.finditer(new)}
        touched += [t[1][:60] for t in sorted(was)]
        removed += [("module-level " if not indent else f"nested ({len(indent)} spaces in) ") + line
                    for indent, line in sorted(was - now)]
    return {"edits_an_import_line": touched or None, "REMOVES_an_import": removed or None}


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


def _fact_spill_read_small(case: Case, msg: dict) -> dict:
    """The refusal said "grep the file for what you need" about a file with no outline. So: does the
    reply grep it, read it again, go back to the network — and does it name anything that is only
    IN the file, which is the one thing it could not have known before.

    ``names_something_only_the_file_says`` is a byte check against the archived file, not a score:
    the strings are drawn from the file's own lines, so a hit means the model repeated content that
    was in the recomposed text and nowhere else in the prompt."""
    rel = case.facts.get("path", "")
    base = os.path.basename(rel)
    blob = signature(msg)
    greps = [c for n, a in calls_of(msg) if n in ("shell", "bash", "exec_command", "run_terminal_cmd")
             for c in [json.dumps(a)] if "grep" in c and base in c]
    rereads = [n for n, a in calls_of(msg) if n in ("read_file", "list_dir") and base in json.dumps(a)]
    only_here = [s for s in case.facts.get("only_in_the_file", []) if s in blob]
    return {"greps_the_same_file_again": bool(greps),
            "reads_the_same_file_again": rereads or None,
            "fetches_the_web_again": [str(a.get("url", "")) for n, a in calls_of(msg)
                                      if n == "web_fetch"] or None,
            "names_something_only_the_file_says": only_here[:6]}


FACTS = {
    "unclosed-verdict": lambda case, msg: _fact_unclosed_verdict(case, msg),
    "spill-read-small": _fact_spill_read_small,
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
    """(block, is the whole message) for every ⟦ctx:checks⟧ error-class block a captured prompt
    carried.

    The second value is load-bearing. cria delivers a gate result as a message of its own, so a
    message that is NOTHING BUT the block has a known end: the end of the message. Where the block is
    embedded in something larger — a compaction briefing, which re-quotes it above its own ``• ``
    digests — nothing in the bytes says where the checker's lines stop, and a recomposer that guesses
    will edit its neighbour. Measured: a first version deleted three lines out of the coder's OWN
    pyflakes exec output, which is not cria's text to touch at all."""
    for m in body.get("messages", []):
        t = _msg_text(m)
        i = t.find(_HEAD)
        while i >= 0:
            end = replay_logic.BLOCK_END_RE.search(t, i)
            block = t[i:end.start() if end else len(t)].rstrip()
            yield block, block == t.strip()
            i = t.find(_HEAD, i + 1)


def _finding_lines(block):
    return [ln for ln in block.split("\n")[1:] if ln.strip()]


def _advisory_filtered(block):
    """The shipped gate block with only its ADVISORY findings removed — cria's own predicate, applied
    exactly as ``probegate`` applies it (whole line, and line minus its ``file:line:col:`` prefix).

    Recomposing a gate block normally needs the RAW checker bytes, because the pre-fix cleaner
    destroyed indentation and duplicate lines and only the raw output can put them back. The advisory
    fix restores nothing — ``is_advisory`` DELETES findings — so the block the prompt already carries
    is input enough, and every surviving line here is a byte copy of a line that shipped. Nothing is
    composed; the header sentence is left exactly as it shipped so the ONLY difference the model sees
    is the suppression this fix is being asked about.

    Why this matters rather than being a convenience: on the mellum2 run that shipped the NameError,
    the coder prompt carried the same findings in THREE ⟦ctx:checks⟧ blocks, and the raw output for
    two of them survives nowhere. Recomposing only the third left the model reading the suppressed
    lines through the other two — the A/B measured almost nothing, and the model's own reasoning
    still enumerated all four findings.

    None when nothing in the block is advisory, or when EVERYTHING is: a fully advisory result ships
    as no block at all today, and rendering that as an empty findings list would be inventing a
    surface cria does not emit."""
    head, *lines = block.split("\n")
    kept = [ln for ln in lines
            if not (probeparse.is_advisory(ln.strip())
                    or probeparse.is_advisory(probegate._LOC_PREFIX.sub("", ln.strip())))]
    if len(kept) == len(lines) or not any(ln.strip() for ln in kept):
        return None
    return "\n".join([head] + kept)


def _gate_cases(fix, row, cap, ws, limit, differs):
    """Shared by gate-verbatim and advisory-gate: both are one function, ``clean_gate_output``, run
    over the raw checker bytes the run captured. The block that SHIPPED is read off disk; the block
    that would ship now is composed by the current cleaner; ``differs`` decides which difference
    class this fix is asking about.

    The raw output is paired to the shipped block by counting shared finding lines (compared
    stripped, since stripping is exactly what the old code did) and taking the best match. The
    pairing evidence is printed with the case, so a wrong pairing is visible rather than silent.

    Where no raw output survives, advisory-gate falls back to :func:`_advisory_filtered` — not an
    approximation but the same predicate on a sufficient input (see its docstring). gate-verbatim has
    no such fallback and reports the missing evidence instead."""
    shipped_any = any(True for _f, b in coder_bodies(cap) for _ in _shipped_checks_blocks(b))
    composed = []
    for src, raws in (("a proxy capture", _raw_gate_outputs(cap)),
                      ("the harness log", _raw_from_harness_log(row))):
        for raw in raws:
            clean = probegate.clean_gate_output(raw)
            if clean and clean.startswith(_HEAD):   # the FINDINGS header, not the clean one
                composed.append((clean, src))
    if not composed and fix != "advisory-gate":
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

    all_advisory: set = set()

    def _recompose(blk, whole):
        """(the block cria composes today, how it was driven) or (None, '')."""
        best, score, src, carried = _pair(blk)
        # ``differs`` is the whole-relation test — the guard that keeps a case from pairing one
        # gate's output against another's applies to the siblings too.
        if best is not None and best != blk and differs(blk, best):
            return best, (f"clean_gate_output re-run on the raw checker output from {src}; paired "
                          f"to the shipped block on {score} shared finding lines "
                          f"(of {carried} it carried)")
        # Only where the block IS the message: elsewhere its end is not in the bytes.
        if fix == "advisory-gate" and whole:
            filt = _advisory_filtered(blk)
            if filt:
                return filt, ("probeparse.is_advisory applied line-by-line to the block cria "
                              "shipped — this fix only DELETES findings, so every surviving line "
                              "is a byte copy of one the prompt carried")
            if all(probeparse.is_advisory(ln.strip())
                   or probeparse.is_advisory(probegate._LOC_PREFIX.sub("", ln.strip()))
                   for ln in _finding_lines(blk)) and not all_advisory:
                all_advisory.add(cap)      # NOTES is counted per RUN — say it once for this one
                NOTES.append("a gate block whose findings are ALL advisory is left as it shipped: "
                             "cria would send its clean-result sentence instead, and composing that "
                             "here would mean copying cria's own wording rather than running its "
                             "code — so this run's case understates the fix by that block")
        return None, ""

    out, used = [], set()
    for call, body in coder_bodies(cap):
        blocks = list(_shipped_checks_blocks(body))
        # EVERY gate block in this prompt gets recomposed, not only the one the fix is asked about.
        # A conversation carries the same findings several turns over; leaving the earlier copies as
        # they shipped leaves the suppressed lines in front of the model and understates the fix —
        # measured, the first advisory case still saw all four findings through an older block.
        others = [(blk, new) for blk, new in ((b, _recompose(b, w)[0]) for b, w in blocks) if new]
        for old, whole in blocks:
            if old in used:
                continue
            best, why = _recompose(old, whole)
            if best is None:
                continue
            used.add(old)
            out.append(Case(fix, call, row.get("model", "?"), body, old, best, why, ws,
                            {"also": [p for p in others if p[0] != old],
                             "unpaired": len(blocks) - len(others)}))
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


# The two spellings of "cria could not read the verdict" the corpus holds. The first is cria's
# CURRENT prompt file, read rather than copied. The second is the retired bookkeeping line it
# replaced — a literal, because nothing in the repo still holds it, and a harness that only matches
# today's wording silently measures the newest runs only (replay_logic's SPILL_READ_STEER rule).
UNVERIFIED_RETIRED = "unverified (no parseable verdict)"


def _unverified_anchor(text):
    """The 'no verdict' text this prompt actually carried, or ``None``."""
    for anchor in (prompts.load("unverified_step").strip(), UNVERIFIED_RETIRED):
        if anchor and anchor in text:
            return anchor
    return None


def cases_unclosed_verdict(row, cap, ws, limit):
    """The coder's re-nudge after a step critic whose verdict was lost to one absent closing brace.

    What the coder read was cria saying it had no verdict. What it would read now is the judge's OWN
    ``reason`` and ``proposed_fix``, because the verdict object it wrote is recoverable by supplying
    closers.

    Driven through cria's own code and nothing else: the critic's captured reply goes through
    :func:`loop.verdict_from_unclosed` (the one-way gate, so an unclosed APPROVAL yields no case at
    all) and the result through :func:`loop._verdict_nudge` (the same function the live re-nudge
    calls). Nothing is transcribed; revert the fix and the same driving produces no case.

    PAIRING is by call ORDER, which is the only record of it on disk, and it is strict: the case is
    a coder prompt carrying the no-verdict text whose most recent critic call BOTH failed cria's
    reader AND is recovered by the gate. A readable critic verdict in between ends the pairing —
    that coder turn is about a verdict cria did read, and recomposing it would splice this fix's
    text into another call's slot.

    DISCLOSED: on a capture that predates the prompt-wording fix, the shipped text is the retired
    bookkeeping line, so the diff carries TWO changes — that wording fix and this one. Said in the
    case's own ``why`` rather than left for the reader to infer."""
    pending = None                       # the recovered verdict of the most recent critic call
    out = []
    for f in sorted(cap.glob("*.json")):
        if f.name.endswith(".response.json"):
            continue
        kind = f.name.split("-", 1)[-1].replace(".json", "")
        resp = f.with_name(f.name.replace(".json", ".response.json"))
        if kind.startswith("critic") and "confirm" not in kind:
            pending = None
            try:
                j = json.loads(resp.read_text())
            except (OSError, ValueError):
                continue
            ch = (j.get("choices") or [{}])[0]
            if ch.get("finish_reason") == "length":
                continue                 # refused before the reader — never a case
            text = _msg_text(ch.get("message") or {})
            if replay_logic.extract_json_object(text) is not None:
                continue                 # cria read this one fine; the pairing is broken
            pending = (f.name, loop.verdict_from_unclosed(text, "done", _QuietLog(), "critic"))
            continue
        if "coder" not in kind or pending is None or pending[1] is None:
            continue
        try:
            body = (json.loads(f.read_text()).get("body") or {})
        except (OSError, ValueError):
            continue
        if not body.get("messages"):
            continue
        old = next((a for m in body["messages"] if (a := _unverified_anchor(_msg_text(m)))), None)
        if old is None:
            continue
        new = loop._verdict_nudge(pending[1], False)
        if not new.strip():
            continue
        why = (f"the critic at {pending[0]} wrote a verdict cria could not read; "
               f"verdict_from_unclosed recovers it and _verdict_nudge renders the coder-facing text")
        if old == UNVERIFIED_RETIRED:
            why += ("; NOTE the shipped text is the RETIRED bookkeeping line — this diff therefore "
                    "carries the later prompt-wording fix as well as this one")
        out.append(Case("unclosed-verdict", f, row.get("model", "?"), body, old, new, why, ws,
                        {"reason": str(pending[1].get("reason") or ""),
                         "fix": str(pending[1].get("proposed_fix") or "")}))
        pending = None
        if len(out) >= limit:
            break
    return out


class _QuietLog:
    """A run log that swallows the trace. This harness prints the recomposition itself; the event is
    cria's, for a live run's record, and duplicating it here would read as a second firing."""

    phase = ""

    def emit(self, *_a, **_kw):
        pass


def _fact_unclosed_verdict(case: Case, msg: dict) -> dict:
    """Does the reply act on the diagnosis it was handed? Byte checks against the recovered verdict
    — the words are in the recomposed text and, being the judge's own, nowhere else in the prompt."""
    blob = signature(msg) + json.dumps(calls_of(msg))
    words = [w for w in re.findall(r"[\w./{}-]{5,}", case.facts.get("fix", ""))
             if w not in case.old]
    return {"echoes_a_token_of_the_proposed_fix": [w for w in dict.fromkeys(words) if w in blob][:6],
            "answers_with_prose_only": not msg.get("tool_calls")}


_URL_IN_FILE = re.compile(r"https?://[^\s\"'<>)]{12,}")
# A tool result cria wrote ENTIRELY: the path, then the corpus-stable phrase, at the very start.
_REFUSED_WHOLE_READ = re.compile(r"(\S+)\s+" + re.escape(replay_logic.SPILL_READ_STEER))


def cases_spill_read_small(row, cap, ws, limit):
    """A whole read of a SMALL spilled file that was refused, recomposed by RUNNING cria's own
    lowered read command against the archived file.

    The `new` string is not composed here at all. A synthetic ``read_file`` completion for the path
    the coder actually asked for goes through :func:`writeproxy.translate_outbound` — the real entry
    point, the real guard chain — and the shell command it lowers is EXECUTED with the cwd set to the
    archived workspace, exactly as the harness would run it. Its stdout is what the coder would now
    receive. Nothing is transcribed, and if the fix were reverted the very same driving would produce
    the refusal again and the case would report itself IDENTICAL.

    Only the SEARCH-RESULT population can be built here, and that is not a limitation of the harness:
    :func:`replay_logic.check_spill_read_small` measured five small files across the 96 runs and every
    one of them is saved search results. They are the population with no outline at all — a shell
    pipeline writes them, so cria never holds them parsed — which is why "grep it for what you need"
    left the coder with nothing to grep FOR.
    """
    if ws is None:
        return []
    out, seen = [], set()
    for call, body in coder_bodies(cap):
        if len(out) >= limit:
            break
        hit = rel = None
        for m in body.get("messages", []):
            t = _msg_text(m).strip()
            # The refusal must be the WHOLE tool result — cria wrote every byte of it. A message
            # that merely CONTAINS the phrase (an inventory, the coder quoting it back) would have
            # the recomposition spliced into someone else's text. Anchored at the start on the
            # corpus-stable phrase, never the current template's closing sentence.
            m2 = _REFUSED_WHOLE_READ.match(t) if m.get("role") == "tool" else None
            if m2:
                hit, rel = t, m2.group(1)
                break
        if hit is None:
            continue
        if rel in seen:            # the refusal is durable and rides in every later prompt
            continue
        seen.add(rel)
        target = (ws / rel.lstrip("./")).resolve()
        if not target.is_file():
            NOTES.append(f"the refused spill file is not in the archive ({rel})")
            continue
        size = target.stat().st_size
        if size > writeproxy.READ_INLINE_MAX:
            NOTES.append(f"the refused spill file is genuinely oversized ({size} bytes) — the fix "
                         f"does not touch it")
            continue
        # cria's OWN code decides what the coder now gets: translate_outbound lowers the call, the
        # shell runs it in the archived workspace. No text is written here.
        comp = {"choices": [{"message": {"tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "read_file", "arguments": json.dumps({"path": rel})}}]}}]}
        with _cwd(ws):
            writeproxy.translate_outbound(
                comp, {"name": "shell", "parameters": {"properties": {"command": {"type": "string"}},
                                                       "required": ["command"]}},
                injected={"read_file"}, workspace_root=os.getcwd())
            lowered = json.loads(
                comp["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"])
            cmd = lowered.get("command") or lowered.get("cmd")
            proc = subprocess.run(["bash", "-c", cmd[-1] if isinstance(cmd, list) else cmd],
                                  capture_output=True, text=True, cwd=os.getcwd())
        if proc.returncode != 0:
            NOTES.append(f"cria's lowered read still refuses {rel} (exit {proc.returncode}) — "
                         f"nothing to ask")
            continue
        # Strings that exist ONLY in the file, for the reply facts: the urls it lists. A model that
        # names one of these got it from the recomposed text and from nowhere else in the prompt.
        prompt_blob = "".join(_msg_text(m) for m in body.get("messages", []))
        only_here = [u for u in dict.fromkeys(_URL_IN_FILE.findall(proc.stdout))
                     if u not in prompt_blob][:12]
        out.append(Case("spill-read-small", call, row.get("model", "?"), body, hit, proc.stdout,
                        f"writeproxy.translate_outbound lowered a read_file of {rel} and the "
                        f"command was RUN in the archived workspace ({size} bytes)", ws,
                        {"path": rel, "bytes": size, "only_in_the_file": only_here}))
    return out


RECOMPOSERS = {
    "unclosed-verdict": cases_unclosed_verdict,
    "spill-read-small": cases_spill_read_small,
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


def build_cases(fix, data, n, per_run):
    """The cases for one fix, built offline. Returns (sendable, built, identical)."""
    cases, unchanged, built = [], 0, 0
    for row, cap, ws in data:
        if len(cases) >= n:
            break
        try:
            got = RECOMPOSERS[fix](row, cap, ws, per_run)
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
            elif len(cases) < n:
                cases.append(c)
    return cases, built, unchanged


def report_case(fix, c, live, args) -> dict:
    """Print one case in full and ask the model. Returns the deterministic facts, for the summary."""
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
    tag = "" if was == live else "  ← DIFFERENT MODEL — label the reading"
    if c.facts.get("same_model"):
        tag = "  ← SAME MODEL"
    print(f"── {c.session}/{c.call.name}  (captured against {was} [{c.model}]; replayed "
          f"against {live}{tag})")
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

    # A finding cria drops from the gate block can still ride in a DIFFERENT cria surface of
    # the same prompt — the ⟦ctx:steer⟧ ground-truth block is built by proberun from the same
    # probe report, and this harness recomposes only the gate block. Today's code filters
    # both through the one predicate (probeparse.parse_output applies it to every finding),
    # so when this fires the case UNDERSTATES the fix. Say it rather than let a reader
    # conclude the model ignored the change.
    # Matched on the checker's MESSAGE, with cria's own location prefix stripped: the same
    # finding is rendered with a different location in each surface (`file:41:15:` in the
    # gate block, `file:41:` in the steer), so matching the whole line finds nothing and
    # reports a clean isolation that isn't one.
    def _msg_of(s):
        return probegate._LOC_PREFIX.sub("", s.strip()).strip()

    kept = {ln.strip() for ln in _finding_lines(c.new)}
    carriers = {}
    for ln in _finding_lines(c.old):
        s = ln.strip()
        if s in kept or len(_msg_of(ln)) < 15:
            continue
        for m in body_new.get("messages", []):
            if _msg_of(ln) in _msg_text(m):
                carriers.setdefault(s, []).append(m)
    if carriers:
        print(f"   NOTE {len(carriers)} dropped finding(s) still reach the model elsewhere in this "
              f"prompt — the case UNDERSTATES the fix. Where each one still is:")
        for s, msgs in list(carriers.items())[:4]:
            # WHOSE text is still carrying it decides whether the fix could ever have removed it: a
            # cria surface this harness does not recompose is an artefact of the harness; the CODER's
            # own checker output is not cria's to filter and would still be there in a live run.
            where = []
            for m in msgs:
                t = _msg_text(m).strip()
                mine = t.startswith("⟦ctx:") or "⟦ctx:" in t[:200]
                where.append(f"{m.get('role')}:{'a cria surface' if mine else t[:40]!r}")
            print(f"     · {s[-70:]!r} in {len(msgs)} message(s): " + " | ".join(where[:3]))
    show_diff(c.old, c.new, args.detail)
    for cls in difference_classes(c.old, c.new):
        print(f"   · {cls}")
    if hits == 0:
        print("   the shipped text was not found in the body — not sent.\n")
        return {}
    if args.dry_run:
        print()
        return {}
    fact_fn = FACTS[fix]
    show_reply("CAPTURED at run time (from disk)", captured_reply(c.call), args.detail)
    try:
        # BOTH prompts, --sends times each. A weak model at its own sampling moves on its own, and
        # a single old reply against a single new one cannot tell that apart from the change. Two
        # sends can only ever say "not deterministic"; four begin to say how wide the spread is.
        olds = [ask(c.body) for _ in range(args.sends)]
        news = [ask(body_new) for _ in range(args.sends)]
    except Exception as e:  # noqa: BLE001
        print(f"   upstream error: {type(e).__name__}: {e}\n")
        return {}
    o_sigs = [signature(m) for m in olds]
    n_sigs = [signature(m) for m in news]
    stable = len(set(o_sigs)) == 1 and len(set(n_sigs)) == 1
    for i, m in enumerate(olds):
        if i == 0 or o_sigs[i] not in o_sigs[:i]:
            show_reply("REPLAY of the prompt AS IT SHIPPED" if i == 0
                       else f"...the SAME old prompt, send {i + 1}", m, args.detail)
    for i, m in enumerate(news):
        if i == 0 or n_sigs[i] not in n_sigs[:i]:
            show_reply("REPLAY of the RECOMPOSED prompt" if i == 0
                       else f"...the SAME recomposed prompt, send {i + 1}", m, args.detail)
    # The ACTION separately from the whole reply. A sampled model rewrites its reasoning every send
    # while asking for the identical tool call, so signature-level "4 distinct replies" can sit on
    # top of one stable action — and the action is what the run's next turn is built from. Both are
    # byte facts; neither is a score.
    o_acts = [json.dumps(calls_of(m), sort_keys=True) for m in olds]
    n_acts = [json.dumps(calls_of(m), sort_keys=True) for m in news]
    print("  ── facts")
    print(f"     distinct ACTIONS (tool name + arguments, ignoring wording): "
          f"{len(set(o_acts))} old / {len(set(n_acts))} new; "
          f"{len(set(o_acts) & set(n_acts))} action(s) taken on BOTH sides")
    print(f"     {args.sends} send(s) of each prompt · the model is "
          f"{'DETERMINISTIC' if stable else 'NOT deterministic'} here — "
          + (f"every send of a prompt agreed ({len(set(o_sigs))} distinct old, "
             f"{len(set(n_sigs))} distinct new)" if stable else
             f"a prompt sent {args.sends}× gave {len(set(o_sigs))} distinct old and "
             f"{len(set(n_sigs))} distinct new replies, so read each column as SAMPLES"))
    overlap = sorted(set(o_sigs) & set(n_sigs))
    print(f"     replies byte-identical old vs new: first-send {o_sigs[0] == n_sigs[0]}; "
          f"{len(overlap)} of {len(set(o_sigs) | set(n_sigs))} distinct replies appear on BOTH sides")
    labelled = [(f"old  #{i + 1}", m) for i, m in enumerate(olds)] + \
               [(f"new  #{i + 1}", m) for i, m in enumerate(news)]
    for label, msg in labelled:
        f = {**base_facts(msg), **fact_fn(c, msg)}
        print(f"     {label}: " + "  ".join(f"{k}={v}" for k, v in f.items()
                                            if v not in (None, [])))
    print()
    return {"fix": fix, "model": c.model, "case": f"{c.session}/{c.call.name}",
            "deterministic": stable, "distinct_old": len(set(o_sigs)),
            "distinct_new": len(set(n_sigs)), "first_send_identical": o_sigs[0] == n_sigs[0],
            "shared_replies": len(overlap), "sampling": sampling,
            "acts_old": len(set(o_acts)), "acts_new": len(set(n_acts)),
            "acts_shared": len(set(o_acts) & set(n_acts))}


def _attribute(data, aliases):
    """(by model, excluded) — every run placed under the model that produced it, or set aside."""
    by_model, excluded, how = defaultdict(list), [], defaultdict(Counter)
    for row, cap, ws in data:
        name, why = origin_model(row, cap, aliases)
        if name is None:
            excluded.append((cap.name, why))
            continue
        by_model[name].append((row, cap, ws))
        how[name][why] += 1
    return by_model, excluded, how


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", choices=sorted(RECOMPOSERS), action="append")
    ap.add_argument("--n", type=int, default=3, help="cases per fix (a few READ beats many counted); "
                                                     "with --same-model, cases per fix PER MODEL")
    ap.add_argument("--per-run", type=int, default=1, help="cases taken from any one captured run")
    ap.add_argument("--sends", type=int, default=2,
                    help="how many times each prompt is sent, per side (2 can only say 'not "
                         "deterministic'; 4 begins to say how wide)")
    ap.add_argument("--detail", action="store_true", help="full replies and full diffs")
    ap.add_argument("--dry-run", action="store_true", help="build cases, call no model")
    ap.add_argument("--session", help="only captures from this session id")
    ap.add_argument("--oldest-first", action="store_true",
                    help="take cases from the earliest runs (default: the most recent, which are "
                         "the ones the walks read and the ones the current model ran)")
    ap.add_argument("--same-model", action="store_true",
                    help="ask each capture's OWN model: group the cases by origin model and load "
                         "that model before sending, one swap per model, restoring what was loaded "
                         "at the start. Without it every reply comes from whatever is on the GPU.")
    ap.add_argument("--models", help="comma-separated origin models to cover (--same-model only)")
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

    if not args.same_model:
        for fix in wanted:
            print(f"{'=' * 100}\n══ {fix}\n{'=' * 100}")
            NOTES.clear()
            cases, built, unchanged = build_cases(fix, data, args.n, args.per_run)
            for note in sorted(set(NOTES)):
                print(f"  · {sum(1 for x in NOTES if x == note)} run(s): {note}")
            if not cases:
                print(f"  no case with a recomposed difference ({built} built, {unchanged} "
                      f"identical)\n")
                continue
            print(f"  {built} case(s) recomposed; {unchanged} identical to what shipped; "
                  f"{len(cases)} sent to the model\n")
            for c in cases:
                report_case(fix, c, live, args)
        return

    # ---- same-model mode -------------------------------------------------------------------
    aliases = fleet_aliases()
    if not aliases:
        sys.exit(f"cannot read the fleet config at {FLEET_TOML} — without it a capture cannot be "
                 f"tied to a model, and guessing is the one thing this harness must not do")
    by_model, excluded, how = _attribute(data, aliases)
    print("── every captured run placed under the model that produced it")
    for name in sorted(by_model):
        print(f"   {name:17s} {len(by_model[name]):3d} run(s) — "
              + "; ".join(f"{n} {why}" for why, n in how[name].most_common()))
    for cap_name, why in excluded:
        print(f"   EXCLUDED {cap_name}: {why}")
    if not excluded:
        print("   0 runs excluded — every run's two records agree")
    print()

    picked = [m.strip() for m in args.models.split(",")] if args.models else sorted(by_model)
    plan, order = {}, []
    for name in picked:
        if name not in by_model:
            print(f"── {name}: no captured run is attributed to it — skipped")
            continue
        if name in ladder_status.BLOCKED_ON_TOOLING:
            print(f"── {name}: BLOCKED ON TOOLING, not asked — "
                  f"{ladder_status.BLOCKED_ON_TOOLING[name][:110]}…")
            continue
        print(f"{'=' * 100}\n══ building cases from {name}'s own captures "
              f"({len(by_model[name])} runs)\n{'=' * 100}")
        per_fix = {}
        for fix in wanted:
            NOTES.clear()
            print(f"  ── {fix}")
            cases, built, unchanged = build_cases(fix, by_model[name], args.n, args.per_run)
            for note in sorted(set(NOTES)):
                print(f"    · {sum(1 for x in NOTES if x == note)} run(s): {note}")
            print(f"    {built} recomposed, {unchanged} identical to what shipped, "
                  f"{len(cases)} sendable")
            for c in cases:
                c.facts["same_model"] = True
            if cases:
                per_fix[fix] = cases
        if per_fix:
            plan[name] = per_fix
            order.append(name)
    if args.dry_run:
        print("\n── dry run: nothing sent, no model swapped")
        for name in order:
            for fix, cases in plan[name].items():
                print(f"   {name:17s} {fix:20s} {len(cases)} case(s)")
                for c in cases:
                    print(f"        {c.session}/{c.call.name}")
        return
    if not order:
        print("\nno sendable case on any selected model.")
        return

    # The GPU holds one model; whatever was on it when this started goes back on when it ends,
    # including on a crash — a harness that leaves the fleet in a different state than it found it
    # has changed the thing the next run measures.
    start_name = aliases.get(live)
    restored = {"done": False}

    def restore():
        if restored["done"]:
            return
        restored["done"] = True
        if not start_name:
            print(f"\n!! COULD NOT RESTORE: the model loaded at start ({live!r}) is not named in "
                  f"{FLEET_TOML}. The GPU now holds {loaded_model()!r}.")
            return
        ok, msg = ensure_loaded(start_name, aliases)
        print(f"\n── restoring the model that was loaded at start: {msg}"
              + ("" if ok else "  !! RESTORE FAILED"))

    atexit.register(restore)
    # atexit alone is not enough: a `timeout`/Ctrl-C kill delivers SIGTERM/SIGINT, which ends the
    # process WITHOUT running atexit, and the fleet is then left holding whatever model was mid-run.
    # Measured the hard way — one killed run left mellum2 loaded. Raising SystemExit from the handler
    # unwinds through the `finally` below, so the restore happens on every exit path there is.
    def _bail(signum, _frame):
        raise SystemExit(f"interrupted by signal {signum}")

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, _bail)
    summary = []
    try:
        for name in order:
            print(f"\n{'=' * 100}\n══ ASKING {name} — the model these captures came from\n"
                  f"{'=' * 100}")
            ok, msg = ensure_loaded(name, aliases)
            print(f"   {msg}")
            if not ok:
                print(f"   SKIPPED: {name} could not be loaded, so none of its cases were asked")
                continue
            got = loaded_model()
            for fix, cases in plan[name].items():
                print(f"\n{'-' * 100}\n── {fix} · {len(cases)} case(s) from {name}\n{'-' * 100}")
                for c in cases:
                    row = report_case(fix, c, got, args)
                    if row:
                        summary.append(row)
    finally:
        restore()

    print(f"\n{'=' * 100}\n══ what was asked, and of whom (facts only — the reading is yours)\n"
          f"{'=' * 100}")
    for r in summary:
        print(f"   {r['model']:17s} {r['fix']:20s} {r['case']:46s} "
              f"{'deterministic' if r['deterministic'] else 'NOT deterministic'} "
              f"({r['distinct_old']} distinct old / {r['distinct_new']} distinct new of "
              f"{args.sends}); actions {r['acts_old']}/{r['acts_new']}, "
              f"{r['acts_shared']} on both sides; {r['shared_replies']} reply(s) on both sides")
    for name in sorted({r["model"] for r in summary}):
        rows = [r for r in summary if r["model"] == name]
        det = sum(1 for r in rows if r["deterministic"])
        print(f"   ── {name}: {det}/{len(rows)} case(s) deterministic at the captures' own "
              f"sampling {rows[0]['sampling']}")


if __name__ == "__main__":
    main()
