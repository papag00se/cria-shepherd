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


# Read-family tool names, matched by shape so this stays harness-agnostic (read_file, view_file,
# open_file, Cline's read, …). editrecovery may NOT import writeproxy (writeproxy imports it), so the
# shape rule lives here rather than reaching for writeproxy's _READ_NAMES.
def _is_grounded_in(prior_msgs: list, path: str) -> bool:
    """True when the coder already has THIS file's real bytes in context — it read the file, or it
    wrote the file itself. A blind touch (edit/write of a file never read or written this session) is
    the case where surgical mismatch-windows cannot help: the coder has no basis to pin an old_string
    outside the window cria happens to show, so it re-guesses. Stateless, reconstructed from history."""
    base = os.path.basename(path or "")
    if not base:
        return True  # can't identify the file → do not force early escalation
    if _wrote_since(prior_msgs, path):
        return True  # the coder produced this file's content, so it is not blind to it
    for m in prior_msgs:
        if not isinstance(m, dict) or m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            name = str(fn.get("name") or "").lower()
            if "read" not in name and "view" not in name and "open" not in name:
                continue
            args = fn.get("arguments")
            hay = args if isinstance(args, str) else str((args or {}).get("path") or "")
            if base in hay:
                return True
    return False


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


def compose(fail: dict, prior: int, grounded: bool = True) -> str:
    """The ONE directive for an edit failure, given the file's prior edit-steer count. Monotonic:
    surgical first, then a single committed whole-file-rewrite escalation. When ``grounded`` is False
    (a blind touch — a file the coder never read or wrote this session), the "can't pin the text"
    family escalates on the FIRST miss instead of the third: surgical windows cannot help a coder that
    has no copy of the file, so it is handed the whole current file at once rather than re-guessing an
    old_string two more times. Measured origin: cart-billing-go x gigachat31 confabulated cart.go's
    body and ground its way through repeated window-only mismatches before the whole file appeared."""
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
    if prior + 1 >= ESCALATE_AFTER or not grounded:
        # COMMITTED escalation: stop editing this file, rewrite it whole from the exact bytes shown. One
        # directive from here on — no "copy the exact text" that the model keeps failing to do.
        #
        # …UNLESS the bytes were too big to travel. writeproxy drops `current` from the report rather
        # than let it exceed the harness's per-result budget, because the alternative is what shipped
        # before: a ~13.7 KB base64 payload, middle-cut by the harness INSIDE the base64, that then
        # fails to decode and reaches the coder as a 10 KB wall of noise. Measured on maple-preview
        # 1786138747: `⟦ctx:edit⟧` appears ZERO times in the whole 105-call run while the raw marker
        # appears 13 times — the recovery never ran once, on the files where edits fail most.
        # A directive to go read the file is worth something; an empty quote block is worth less
        # than nothing.
        return (report("escalate", prior=prior + 1, cur=cur) if cur
                else report("escalate_unread", prior=prior + 1, path=path))
    # Surgical (early failures): hand over the exact text to copy, or point at the current file.
    if anchor:
        # THE LINE NUMBER, not just the window. A quoted snippet that appears twice in the file
        # cannot tell the model WHICH copy it mistyped, and the six-language battery caught a coder
        # resubmitting a byte-identical old_string three times against a hint that showed it text it
        # believed it already had. The divergence index is computed where the mismatch is found; it
        # only has to be carried out.
        # NO LINE, NO CLAIM ABOUT A LINE. This filled the same template with "?" when the divergence
        # index was absent, so cria told the coder "your copy first differs from the file at LINE ?"
        # and "line ? is where your copy is wrong". nemotron-elastic/java 0031 answered "But we need
        # to find exact line. Let's view file again" and spent the rest of the run looking for a line
        # cria had never located. The two situations get two messages (#4: the fallback that printed
        # a placeholder where a fact belongs is deleted, not reworded).
        line = fail.get("line")
        if line in (None, "", 0):
            return report("anchor_noline", anchor=anchor)
        return report("anchor", anchor=anchor, line=line)
    return report("no_anchor")


def recover(content: str, prior_msgs: list, rlog=None) -> str:
    """If ``content`` is a heredoc edit-FAIL fact-report, compose the one directive (keyed on the file's
    prior edit-steer count in ``prior_msgs``). Otherwise return it unchanged — non-edit-fail results
    (write refusals, real errors) pass straight through."""
    i = content.find(EDITFAIL)
    if i < 0:
        return content
    # FIND, NOT STARTSWITH — the same lookup :func:`summarize` has always used, for the same marker,
    # in the same module. They disagreed, and that disagreement silently killed this function.
    #
    # `_strip_exec_envelope` was taught on 2026-08-26 to KEEP the harness's `Warning: truncated
    # output (original token count: N)` line above the payload, so the coder is told the report is a
    # piece. Correct, and it put one line in front of the marker — which is all it took: the guard
    # here was positional, so every edit miss that came back with a cut warning skipped recovery and
    # handed the coder 3,200 characters of base64 instead of "your copy first differs at LINE 53".
    #
    # Measured on shipping-rates-rb x nemotron-elastic 1787950133, found twice in one walk. At 0047
    # and again at 0081 the coder read the warning as a fact about its OWN edit — 0086: "The previous
    # edit we made was to add the require "countries" line but it got truncated." It then spent calls
    # 0086, 0087, 0089 and 0090 re-reading the file to settle a question cria had already answered,
    # and the blob rode every prompt from 0081 to 0091. The contrast is in the same run: at 0036 and
    # 0085 there was no warning, `startswith` matched, and the directive landed.
    #
    # Whatever preceded the marker is kept in place — the warning is still true and still wanted; it
    # simply belongs ABOVE the directive rather than in front of a prefix test.
    head, rest = content[:i], content[i + len(EDITFAIL):]
    try:
        fail = json.loads(base64.b64decode(rest.strip()).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        # A REPORT THAT WAS REALLY CUT STILL MUST NOT SHIP AS BASE64. Returning `content` unchanged
        # is what leaked the blob for ten calls; the marker proves an edit_file failed, so cria can
        # always say that much in words even when it can no longer say which line (#5, #5b).
        return head + prompts.load("editfail_unreadable")
    path = fail.get("path") or ""
    prior = _prior_edit_steers(prior_msgs, path)
    grounded = _is_grounded_in(prior_msgs, path)
    # TELEMETRY (provenance audit 2026-08-04): the whole-file escalation had no event at all — its
    # window-fill cost on dense models (both gemma4 0/4s compacted mid-run under forced rewrites)
    # was uncountable from the logs. The event makes the re-measure possible. `blind` marks the
    # first-miss escalations this change added, so their prevalence and cost are measurable apart
    # from the count-driven ones.
    # `identical` is self-resolving (old_string == new_string) and `compose` answers it BEFORE the
    # escalation clock, so the blind-touch early escalation must not fire for it either — only the
    # count clock does (a high prior on identical still emits, unchanged).
    self_resolving = ("phantom", "would_break", "multi", "multi_flex")
    escalates = (prior + 1 >= ESCALATE_AFTER) or (not grounded and fail.get("mode") != "identical")
    if rlog is not None and escalates and fail.get("mode") not in self_resolving:
        rlog.emit("editrecovery.escalated", path=os.path.basename(path),
                  fails=prior + 1, blind=not grounded)
    return head + compose(fail, prior, grounded)


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
