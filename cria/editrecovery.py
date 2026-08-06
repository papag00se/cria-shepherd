"""The single EDIT-RECOVERY assist — one owner, many triggers.

The edit-failure guidance used to be scattered across the writeproxy heredoc's per-mode branches
(identical-edit → "REWRITE THE WHOLE FILE"; anchor-found → "do NOT rewrite, copy the exact text";
close-miss → "copy verbatim, don't rewrite"; …). Each branch was locally reasonable but HISTORY-BLIND,
so across a stuck session the model was told to rewrite and not-to-rewrite by turns — a whipsaw (one
live walk showed "do not rewrite the whole file" 80× vs "REWRITE THE WHOLE FILE" 11×).

Now the heredoc only does what it alone can — APPLY the edit (exact → whitespace-flexible) and, on a
miss, REPORT the facts as a ``⟦ctx:editfail⟧`` marker (mode + the file's real current bytes + the near
anchor). This module is the one place that turns that fact-report into a directive, keyed on the file's
own failure history (reconstructed statelessly from the conversation). The policy is MONOTONIC: surgical
guidance while failures are few, then a single COMMITTED escalation to a grounded whole-file rewrite —
no oscillation, and it commits to the action a weak model can actually complete (rewrite the whole file
from the exact bytes it's shown, rather than pin an ``old_string`` it keeps mis-copying).

Modes that are their own resolution (phantom = already-correct, would-break, non-unique match) are
answered directly regardless of history. The "can't pin the exact text" family (identical / anchor /
close / no-anchor) is the one that escalates.
"""
from __future__ import annotations

import base64
import json
import os

from . import prompts

# Heredoc → cria: a structured edit-FAILURE fact-report (base64 JSON follows the marker).
EDITFAIL = "⟦ctx:editfail⟧"
# cria → model: the composed directive. Carries the file's basename so this module can COUNT how many
# times it has already steered edits on that file (the escalation clock), statelessly from history.
EDIT_MARK = "⟦ctx:edit⟧"
# Surgical guidance for this many failures on a file; on the next one, COMMIT to the whole-file rewrite.
ESCALATE_AFTER = 3


def _tag(path: str) -> str:
    return f"{EDIT_MARK} {os.path.basename(path or 'the file')} — "


def _wrote_since(prior_msgs: list, path: str) -> int:
    """Index just past the coder's most recent SUCCESSFUL write of ``path`` (0 if it never landed one).
    Matched on the write-confirm line by basename, so a relative call and an absolute one still count as
    the same file."""
    head = prompts.render("write_confirm", path="").strip()
    base = os.path.basename(path or "")
    at = 0
    for i, m in enumerate(prior_msgs):
        if not isinstance(m, dict) or m.get("role") != "tool":
            continue
        for ln in str(m.get("content") or "").splitlines():
            ln = ln.strip()
            if base and ln.startswith(head) and os.path.basename(ln[len(head):].strip()) == base:
                at = i + 1
                break
    return at


def _prior_edit_steers(prior_msgs: list, path: str) -> int:
    """How many times this module has steered edits on ``path`` SINCE the coder last wrote it
    successfully — the clock that decides when to escalate to a whole-file rewrite.

    Counting a file's LIFETIME misses instead was a trap. Once a file crossed the threshold it stayed
    in forced-rewrite mode for the rest of the session, however well the model did afterwards — and a
    whole-file rewrite asks a small model to retype thousands of characters from memory, which is the
    one thing it is worst at. Measured in g18 (gemma4, ada-handles): 4 edit steers on test_resolve.py
    with 7 SUCCESSFUL writes interleaved, 5 of them after the threshold. cria kept ordering a ~2,000
    character retype, and one of those retypes silently reverted a one-character fix the model had
    already made — so it spent the rest of the run chasing a NameError that cria had reintroduced.
    A successful write is the model proving it can pin this file's text; the clock starts over.

    Stateless — reconstructed from the messages, so it survives a cria restart."""
    tag = _tag(path)
    return sum(1 for m in prior_msgs[_wrote_since(prior_msgs, path):]
               if isinstance(m, dict) and tag in str(m.get("content") or ""))


def compose(fail: dict, prior: int) -> str:
    """The ONE directive for an edit failure, given the file's prior edit-steer count. Monotonic:
    surgical first, then a single committed whole-file-rewrite escalation."""
    path = os.path.basename(fail.get("path") or "the file")
    cur = fail.get("current") or ""
    anchor = (fail.get("anchor") or "").strip("\n")
    head = _tag(path)

    def report(key: str, **tokens: object) -> str:
        # bodies live in prompts/editfail_reports.txt; content tokens (anchor/cur) fill LAST so a
        # value that happens to contain a {{TOKEN}} pattern can't be re-substituted.
        return head + prompts.fill(prompts.load_map("editfail_reports")[key], **tokens)

    mode = fail.get("mode")
    # Self-resolving modes — answered the same way regardless of history (no escalation clock).
    if mode == "phantom":
        return report("phantom", anchor=anchor)
    if mode == "would_break":
        return report("would_break", path=path, err=fail.get("err", "it no longer parses"))
    if mode in ("multi", "multi_flex"):
        return report("multi", n=fail.get("n", "several"), path=path)
    if mode == "identical":
        # SELF-RESOLVING, and it must be answered BEFORE the escalation clock. old_string ==
        # new_string is complete information on its own: the model does not need the file's bytes,
        # it needs to be told its two arguments are the same string. Walked on
        # ada-handles_nemotron-elastic_codex_pon_1785888803 calls 0160-0165: five consecutive
        # identical-string edits, every one answered with the escalate body ("you have failed to
        # edit this file 3 times — you cannot pin its exact current text. STOP editing it. Here is
        # its EXACT current content on disk") because the file's failure count had already passed
        # ESCALATE_AFTER. The coder read the diagnosis, believed its problem was stale text, and
        # answered by trying harder to pin the text — re-reading, re-dumping, view_image on a .py —
        # for five turns, while the 145-line file body was re-injected nine times. On the sibling
        # file, whose clock was clean, the SAME mistake got the correct one-line answer at 0166.
        return report("identical")

    # The "can't pin the exact current text" family: anchor / close / no_anchor.
    if prior + 1 >= ESCALATE_AFTER:
        # COMMITTED escalation: stop editing this file, rewrite it whole from the exact bytes shown. One
        # directive from here on — no "copy the exact text" that the model keeps failing to do.
        return report("escalate", prior=prior + 1, cur=cur)
    # Surgical (early failures): hand over the exact text to copy, or point at the current file.
    if anchor:
        return report("anchor", anchor=anchor)
    return report("no_anchor")


def recover(content: str, prior_msgs: list, rlog=None) -> str:
    """If ``content`` is a heredoc edit-FAIL fact-report, compose the one directive (keyed on the file's
    prior edit-steer count in ``prior_msgs``). Otherwise return it unchanged — non-edit-fail results
    (write refusals, real errors) pass straight through."""
    if not content.startswith(EDITFAIL):
        return content
    try:
        fail = json.loads(base64.b64decode(content[len(EDITFAIL):].strip()).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return content
    prior = _prior_edit_steers(prior_msgs, fail.get("path") or "")
    # TELEMETRY (provenance audit 2026-08-04): the whole-file escalation had no event at all — its
    # window-fill cost on dense models (both gemma4 0/4s compacted mid-run under forced rewrites)
    # was uncountable from the logs. The event makes the re-measure possible; behavior unchanged.
    if (rlog is not None and prior + 1 >= ESCALATE_AFTER
            and fail.get("mode") not in ("phantom", "would_break", "multi", "multi_flex")):
        rlog.emit("editrecovery.escalated", path=os.path.basename(fail.get("path") or ""),
                  fails=prior + 1)
    return compose(fail, prior)


def summarize(content: str) -> str:
    """Collapse a raw ``⟦ctx:editfail⟧<base64>`` report to a ONE-LINE fact — for a REASONER session only.
    The base64 embeds the file's FULL current bytes: useless noise a reasoner can't decode (three such
    blobs were ~96K tokens of poison in a single verify prompt). The MODEL keeps the raw marker —
    :func:`recover` turns it into the recovery directive it actually needs. Unchanged if no marker."""
    i = content.find(EDITFAIL)
    if i < 0:
        return content
    rest = content[i + len(EDITFAIL):]
    b64 = rest.split(None, 1)[0] if rest.strip() else ""   # the report is one whitespace-free token
    tail = rest[len(b64):]
    try:
        fail = json.loads(base64.b64decode(b64).decode("utf-8"))
        path = os.path.basename(fail.get("path") or "a file")
        note = f"[edit_file on {path} did not apply (mode={fail.get('mode') or 'miss'}); cria gave the coder the exact fix]"
    except (ValueError, json.JSONDecodeError):
        note = "[edit_file did not apply; cria gave the coder the fix]"
    return content[:i] + note + tail


def rewrite_sanctioned(msgs: list, path: str) -> bool:
    """True when this module has ESCALATED ``path`` to a whole-file rewrite in the recent conversation —
    i.e. cria itself just told the model to rewrite this file. The wheel-spin guard checks this so it
    never flags a rewrite cria ordered as 'spinning' (punishing the model for obeying)."""
    tag = _tag(path)
    for m in reversed(msgs[-40:]):
        c = str((m.get("content") if isinstance(m, dict) else "") or "")
        if tag in c and "produce the corrected FULL file" in c:
            return True
    return False
