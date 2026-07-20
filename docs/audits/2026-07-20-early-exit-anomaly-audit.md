# Anomaly Sweep — early-exit paths (2026-07-20)

**Seed anomaly.** The plan-off done-critic (`loop.py _done_critic_says_incomplete`) "ran at most ONCE"
(`done_critiqued`): after it flagged a task incomplete and steered once, the model's *next* green 'done'
skipped the critic and ended the session — a real session completed with a dropped requirement
(`total_handles`) through this path.

**Mission.** cria must NEVER let the driven model "early-exit" — end the session, declare done, advance a
step, or hand back to a human — before the work is GENUINELY complete (the repo's real checks/tests ran
and passed, requirements met). A premature/false "done" is the cardinal sin.

**Dimensions swept (4 parallel agents).** (1) explicit done/advance decisions, (2) fail-open-toward-done,
(3) bounds/caps/once-guards, (4) termination/give-up/human-handback residuals.

**Cross-cutting root (all 4 agents agree):** every early-exit is a **FAIL-OPEN ON MISSING GROUND TRUTH** —
no shell tool, the gate didn't run, no reasoner, a bound expired, or a misclassification. When the
objective gate actually runs, cria is trustworthy; the danger is the exits reachable when the gate is
absent or silenced.

---

## Tier 1 — reachable early-exit, fix on sight

- [x] **The done-critic once-bound.** `loop.py:1124` `not sess.done_critiqued` + `done_critiqued` field.
  A flagged-incomplete plan-off 'done' ended on the 2nd try. **FIXED 2026-07-20**: removed the bound; the
  critic re-runs on EVERY green 'done' and steers back with its CONCRETE reason (via `done_incomplete`'s
  new `{{REASON}}`) until the task is actually satisfied. Fail-closed (undecidable judge = not-done).
- [ ] **Plan-off no-shell 'done' ends with ZERO verification.** `_gate_single_done` `loop.py:~1275`
  `return comp` — no gate AND no critic. The multi-step loop path runs `_verify` first (`:766-773`); the
  synthetic/plan-off path does not. → route the no-shell 'done' through the reasoner critic before
  forwarding (parity with the loop path).
- [ ] **Dead human-handback residual.** `_closing` `loop.py:~1074-1094` can emit "N of M steps did NOT
  pass verification … the result needs review before it can be trusted" (surface untrusted work to a
  human) via `_advance(ok=False)`. Currently UNREACHABLE (the fail-cap was removed; every `_advance`
  caller guards on `if ok:`), so it is dead residual of the removed accept-and-advance/terminator. →
  delete it (or confirm intentional).
- [ ] **Stale stall-terminator comments.** `loop.py:~166-169` still frames "ending the session HONESTLY
  back to the user"; `:~855-856` narrates the codex-local "ACCEPTS with an UNRESOLVED banner" cria
  rejected. Fields (`gate_stall`/`gate_sig`) are legitimately repurposed for the thrash-assist; only the
  prose is stale. → rewrite to the no-terminator reality.

## Tier 2 — the "can't verify → fail-open vs loop-forever" cluster (a policy decision)

Each ends a session when cria CANNOT get ground truth. Closing them (keep-working instead of fail-open)
honors "no early exit" but risks a futile loop when verification is genuinely impossible. Needs an
explicit policy call.

- [ ] **Satisfaction check ends fail-open with no shell.** `loop.py:~1211` — a proactive "satisfied"
  reasoner verdict ends the session when no gate can be built. (It is at least reasoner-gated, not blind.)
- [ ] **Gate couldn't-run is fail-open.** `guard_gate_verdict` `loop.py:~2245-2246` / `_verify_after_probe`
  `:~834`: `outcome.ran=False` (declined / timeout / no markers) → accept the 'done'. → distinguish "no
  gate configured" (fail-open OK) from "gate errored/declined" (should re-issue, not accept).
- [ ] **Compaction-lost probe-reissue cap.** `MAX_PROBE_REISSUES=2` (`:~99`): past the cap the empty probe
  falls to the couldn't-run fail-open above. → re-arm rather than fall through.
- [ ] **Vacuous-green isn't a hard block.** `last_gate_testless` is fed only as *evidence* to the
  reasoner critic; with NO reasoner on the plan-off path, a 0-tests-collected green passes the objective
  gate and ends. (Largely mitigated now that the TEST FLOOR runs `test_*.py`, but not a hard block.)
- [ ] **Misclassification bypasses the driver.** A coding-shaped turn classified non-task relays the raw
  upstream 'done' to the client ungated (`server.py` proxy fallback). → fail toward engaging the driver
  for ambiguous coding-shaped turns.

## Posture check — what's RIGHT

The core is sound; the anomalies are all at the *edges* where ground truth is unavailable.

- **No fail-cap.** `_advance` is only ever called with `ok=True`; `verify_fails` increments but NEVER
  advances — a step re-nudges INDEFINITELY, never accepts-unverified. The operator's "no cap" stance holds.
- **Judges fail CLOSED.** `judge_satisfaction`, `_verify`, `_satisfaction_verdict`: an unparseable/empty
  verdict → NOT satisfied / NOT done; the reasoning-off retry can only REJECT, never approve.
- **No coercion-into-clean-done.** `_normalize_completion` + `massage.coerce_text_answer` fold a
  `task_complete` into a plain 'done' that STILL runs LEG0 → gate → critic; they never bypass the gate.
- **No live terminate / escalate / human-handback** anywhere in `loop.py`/`server.py`. Error paths
  fail-to-TRANSPORT (502 / return None), they do not give up on the task. Prompts contain no handback
  language — "then stop" / "report when genuinely done" mean end the TURN (cria's gated completion
  signal), not surface to a human; `steer_diagnose.txt` forbids the reasoner from telling the coder it's
  done. The stall terminator stays removed.
- **Cooldowns are assist-cadence only** (`FLAIL_COOLDOWN`, `THRASH_STALL_CYCLES`, `GATE_EVERY_CODER_TURNS`);
  none end or advance. Truncation/rumination retry caps REFUSE a partial write, they don't exit.

---

*Source transcripts (this session's JSONL): agent task IDs a589f0e66d58120eb (explicit-done),
a689e17b768274c29 (fail-open), a7da01bcc4714ef15 (caps/bounds), a4a25d7eebfdc5ceb (termination).*
