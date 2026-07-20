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

# Heredoc → cria: a structured edit-FAILURE fact-report (base64 JSON follows the marker).
EDITFAIL = "⟦ctx:editfail⟧"
# cria → model: the composed directive. Carries the file's basename so this module can COUNT how many
# times it has already steered edits on that file (the escalation clock), statelessly from history.
EDIT_MARK = "⟦ctx:edit⟧"
# Surgical guidance for this many failures on a file; on the next one, COMMIT to the whole-file rewrite.
ESCALATE_AFTER = 3


def _tag(path: str) -> str:
    return f"{EDIT_MARK} {os.path.basename(path or 'the file')} — "


def _prior_edit_steers(prior_msgs: list, path: str) -> int:
    """How many times this module has already steered edits on ``path`` (its directive tag appears in the
    conversation-so-far). Stateless — reconstructed from the messages, so it survives a cria restart."""
    tag = _tag(path)
    return sum(1 for m in prior_msgs
               if isinstance(m, dict) and tag in str(m.get("content") or ""))


def compose(fail: dict, prior: int) -> str:
    """The ONE directive for an edit failure, given the file's prior edit-steer count. Monotonic:
    surgical first, then a single committed whole-file-rewrite escalation."""
    path = os.path.basename(fail.get("path") or "the file")
    cur = fail.get("current") or ""
    anchor = (fail.get("anchor") or "").strip("\n")
    head = _tag(path)

    mode = fail.get("mode")
    # Self-resolving modes — answered the same way regardless of history (no escalation clock).
    if mode == "phantom":
        return (head + "that line already reads:\n---\n" + anchor + "\n---\nwhich is ALREADY what your "
                "new_string makes it. This change is DONE — do not edit that line again; your old_string "
                "just misremembers the current text. Move on: run the failing check and read the actual error.")
    if mode == "would_break":
        return (head + f"your edit would break {path} — {fail.get('err', 'it no longer parses')}. "
                "Fix new_string so the file stays valid, then edit again.")
    if mode in ("multi", "multi_flex"):
        return (head + f"old_string matches {fail.get('n', 'several')} places in {path} — add surrounding "
                "lines so it is unique, then edit again.")

    # The "can't pin the exact current text" family: identical / anchor / close / no_anchor.
    if prior + 1 >= ESCALATE_AFTER:
        # COMMITTED escalation: stop editing this file, rewrite it whole from the exact bytes shown. One
        # directive from here on — no "copy the exact text" that the model keeps failing to do.
        return (head + f"you have failed to edit this file {prior + 1} times — you cannot pin its exact "
                "current text. STOP editing it. Here is its EXACT current content on disk; produce the "
                "corrected FULL file in a single write_file call:\n---\n" + cur + "\n---")
    # Surgical (early failures): hand over the exact text to copy, or point at the current file.
    if anchor:
        return (head + "your old_string is not an exact match. The file actually reads:\n---\n" + anchor +
                "\n---\nCopy that text VERBATIM into old_string and edit again.")
    if mode == "identical":
        return (head + "old_string and new_string are identical — this edit changes nothing, and you "
                "cannot pin the exact current text. Read the file, then make one targeted edit.")
    return (head + "your old_string is not in the file (likely a stale copy). Read the file to get its "
            "exact current text, then make one targeted edit.")


def recover(content: str, prior_msgs: list) -> str:
    """If ``content`` is a heredoc edit-FAIL fact-report, compose the one directive (keyed on the file's
    prior edit-steer count in ``prior_msgs``). Otherwise return it unchanged — non-edit-fail results
    (write refusals, real errors) pass straight through."""
    if not content.startswith(EDITFAIL):
        return content
    try:
        fail = json.loads(base64.b64decode(content[len(EDITFAIL):].strip()).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return content
    return compose(fail, _prior_edit_steers(prior_msgs, fail.get("path") or ""))


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
