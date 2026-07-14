# Anomaly Sweep — loop-only capabilities missing from the plan-off/proxy path

**Date:** 2026-07-14 · **Type:** Anomaly Sweep (parity lens) · **Paths:** the plan LOOP
(`Loop.drive`/`_work`, planner on) vs the PLAN-OFF proxy (`_produce_completion` direct-coder
branch / `_produce_stream` / `_direct_coder_body`, planner off).

**Seed anomaly:** a plan-off session hit a harness compaction (Codex compacted ~103 KB → ~10 KB
mid-run); the model then read the lossy summary, treated its OWN prior work as "a previous
model's," couldn't find the test file it had written, and re-created a duplicate under a
different directory (`test_lambda.py` in root AND `tests/test_lambda.py`). cria HAS
harness-compaction-survival machinery — but it lives in the loop. Plus: the runaway guards were
loop-only until the recent guard refactor shared them. Lens: **what ELSE only lives in the loop
that the plan-off path equally needs?**

**Dimensions audited (4 parallel agents):** A verification / false-"done"; B compaction /
session survival; C per-turn completion hygiene; D recovery / escalation / streaming asymmetry.

## The pattern

Every layer cria uses to keep a small model on the rails was built loop-first and gated behind
`planner.enabled`. The guard refactor shared the **runaway guards**. This sweep finds the rest:
**verification, per-turn hygiene, and compaction-survival are all still loop-only** — the
plan-off coder (the user's path) runs without them. Root: `self.loop = None` unless
`planner.enabled` ([server.py:159-160](../../cria/server.py#L159)), so `observe_shape`,
`knows_session`, `_gate_op`, `_clean_completion`, `_strip_completion_banners`, `_compact_done`,
`prior_work` are **never referenced on the proxy path** (verified: 0 refs each).

## Tier 1 — model-agnostic, mechanically shareable (small extract-and-wire, like the guard refactor)

- [ ] **Completion gate on a plan-off "done" turn** — HIGH. A no-tool-call "done" is forwarded
  with ZERO ground-truth check ([server.py `_produce_completion`, the `if any(...tool_calls...)`
  has no else]). The loop runs the syntax floor + discovered repo probes on exactly that case
  (`_gate_op` → `_verify_after_probe`, loop.py:540/564). `guard_gate_op` is already
  `GuardState`-based and the plan-off `GuardStore` carries `gate_plan`, so it's shareable: on a
  no-tool direct-coder turn, emit the gate probe and, on the result, steer with the errors
  instead of letting a false "done, tests pass" through. **Objective (floor/probe) half only** —
  the reasoner critic stays loop-only.
- [ ] **`_clean_completion` — strip leaked reasoning from content when reasoning is OFF** — HIGH.
  LFM2-class models ignore the empty-think prefill and narrate in `content`; plan-off ships that
  raw to the harness (loop.py:518-519 cleans it via `role.clean_content`). Apply the routed coder
  role's clean after the guards. (Distinct from reasoning-FORWARDING, which is for reasoning-ON.)
- [ ] **LEG0 no-tools nudge** — MED/HIGH. A plan-off "done" that used no tools this turn should
  get one act-first nudge (a `GuardStore` flag) before forwarding (loop.py:531-537).
- [ ] **`_strip_completion_banners` + `_strip_cria_file_ops`** — MED. Scrub cria's own parroted
  `⟦cria⟧` banners from the forwarded completion (loop.py:516), and strip historical `.cria/`
  writes from the replayed history in `_direct_coder_body` (loop.py `_frame_for_item` does this;
  the direct-coder body doesn't) — bites resumed/compacted sessions.

## Tier 2 — structural: compaction survival on plan-off (the seed)

- **Lift the survival subsystem out of the planner gate** — HIGH impact, real refactor. Today
  `self.loop = None` unless the planner is on, so shape-recording (`observe_shape`), rewrite
  detection (`knows_session`), `LoopStore` persistence, and the `⟦cria:briefing⟧` completion
  briefing (`_compact_done`/`_closing`) NEVER run on plan-off. Lift shape-recording + rewrite
  detection into a plan-off-available store; emit a briefing on plan-off turn-end; inject the
  re-anchor frame in `_direct_coder_body` when a rewrite is detected. **This is the exact fix for
  the seed** (the duplicate-test-file incident) and is the same shape as the guard refactor.

## Tier 2/3 — latent / non-Codex / scoped

- **Streaming plan-off has no direct-coder branch** — HIGH for a non-Codex streaming client, LOW
  for the user. `_produce_stream` sends plan-off coding to a bare `_proxy_body` (no coder prompt,
  no guards, no hygiene). Codex drives via the buffered Responses path, so the user is
  unaffected. Mirror the buffered branch into `_produce_stream` (using `chat_watched`) if/when a
  streaming chat client matters. (DEFERRALS already notes this; now the 5 missing pieces are
  enumerated in the agent transcript.)
- **Classifier-gated plan-off** — MED. The direct-coder branch requires
  `classification.task_type=="coding"`; with no `[classifier]` configured, `classification` is
  None and plan-off falls to bare proxy. The user has a classifier, so latent. Broaden the
  trigger (tools-present + not-a-question).
- **Session-key reset on the plain-chat path** — MED (LOW for the user). `/v1/chat/completions`
  without a session header keys the stores on the content-derived root, which changes on a
  compaction → `GuardStore`/`StatsStore`/`TranslationStore` reset. The Codex/Responses path uses
  a stable `sid:{prompt_cache_key}` key, so the user's stores survive. Fix for non-Codex clients:
  a server-assigned session cookie.
- **Probe re-issue after a rewrite erases a guard probe** — LOW (loop has `probe_reissues`).

## NOT shared (plan-specific, by design)

- The reasoner critic (`_verify`) and reasoner-authored redirect — plan-off runs without a
  reasoner (uses canned steers). Only the objective probe/floor is shareable.
- Per-step advance discipline / no-cap re-prompt — there are no steps on plan-off.
- **Reverse asymmetry (bonus):** plan-off's coder DOES resolve through the failover chain
  (`_route`); the LOOP pins its coder to the local upstream, bypassing failover — so the loop
  lacks the coder cloud-escalation the plan-off path has.

## Posture check — what's RIGHT

- The runaway GUARDS (rumination / truncation / repetition / wheel-spin / probe round-trip) ARE
  shared — the guard refactor landed correctly; both paths run one implementation.
- The context floor / output budget is SYMMETRIC across both paths (verified non-finding) — no
  window/reserve divergence.
- The Codex/Responses session key is stable across a compaction, so the per-session stores
  (guard/stats/translation) survive on the user's path.
- Tool menu, cheatsheet/tool-hint, coder-role sampling, env-context reframing, text-answer
  recovery, and reasoning-forwarding are all shared.

This is a maturing system whose protections were built loop-first and are being progressively
shared. The sweep maps the remaining loop-only layers — verification, hygiene, compaction — not
a mess.

_Source transcripts: sweep agents A/B/C/D (session JSONL, 2026-07-14)._
