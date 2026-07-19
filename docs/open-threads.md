# Open threads — what's left to decide and build

The single source of truth for work that is **undecided or unbuilt right now**. Update it as
decisions land and items ship; close an item by checking it off (and delete the section once a
whole theme is done). Grew out of the 2026-07-18 routes/naming/reasoning discussion.

**Where the rest is tracked (so nothing feels lost):**
- [docs/work-plan.md](work-plan.md) — the `/goal` wave (Epics A/B/C). **COMPLETE.**
- [docs/port-fidelity-audit.md](port-fidelity-audit.md) — older port gaps (the former `DEFERRALS.md`
  was merged in here, commit `5be0f9f`).
- This file — the three live themes below.

---

## 1. Decisions waiting on you

| # | Decision | Options | My recommendation |
|---|----------|---------|-------------------|
| D1 | **Reasoning knob names** | `think` / `think_protocol` / `show_thinking` — or your words | Adopt them. One word per domain kills the 3-way "reasoning" collision. |
| D2 | **local/cloud → new names** | `served` / `keyed` — or your words | Adopt them. The real axis is transport (served-keyless vs keyed/subprocess), never geography. |
| D3 | **Classic config schema** | (a) demote `[models.local]`/`[models.cloud]`/`local_only` to deprecated-with-alias; (b) keep both first-class | (a) — make `[backends]`/`[roles]` the ONE documented surface; old files keep loading via a desugar alias. |
| D4 | **Route-unification scope** | (a) dedupe the same-job wrappers only; (b) full unify (plan-off = 1-item plan); (c) leave as-is | (a) now (low-risk, kills the "check both paths" burden), (b) later as a deliberate refactor. |
| D5 | **Order** | which theme first | Reasoning → naming → routes. Reasoning is most contained and closes a real bug. |

---

## 2. Build queue

### Theme 1 — Reasoning legibility  *(needs D1)*
The word "reasoning" means three unrelated things today: GENERATION (does the model think),
DISPLAY (do we surface it), TRANSPORT (the translator module). Split into three named domains.

- [ ] Rename the role knob `reasoning` → `think` (`LocalRole`, `CloudEntry`, `[roles].*`). Value
      unchanged: `on|off|auto` (+ effort passthrough).
- [ ] Rename `ProviderConfig.reasoning_style` → `think_protocol`; module `cria/reasoning.py` →
      `cria/think_protocol.py`; `apply_reasoning` → `apply_think`. **Document as auto-detected /
      override-only** — it is NOT a knob you set (inferred from the backend URL).
- [ ] Collapse `[indicators].reasoning` + `reasoning_transcript` → one
      `show_thinking = off | live | transcript | both`.
- [ ] **BUG — B3b is half-done.** The loop's internal reasoner/critic calls hand-roll
      `enable_thinking=false` at [loop.py:313](../cria/loop.py#L313), [977](../cria/loop.py#L977),
      [1803](../cria/loop.py#L1803), bypassing the translator — so a **cloud-hosted reasoner's "off"
      is a silent no-op**. Route them through `apply_think`. This finishes B3b for ALL roles, not
      just the coder.

### Theme 2 — served/keyed rename  *(needs D2, D3)*
`reasoning.py` is already transport-named — the model to copy. `loopstate.json` has zero
local/cloud strings, so **no data migration**.

- [ ] **Tier 1 (safe, no migration):** internal symbol renames —
      `local_roles→served_roles`, `cloud_pools→keyed_pools`, `CloudEntry→BackendChoice`,
      `ProviderConfig→BackendTransport`, `_build_cloud→_build_transport`,
      `_local_endpoint→_served_endpoint`, `RoutingConfig.local_only→served_only`.
- [ ] **Tier 2 (load-bearing, one atomic commit + desugar alias):** config keys
      `[models.local]→[models.served]`, `[models.cloud]→[models.keyed]`, `local_only→served_only`,
      and the **`cloud.<role>` → `keyed.<role>` chain address** across all 4 sites
      ([config.py:482](../cria/config.py#L482)/[486](../cria/config.py#L486)/[553](../cria/config.py#L553),
      [routing.py:125](../cria/routing.py#L125)) — rename together or chains silently stop resolving.
      Update README + docs/model-settings.md in the same change.

### Theme 3 — Route unification  *(needs D4)*
With the planner OFF, `Loop.drive` is **dead code** — you run one route (`_drive_direct_coder`).
The two-route split exists only for planner-ON; the ~10 duplicated wrappers are why "does it exist
on both paths?" checks keep failing.

- [ ] **Safe subset:** dedupe the same-job-twice wrappers — coder framing, coder-call hygiene,
      gate verdict, probe-reissue, self-compaction, focus-trim, guarded-coder-chat construction,
      rewrite-response, done-judging. Each already bottoms out in a shared primitive; merge the
      wrappers.
- [ ] **Full unify (later):** model plan-off as a degenerate 1-item plan → one driver, planner an
      internal on/off stage. **Preserve 3 invariants:** (1) off-ramps (stall-terminate / task
      satisfaction / done-critic) run *conditionally* in single-item mode; (2) no "step 1/1" framing
      when `total==1`; (3) the synthetic plan stays **non-persisted** on unstable `task:` keys (or
      the plan-cache cross-session leak returns).

### Residual (separate, B1-adjacent) — internal roles can't reach a cloud *endpoint*
Distinct from the Theme-1 translation bug. `endpoint_for` resolves **served/local only**, so
plan-off's OWN reasoner calls (satisfaction / thrash / redirect) can't hit a cloud reasoner even
with a key set. Matters once you put the reasoner on groq/openrouter.

- [ ] Make the loop's internal roles (reasoner/compactor) resolve a keyed/cloud endpoint, not just
      the served one.

---

## 3. Shipped this session (done — don't re-litigate)
- Never-truncate overhaul (`fc2682c`); web_fetch/read exec-envelope strip (`4671687`, `f77d3bb`).
- Turn-stats ledger fixes (`86cb1c3`, `1c6fe74`, `3d7dcc8`); satisfaction-gate-on-green (`9355ca6`).
- validate-before-lower + normalize_tool_names + subtractive gate framing (`d12b248`).
- The whole `/goal` work-plan — Epics A/B/C, 11 commits (see work-plan.md).
- Self-recursion detector idea dropped (`3cdf774`).
- **B3b reasoning-portability** — `cria/reasoning.py` translator (`ea6fba9`, `130228c`). *(Theme 1
  will rename it and finish the internal-roles half.)*
