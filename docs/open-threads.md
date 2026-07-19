# Open threads — what's left to decide and build

The single source of truth for work that is **undecided or unbuilt right now**. Update it as
decisions land and items ship. Grew out of the 2026-07-18 routes/naming/reasoning discussion.

**Where the rest is tracked (so nothing feels lost):**
- [docs/work-plan.md](work-plan.md) — the `/goal` wave (Epics A/B/C). **COMPLETE.**
- [docs/port-fidelity-audit.md](port-fidelity-audit.md) — older port gaps (the former `DEFERRALS.md`
  was merged in here, commit `5be0f9f`).
- This file — the live themes below.

---

## Decisions — all resolved (2026-07-18)

| # | Decision | Resolution |
|---|----------|------------|
| D1 | Reasoning knob names | **LEAVE ALONE.** No `think`/`show_thinking` rename — `reasoning`, `[indicators].reasoning`, `reasoning_transcript` stay. The whole rename is cancelled. |
| D2 | local/cloud → new names | **Not a rename — a UNIFY.** They were never two things: one concept, `[backends]` + `[roles]`, differing only by transport/auth. No `served`/`keyed` split. |
| D3 | Classic config schema | **ZERO ALIASES.** Classic `[models.local]`/`[models.cloud]`/`[providers]`/`[upstream]`/`local_only` + the desugar layer DELETED. `[backends]`/`[roles]` is the only format. |
| D4 | Route-unification scope | **(b) full unify** — plan-off = a degenerate 1-item plan → one driver. |
| D5 | Order | **Do everything**, no per-theme gating. |

---

## Build queue

### Theme 1 — Reasoning legibility  ❌ CANCELLED (D1)
No rename. The one real bug it carried (B3b half-done: the loop's internal reasoner hand-rolled
`enable_thinking=false`, so a cloud reasoner's "off" was a no-op) is **CLOSED by the config
unify** — every role now goes through `role.apply()`, which translates via its backend's
`think_protocol`. Nothing left here.

### Theme 2 — Config unify (was local/cloud rename)  ✅ SHIPPED (`68a4597`)
- [x] ONE model: `Backend` (where) + `Role` (how). Killed `LocalRole`/`CloudEntry`/`ProviderConfig`,
      `local_roles`/`cloud_pools`/`providers`/`local_only`, the desugar, and the `cloud.<role>` address.
- [x] ONE format: `[defaults]` + `[backends]` + `[roles]` + `[failover]`. Zero aliases.
- [x] `role.think_protocol` (chat_template | openai | openrouter | none) resolved from the backend →
      `role.apply()` translates reasoning uniformly; B3b closed by construction.
- [x] `endpoint_for` builds an authed Upstream for a keyed backend → **B1-http residual closed**
      (a loop role on groq/openrouter is now reachable, not just the proxy coder).
- [x] `cria.example.toml` (all keys, terse) + live `~/.cria/cria.toml` converted; cria restarted. 930 tests.

### Theme 3 — Route unification  ✅ SHIPPED (`10404d0`→`1d128f9`, live-smoked)
Plan-off is now a degenerate 1-item plan → ONE driver (`Loop.drive`); the planner is an internal
on/off stage. `_drive_direct_coder`/`_gate_direct_done` + 8 more server helpers DELETED. All 3
invariants held: (1) the off-ramps (stall-terminate / satisfaction / done-critic) live in
`Loop._drive_single_item`, reached only via `sess.synthetic` — the multi-item path is untouched;
(2) `_frame_for_item(synthetic=True)` = raw task, no "step 1/1", byte-equivalent to the old framing;
(3) synthetic session persists on stable `sid:` keys, **ephemeral** on unstable `task:` keys.
The shell-tool decline is gated to planner-ON (else the synthetic path would lose its guards).

- [x] Design pass → `docs/route-unify-plan.md`.
- [x] Phase 1 synthetic framing; Phase 2 relocate into `Loop`; Phase 3 creation + persistence;
      Phase 4 flip dispatch + delete plan-off path; Phase 5 remove dead `GuardStore`.
- [x] 944 tests; **live smoke**: a coding turn drove `loop.start synthetic=true steps=1`, ZERO
      `plan_off`/`direct_coder` events, HTTP 200 coder `write_file`.

### Residual — a cli backend can't be a loop-internal endpoint (B1-cli)
`endpoint_for` now resolves served + keyed-http; a **cli** backend (claude) still falls back to the
shared endpoint (a raw chat endpoint can't be a subprocess agent). Rare config; left as a known gap.

- [ ] (low priority) Make a cli backend usable as a loop-internal role, or reject it with a reason.

---

## Shipped this session (done — don't re-litigate)
- Never-truncate overhaul (`fc2682c`); web_fetch/read exec-envelope strip (`4671687`, `f77d3bb`).
- Turn-stats ledger fixes (`86cb1c3`, `1c6fe74`, `3d7dcc8`); satisfaction-gate-on-green (`9355ca6`).
- validate-before-lower + normalize_tool_names + subtractive gate framing (`d12b248`).
- The whole `/goal` work-plan — Epics A/B/C, 11 commits (see work-plan.md).
- Self-recursion detector idea dropped (`3cdf774`); B3b reasoning-portability (`ea6fba9`, `130228c`).
- **Config unify — one backends/roles model, zero aliases (`68a4597`).**
