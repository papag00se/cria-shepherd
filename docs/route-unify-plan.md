# Route unification (D4b) — implementation plan

Make plan-off a **degenerate 1-item plan** so there is ONE driver (`Loop.drive`); the planner
becomes an internal on/off stage. `_drive_direct_coder` is already built on `loop.py`'s shared
`guard_*`/gate/`author_*`/`summarize` primitives, so this is a **relocation** into `Loop`, not a
re-derivation. Live path — execute in the phased order; each phase is independently green.

## Invariants (must survive)
1. **Termination** — single-item mode runs the off-ramps the multi-item loop lacks (`stall_terminated`
   + task-level `judge_satisfaction` done-critic + periodic satisfaction). Multi-item must NOT grow
   them. So they live in a **separate** `_drive_single_item`, reached only when `sess.synthetic`.
2. **Framing** — `total==1` synthetic ⇒ RAW task, no "step 1/1". `_frame_for_item(synthetic=True)`
   must be byte-equivalent to the deleted `_direct_coder_body`.
3. **Persistence** — stable `sid:` key ⇒ persisted+resumable; unstable `task:` key ⇒ **ephemeral,
   never `put`** (re-synthesized each turn) or the plan-cache cross-session leak returns.

## The key: an explicit `synthetic` flag on `PlanSession` — NOT `len(items)==1`
A genuine planner 1-step plan must NOT get the off-ramps or raw-task framing. `synthetic` is the key.

## Phases (each: commit + full suite green)
1. **Framing (additive).** `_frame_for_item(..., synthetic=False)` raw-task branch; `_synthetic_plan(task)`;
   `PlanSession.synthetic` field + `_session_to_dict`/`_from_dict` round-trip. Verify synthetic output ==
   `_direct_coder_body` output. Nothing calls the new path yet.
2. **Move helpers into `Loop` (dormant).** `Loop._drive_single_item` (← `_drive_direct_coder`),
   `_gate_single_done` (← `_gate_direct_done`), `_run_single_coder` (← `_run_coder`),
   `_done_critic_says_incomplete`, `_reasoned_reanchor`, single-item self-compact. Add `LoopContext`
   fields: `planner_enabled`, `satisfaction_check_start/every`, unconditional `reasoner_chat`/`reasoner_role`.
   `server._drive_direct_coder` still wired. Unit-test moved methods.
3. **Creation + persistence in `_drive_locked`.** Planner-off `sess is None` branch: `latest_user_text`,
   briefing, stable⇒`put`, unstable⇒ephemeral. `if sess.synthetic: return _drive_single_item(...)`
   before the multi-item `awaiting_probe` branch. Persistence tests.
4. **Flip construction + dispatch.** Gate → `has_coder and (has_reasoner or not planner.enabled)` (always
   build Loop). `_engages_loop(sk, classification)` predicate; collapse `_produce_completion` +
   `_produce_stream` to one `Loop.drive`. DELETE `_drive_direct_coder`/`_gate_direct_done`/`_run_coder`/
   `_guarded_coder_chat`/`_maybe_self_compact`/`_summarize`/`_detect_rewrite`/`_reasoned_reanchor`/
   `_done_critic_says_incomplete`/`_direct_coder_body`, attrs `guard_store`/`compact_states`, dead imports.
   Update `test_path_parity.py`, `test_server.py`; new `test_loop.py::SingleItemModeTests`. Live-smoke.
5. **Cleanup.** Remove `GuardStore` if unused; prune imports; restart cria.service.

## Top silent-break risks
1. Keying single-item on `len(items)==1` instead of `synthetic` → a real planner 1-step plan wrongly
   gets off-ramps + loses its refined step text. Use the flag.
2. The shell-tool decline (`_drive_locked`, loop.py ~587 `return None` when no shell tool) — plan-off
   runs the guarded coder even with no shell tool; gate that decline to planner-ON only, or the
   synthetic path silently loses rumination/truncation guards on a native-write_file harness.
3. Persisting a synthetic session on an unstable `task:` key → cross-session leak. Stable-key gate around
   `_store.put` is load-bearing; the "ephemeral on task:" test is the guard.
