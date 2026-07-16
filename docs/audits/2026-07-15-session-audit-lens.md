# Audit Lens — long-session behavior (2026-07-15)

Seeded by a real 98-turn plan-off (direct-coder) session: history grew monotonically
34→331 messages / ~35K tokens (no harness compaction), a reframed compaction summary
anchored msg[3] every turn, the model circled on a broken `pyproject.toml`, guards fired
~7× — all without errors. Four orthogonal lenses ran in parallel; every acted-on finding
was verified against the code.

## Fixed (verified + tested)

- **D1 — write/edit false-success reframe.** The empty-result "Wrote {path}" reframe fired
  on any blank tool result for a write/edit id; a *successful* silent write and a *failed*
  one (error on stderr) both look blank, and `edit_file` failure is blank while its success
  is not — so a failed edit could be reported as success. Fix: write/edit now print a
  positive success token (`⟦cria:wrote⟧`); the reframe keys on the token, so a blank/error
  result is left untouched and the model sees the real failure. (Subsumes D2, the
  `id=None` empty-collision.) `cria/writeproxy.py`.
- **B1 — floor could drop the anchor.** `_protected_mask` protected only system + the
  active turn, so drop-oldest could trim the `⟦cria:briefing⟧` handoff a follow-up
  re-reads. Fix: protect any message carrying a cria anchor marker.
  `cria/contextfloor.py`. (Deliberately NOT protecting the reframed compaction *summary* —
  it's redundant with the actual work messages still in history.)
- **B2 — content_reduce could truncate the ground truth.** Unlike focus-trim, the floor's
  `_reduce_tool_outputs` had no gate-probe exemption. Fix: skip tool results carrying
  `___CRIA_GATE_`. `cria/contextfloor.py`.
- **C1 — GuardStore leak/unbounded.** `GuardStore` was unbounded and NOT `_stable_session`
  gated, so two header-less conversations opening with the same text shared one
  `GuardState` (one's held "done"/probe forwardable into the other). Fix: unstable
  (`task:`) keys get a fresh memory-less state per turn; stable (`sid:`) keys persist and
  the store is bounded like `_shapes`. Consequence (accepted): header-less clients lose
  cross-turn guarding + the completion gate — those keys can't persist without the leak.
  `cria/loop.py`.
- **A3 + A1 — reframe_compaction robustness.** Blind to list-shaped content
  (`isinstance str`), and on a drifted/absent boundary it wrapped the whole "another
  language model…" preamble inside "this is YOUR OWN work". Fix: match via
  `_msg_text_content`; on an absent boundary, strip up to the marker's own line-end.
  `cria/loop.py`.

## Deferred — scoped, with rationale (NOT fixed)

- **C2 — plan-off repetition redirect can over-fire** on a healthy multi-file test sweep
  whose commands share a path token (`pytest app/test_a.py` vs `…test_b.py`), because the
  reasoner that mediates the intentional bias-to-fire is loop-only. **Deferred:**
  `_actions_match` is heavily tuned across documented rounds; the seed session showed the
  *opposite* (under-firing), and tightening risks regressing real-loop detection. Trigger
  to revisit: a live session where a legit sweep gets misdirected.
- **C3 — a genuinely-absent probe result (non-compaction) fails open to an unverified
  "done".** **Deferred:** fail-open is a deliberate anti-wedge posture; re-nudging risks
  wedging when the harness genuinely can't run the probe (which the user weights higher than
  a rare false-complete). `guard_probe_reissue` already recovers the compaction case.
- **B3 — `_drop_protected_overflow` is O(n²)** on a large protected span. Latent (lever
  fires only when the protected span alone is over budget). Trigger: if protected-overflow
  becomes hot on very large histories.
- **D3 — `_repair_double_escaped`** rewrites a legit single-line file containing literal
  `\n` (minified JS/JSON, a one-line fixture). Known codex-local port tradeoff.
- **A5 — the reframed compaction summary never ages its "don't redo" assertion**; ~300
  messages stale it still says "already done — don't recreate." Prompt-tuning, not a code
  bug.

## Reassuring negatives (verified clean)

No tool-result orphaning in any floor/focus-trim removal path; tool-schema bounding never
drops a synthetic tool (only truncates descriptions); the sentinel/base64 is never
*partially* truncated (floor reduces tool OUTPUTS, not assistant tool_call args); heredoc
terminators can't collide with base64; `represent_inbound` is stateless and idempotent;
web_search native rename is symmetric; the shape store IS `_stable_session`-gated (so the
A2 shape-leak concern was down-rated — the real leak was C1); tokenratio cold-start is
covered by the overflow refit-retry.

## Effectiveness opportunities (not bugs — the biggest levers)

1. **cria doesn't compact its own plan-off path** → the coder wades through an
   ever-growing history (331 msgs here). A mid-session rolling summary would keep it lean.
2. **Ground truth reaches the model too rarely** — the gate only fires on a done-claim or
   guard trip, so an acting-heavy model circles with little feedback. A periodic gate every
   N acting turns would surface ground truth far sooner (the TOML floor added earlier only
   helps *when* the gate runs).

669 tests green (+8 for the fixes).
