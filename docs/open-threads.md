# Open threads — what's left to decide and build

The single source of truth for work that is **undecided or unbuilt right now**. Update it as decisions land and items ship. Grew out of the 2026-07-18 routes/naming/reasoning discussion.

**Where the rest is tracked (so nothing feels lost):**
- [docs/goals/work-plan.md](goals/work-plan.md) — the `/goal` wave (Epics A/B/C). **COMPLETE.**
- [docs/audits/port-fidelity-audit.md](audits/port-fidelity-audit.md) — older port gaps (the former `DEFERRALS.md` was merged in here, commit `5be0f9f`).
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
No rename. The one real bug it carried (B3b half-done: the loop's internal reasoner hand-rolled `enable_thinking=false`, so a cloud reasoner's "off" was a no-op) is **CLOSED by the config unify** — every role now goes through `role.apply()`, which translates via its backend's `think_protocol`. Nothing left here.

### Theme 2 — Config unify (was local/cloud rename)  ✅ SHIPPED (`68a4597`)
- [x] ONE model: `Backend` (where) + `Role` (how). Killed `LocalRole`/`CloudEntry`/`ProviderConfig`, `local_roles`/`cloud_pools`/`providers`/`local_only`, the desugar, and the `cloud.<role>` address.
- [x] ONE format: `[defaults]` + `[backends]` + `[roles]` + `[failover]`. Zero aliases.
- [x] `role.think_protocol` (chat_template | openai | openrouter | none) resolved from the backend → `role.apply()` translates reasoning uniformly; B3b closed by construction.
- [x] `endpoint_for` builds an authed Upstream for a keyed backend → **B1-http residual closed** (a loop role on groq/openrouter is now reachable, not just the proxy coder).
- [x] `cria.example.toml` (all keys, terse) + live `~/.cria/cria.toml` converted; cria restarted. 930 tests.

### Theme 3 — Route unification  ✅ SHIPPED (`10404d0`→`1d128f9`, live-smoked)
Plan-off is now a degenerate 1-item plan → ONE driver (`Loop.drive`); the planner is an internal on/off stage. `_drive_direct_coder`/`_gate_direct_done` + 8 more server helpers DELETED. All 3 invariants held: (1) the off-ramps (stall-terminate / satisfaction / done-critic) live in `Loop._drive_single_item`, reached only via `sess.synthetic` — the multi-item path is untouched; (2) `_frame_for_item(synthetic=True)` = raw task, no "step 1/1", byte-equivalent to the old framing; (3) synthetic session persists on stable `sid:` keys, **ephemeral** on unstable `task:` keys. The shell-tool decline is gated to planner-ON (else the synthetic path would lose its guards).

- [x] Design pass → `docs/goals/route-unify-plan.md`.
- [x] Phase 1 synthetic framing; Phase 2 relocate into `Loop`; Phase 3 creation + persistence; Phase 4 flip dispatch + delete plan-off path; Phase 5 remove dead `GuardStore`.
- [x] 944 tests; **live smoke**: a coding turn drove `loop.start synthetic=true steps=1`, ZERO `plan_off`/`direct_coder` events, HTTP 200 coder `write_file`.

### Residual — a cli backend can't be a loop-internal endpoint (B1-cli)
`endpoint_for` now resolves served + keyed-http; a **cli** backend (claude) still falls back to the shared endpoint (a raw chat endpoint can't be a subprocess agent). Rare config; left as a known gap.

- [ ] (low priority) Make a cli backend usable as a loop-internal role, or reject it with a reason.

---

## Considered and REFUSED (don't rebuild)

### Withhold a steer that contradicts the session's own response shapes (2026-08-03)
A steer naming a parsed endpoint AND a field that endpoint does not return would have been deleted before delivery. Built twice, refused twice. What the evidence said, all of it re-derived by an independent reviewer over the 98-run corpus:

- **The trade is upside-down.** 18 candidate steers: **4 defective, 10 correct**, 3 capture artifacts, 1 unclassifiable — and nothing lexical separates them. Correct and defective name the same two endpoints and the same two fields in the same kind of sentence. Ten clean signals gated to catch four (rule 1: the bar to ADD is high).
- **It cannot prevent the damage.** All four defects arrive AFTER the coder already wrote the wrong field: −53, −196 and −19 calls. The one case where the steer led the write is the case the gate MISSED at temp 0. Withholding an echo of a fact the coder is already acting on changes nothing.
- **The real cause was upstream and is already fixed.** The steer author's evidence block ended `utxo(string, e.g. …), …+4 more field(s)` — it was shown 34 of 39 fields and told 4 were hidden, so it could not rule the field out. That is cria showing an author a cut list, not a model inventing a fact. `FIELD_CAP` 30→40 (`ce8ac20`) renders the same spec with **no elision**. Every run behind this branch predates that commit by hours.
- **The message that actually destroyed the recovery is out of its reach.** The coder worked it out alone — *"the API response we have does not contain a field for total handles"* — and what pushed it back was the step critic's `reason`, which reaches the coder on a different path the check never sees.

If it is ever revisited, the fix belongs in the steer author's own prompt (fence it to the parsed field names it was given), which also covers the critic path and the plan step. Not a downstream deletion. Re-open only with ≥5 runs on current code showing the false claim still happens.

---

## Shipped this session (done — don't re-litigate)
- Never-truncate overhaul (`fc2682c`); web_fetch/read exec-envelope strip (`4671687`, `f77d3bb`).
- Turn-stats ledger fixes (`86cb1c3`, `1c6fe74`, `3d7dcc8`); satisfaction-gate-on-green (`9355ca6`).
- validate-before-lower + normalize_tool_names + subtractive gate framing (`d12b248`).
- The whole `/goal` work-plan — Epics A/B/C, 11 commits (see work-plan.md).
- Self-recursion detector idea dropped (`3cdf774`); B3b reasoning-portability (`ea6fba9`, `130228c`).
- **Config unify — one backends/roles model, zero aliases (`68a4597`).**

**2026-08-04 addendum (REGRESSION1 walks), counter-evidence:** run `ada-handles_gemma4_codex_poff_1785843217` steer 0080 asserted camelCase field names (`resolvedAddresses`/`totalHandles`) against a ledger holding the snake_case truth — and the coder's code was CORRECT until it obeyed; the shipped resolver kept `totalHandles` and scored one of the run's four zeros. This is a defect that arrived BEFORE the write it caused, the case the refusal's "damage already landed" bullet said did not occur. A second same-day instance: `ada-handles_nemotron-elastic_codex_pon_1785834747` (plan-step side) survived five replans and seven correct critic rejections demanding fields from an endpoint the ledger proves does not return them. Two walked runs, two surfaces (steer, plan step), both ledger-disprovable. Re-adjudication is the operator's call.

---

## Open: a command cria composes cannot exceed 128 KiB, and one path is unmeasured

**The bound.** The harness runs `bash -lc "<command>"`, so every command cria composes is ONE argv string, and Linux caps a single argument at `MAX_ARG_STRLEN` = 32 pages = 128 KiB. Nothing inside the command escapes it — a heredoc, chunked printfs and base64 are all bytes in that same string. Codex reports the overrun as `Argument list too long (os error 7)` and fails the WHOLE exec, so nothing lands and the model gets an error it cannot attribute to anything it did.

**Where it is handled.** The fetch spill (`writeproxy._spill_command`). It was measured there: a large spec never landed, and the workaround — stage the doc in cria's own directory, lower a small `cp` — copies a file the harness cannot see the moment cria and the harness are not the same machine, which silently produced an EMPTY doc under a pointer telling the model to read it. It now cuts at `SPILL_CONTENT_MAX` and states the cut in both the file and the pointer message.

**Where it is not.** `writeproxy._write_command` — the model's own `write_file`. A model writing more than ~90 KB in one call would hit the same wall and get the same unattributable error. **Not observed once**, in any walked run, from any model. Per #15 that is not enough to build on: what a guard here would do (refuse, and tell the model to write in parts) is an ADD, and the bar to add is high.

**What would settle it.** One walked run where a `write_file` fails with `os error 7`, or a count of write payload sizes across the capture corpus showing any above ~90 KB. Until then the docstring states the ceiling and nothing enforces it.

