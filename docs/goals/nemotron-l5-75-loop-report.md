# nemotron-elastic L5 >75% closure report

Ledger for the goal in `docs/goals/nemotron-l5-75-loop.md`. Maintained by the Supervisor; dated
sections supersede older prose where they conflict.

## Acceptance ledger

Updated 2026-09-26 with row p28 (all six cells at `51e82781`). Originally reconciled 2026-09-24 against `suite/results/results.jsonl` and `~/.cria/suite/_usefulness/` (see
"Ledger reconciliation — 2026-09-24" below).

| Cell | Latest comparable run | Note | Final usefulness | Status |
|---|---|---|---:|---|
| shipping-rates-rb | `shipping-rates-rb_nemotron-elastic_codex_pon_1790350009` | `51e82781 p28` | 25% | open — ≤75% |
| cart-billing-go | `cart-billing-go_nemotron-elastic_codex_pon_1790354407` | `51e82781 p28` | 30% | open — ≤75% |
| orders-api-py | `orders-api-py_nemotron-elastic_codex_pon_1790457529` | `51e82781 p28` | 25% | open — ≤75% |
| feed-pipeline-java | `feed-pipeline-java_nemotron-elastic_codex_pon_1790460639` | `51e82781 p28` | 15% | open — ≤75% |
| handles-cli-node | `handles-cli-node_nemotron-elastic_codex_pon_1790463051` | `51e82781 p28` | 20% | open — ≤75% |
| rust-toml-cli | `rust-toml-cli_nemotron-elastic_codex_pon_1790466042` | `51e82781 p28` | 25% | open — ≤75% |

Strict closure criterion: every cell's latest comparable L5 final usefulness judgment is >75%.
Comparable means: launched by this campaign at a recorded HEAD with note form
`BATTERY2 L5 nemotron-elastic <short-HEAD> p<N>` (p4 at Phase 0, then p5…p21 and continuing), planner on, completing through canonical
milestone/final judgment. The FROZEN historical ladder row (L5 total 57%: ruby 59, go 31,
python 76, java 20, node 70, rust 84 — `suite/historical_ladder.json`) and all pre-pause
(2026-09-05) results rows are prior-knowledge and walk evidence only, never comparable cells.

## Cadence change — whole-row iteration (user directive, 2026-09-24 ~16:20)

Binding from now (goal doc "Row cadence", `e2296f6e`): the unit of iteration is the **whole row**. The
in-flight p26 Cart run finishes normally (heartbeat `78b4e05e`, terminal packet). After p26 **no single-cell
reruns**: land every accepted, reviewed unit (C35 when accepted), push, restart `cria.service`, confirm `/health`
— that commit is the **row HEAD**. All six cells, closed ones included, run in one crash-survivable, GPU-serialized
queue at that HEAD with one note `BATTERY2 L5 nemotron-elastic <short-HEAD> p<row#>` (first row: **p27**). Nothing
that changes live behavior lands while the queue is active; one recurring 10-minute heartbeat covers the queue. After
the row: walk every sub-75%/regressed cell, reconcile across cells (classes seen in ≥2 cells first), land the fixes
the row justifies, run the next row. Done = one row at one HEAD with every cell >75%. A row with no new accepted fix
is a strategy reset — work, never a stop. The per-cell reruns p22–p26 above predate this directive.

**Correction (user, 2026-09-24 ~17:05):** a cell whose latest comparable result is >75% is **closed and not rerun**; each
row runs every **open** cell (latest comparable ≤75%) at one HEAD, one note, one heartbeat. Done is unchanged: every
cell's latest comparable final usefulness >75%. Row p27 is consistent with this: at its freeze all six cells were open
(shipping 35, cart 25, orders 40, feed 20, handles 50, rust 30), so it runs all six. Later rows will queue only the
cells still ≤75% after the preceding row.

## Baseline environment

### Phase 0 preflight — 2026-09-22

- Repository: `main` at `7cb10e7c0982fd81472c2b3d5b3008cee316ff4b` (`7cb10e7`); `git status --short` was clean. No sibling session was modifying this worktree when the baseline queue was prepared.
- Live service: `cria.service` was `active`; `:18085/health` returned `{"status": "ok"}`. Before the queued swap, `llama-ternary-bonsai-2.service` was the sole active `llama-*` unit and `llama-nemotron-elastic.service` was installed, inactive, and disabled.
- Pre-swap server evidence: `:18084/v1/models` identified `ternary_bonsai_2_27b_pq2_0`; `:18084/props` reported `n_ctx=40960`. This is preflight evidence only, not the nemotron runtime assertion; each queued cell uses `suite/run.py`'s swap, health wait, configura­tion, service restart, and Codex window sync.
- Live `~/.cria/cria.toml`: local backend targets `http://127.0.0.1:18084`; capture calls is enabled; coder and reasoner reasoning are `medium`; planner is enabled by the queue; model-specific sampling is applied by `suite/sampling.py` on every cell. The isolated `~/.cria/codex-home/config.toml` routes Responses API traffic to `http://127.0.0.1:18085/v1`.
- Suite records: `suite/results/results.jsonl` contained 884 preserved rows before this queue. Existing nemotron rows are pre-pause evidence only and are not used as cells in this campaign. New runner rows preserve archive, workspace, capture directory/directories, harness log, sampling, structured assists, milestones, and final usefulness packet.
- Phase 0 queue contract: six GPU-serialized `suite/run.py` invocations, planner `on`, level `5`, and exact note `BATTERY2 L5 nemotron-elastic 7cb10e7 p4`. The durable queue script and log are outside the repository at `~/.cria/nemotron-l5-75-phase0-7cb10e7.sh` and `~/.cria/nemotron-l5-75-phase0-7cb10e7.log`. It launched at `2026-09-22T00:09:44-07:00` as active, non-collected user unit `nemotron-l5-75-phase0-7cb10e7.service`; first cell `shipping-rates-rb` began with the recorded canonical nemotron sampling. Exactly one 10-minute heartbeat is active for this in-flight queue: `e11a6b4b` (`nemotron-l5-phase0-7cb10e7`).
- Post-swap runtime confirmation at `2026-09-22T00:10` while the first cell was active: `llama-nemotron-elastic.service` and `cria.service` were active; `:18085/health` was OK; `:18084/v1/models` identified `nemotron_elastic_12b_a2b_q4km`; `:18084/props` reported `n_ctx=49152`.
- `shipping-rates-rb` checkpoint `shipping-rates-rb_nemotron-elastic_codex_pon_1790060984.030min`: canonical milestone judgment recorded at 30 active minutes: **35%, continue**. Frozen evidence: `rates.rb` contains country-code/express/free-boundary implementation attempts, while `test/test_rates.rb` and `README.md` are still seed content; frozen `bundle exec rake test` failed before execution because `Gemfile` declares `iso3166` but the lockfile does not resolve it.
- `shipping-rates-rb` checkpoint `shipping-rates-rb_nemotron-elastic_codex_pon_1790060984.045min`: canonical milestone judgment recorded at 45 active minutes: **40%, continue**. Frozen evidence: the requested README rate table and express description were added; no express test was added; `bundle exec rake test` and direct loading both raised `Bundler::SystemStackError` after the Gemfile/rates changes added mutually recursive Bundler setup.
- Final comparable row: `shipping-rates-rb_nemotron-elastic_codex_pon_1790060984`, terminal `exited`, exact note/level/planner contract satisfied, final usefulness **20%**. Preserved evidence: archive `/home/jesse/.cria/suite/shipping-rates-rb_nemotron-elastic_codex_pon_1790060984`, capture `/home/jesse/.cria/calls/20260922T001020-01a0c7f3-8451-7e92-8ab4-85b6776413d7`, and frozen final-usefulness packet `/home/jesse/.cria/suite/_usefulness_evidence/shipping-rates-rb_nemotron-elastic_codex_pon_1790060984.txt` (digest `94e22e3f826b5249`). Final inspection found the README table but no express tests; `bundle exec rake test` raised `Bundler::SystemStackError`; and the shipped `shipping_cost` routes ordinary zone names through `zone_for`. Cell remains open. `suite/battery_status.py --write` refreshed the battery report after the judgment.
- `cart-billing-go` checkpoint `cart-billing-go_nemotron-elastic_codex_pon_1790064697.030min`: canonical milestone judgment recorded at 30 active minutes: **25%, continue**. Frozen evidence: `go.mod` names `shopspring/decimal`, the implementation attempts decimal calculation/file-loaded discounts/stderr logging, and a SUMMER25 regression attempt exists; `go test ./...` fails to compile on multiple invalid decimal APIs and multi-return/rounding uses.
- `cart-billing-go` checkpoint `cart-billing-go_nemotron-elastic_codex_pon_1790064697.045min`: canonical milestone judgment recorded at 45 active minutes: **25%, stalled**. The changed-file set and delivered behavior did not advance from the 30-minute snapshot; the same decimal API/type compiler class remained, including new unqualified constructor errors.
- Final comparable row: `cart-billing-go_nemotron-elastic_codex_pon_1790064697`, terminal `milestone-stalled-45min`, exact note/level/planner contract satisfied, final usefulness **25%**. Preserved evidence: archive `/home/jesse/.cria/suite/cart-billing-go_nemotron-elastic_codex_pon_1790064697`, capture `/home/jesse/.cria/calls/20260922T011205-01a0c82c-0d65-7dd1-af01-78e47874386c`, and final packet `/home/jesse/.cria/suite/_usefulness_evidence/cart-billing-go_nemotron-elastic_codex_pon_1790064697.txt` (digest `f806f336c02d7dd7`). Final `go test ./...` could not compile the decimal implementation; cell remains open.
- Final comparable row: `orders-api-py_nemotron-elastic_codex_pon_1790068242`, terminal `exited`, exact note/level/planner contract satisfied, final usefulness **15%**. Preserved evidence: archive `/home/jesse/.cria/suite/orders-api-py_nemotron-elastic_codex_pon_1790068242`, capture `/home/jesse/.cria/calls/20260922T021106-01a0c862-16ea-7761-8117-e15a06b45c93`, and final packet `/home/jesse/.cria/suite/_usefulness_evidence/orders-api-py_nemotron-elastic_codex_pon_1790068242.txt` (digest `9ae4a8d35df14979`). Final `pytest` passed its two seed database tests, but the archive contains no customer-orders route or HTTP integration test, and the status migration lacks an `ALTER TABLE` path for existing databases; cell remains open.
- Final comparable row: `feed-pipeline-java_nemotron-elastic_codex_pon_1790068525`, terminal `exited`, exact note/level/planner contract satisfied, final usefulness **20%**. Preserved evidence: archive `/home/jesse/.cria/suite/feed-pipeline-java_nemotron-elastic_codex_pon_1790068525`, capture `/home/jesse/.cria/calls/20260922T021549-01a0c866-6838-7e72-a13c-9b736f917739`, and final packet `/home/jesse/.cria/suite/_usefulness_evidence/feed-pipeline-java_nemotron-elastic_codex_pon_1790068525.txt` (digest `e9f2666c122feae6`). Maven compilation failed on nonexistent/misused Commons CSV APIs, missing concurrency symbols, and undefined state; the archive has no REVIEW.md or test source. Cell remains open.
- Final comparable row: `handles-cli-node_nemotron-elastic_codex_pon_1790068911`, terminal `exited`, exact note/level/planner contract satisfied, final usefulness **0%**. Preserved evidence: archive `/home/jesse/.cria/suite/handles-cli-node_nemotron-elastic_codex_pon_1790068911`, capture `/home/jesse/.cria/calls/20260922T022215-01a0c86c-4cba-7a11-8732-723bec7e9210`, and final packet `/home/jesse/.cria/suite/_usefulness_evidence/handles-cli-node_nemotron-elastic_codex_pon_1790068911.txt` (digest `eb075c4e6b9b470b`). The final workspace had an empty git diff and still used deprecated `request`; it had no tests, Dockerfile, fetch implementation, or CLI work. Cell remains open.
- Final comparable row: `rust-toml-cli_nemotron-elastic_codex_pon_1790069056`, terminal `exited`, exact note/level/planner contract satisfied, final usefulness **20%**. Preserved evidence: archive `/home/jesse/.cria/suite/rust-toml-cli_nemotron-elastic_codex_pon_1790069056`, capture `/home/jesse/.cria/calls/20260922T022440-01a0c86e-81be-73d2-b597-c015f19e3891`, and final packet `/home/jesse/.cria/suite/_usefulness_evidence/rust-toml-cli_nemotron-elastic_codex_pon_1790069056.txt` (digest `6ebcf2a7db7b2b56`). The task-directed Rust text was written to a regular file named `src`, leaving Cargo with no target and no runnable unit tests. Cell remains open. `suite/battery_status.py --write` refreshed the battery report after final judgments. All six Phase 0 rows are now comparable; the Phase 0 heartbeat `e11a6b4b` was deleted on completion.

## Walks and candidate records

### Phase 2 launch — 2026-09-22

All six open baseline captures were partitioned losslessly with `suite/walk.py --segment-bytes 250000 --full-prompts` under `~/.cria/walk-findings/2026-09-22/`: shipping-rates-rb (102 segments), cart-billing-go (66), orders-api-py (10), feed-pipeline-java (21), handles-cli-node (3), and rust-toml-cli (28). All material and findings remain outside `/tmp`. Wave 1's ten fresh read-only Coder walkers completed shipping-rates-rb segments 001–010 without repository edits. The Supervisor verified each finding's named chunks exist and every explicit cited CALL is in that finding's declared coverage; direct inspection of chunks 038 and 040 confirms the baseline free-threshold failure and the later ungrounded dependency/planning path. Reconciled lead: repeated planner/read loops consumed early calls, and later code changed the known `>`/`>=` boundary but routed existing zone names through an ungrounded country lookup and introduced Bundler recursion. This is accepted as walk evidence only; no causal candidate has been selected yet.

Wave 2's ten read-only walkers completed segments 011–020. The Supervisor verified all explicit CALL citations against their named capture chunks and directly inspected `chunk064.txt` / CALL 0102. The verified pattern is not merely dependency selection: stale plan steps repeatedly made the coder reread an already-available test; a current state check was sometimes replayed as stale evidence; and country-code dispatch did not preserve accepted zone names or unknown-zone rejection. Capture-grounded implementation errors include unavailable/duplicated gems, routing `domestic` through country lookup, and calculating `express` with the zone base rather than `14.99`. These remain causal evidence, not an implementation candidate.

Wave 3's ten read-only walkers completed segments 021–030. The Supervisor verified all explicit CALL citations against the named capture chunks and reconciled the cited outcomes. New accepted evidence: `⟦ctx:facts⟧` saying a file was already read conflicts with continuation steers that demand rediscovery; the dependency/API failure was `Countries::Country` being undefined even after `require 'countries'`, not a missing-require diagnosis; the search guard accepted a reordered duplicate hunt; and two completion observers contradicted supplied README/express source and fabricated absence. No shared change is selected until the full capture walk establishes the minimal intervention boundary.

Wave 4's ten read-only walkers completed segments 031–040. The Supervisor verified every explicit CALL citation against the named chunk. The additional causal evidence is consistent: repeated searches and dependency substitutions continued after the direct `Countries::Country` probe already disproved the assumed API; later Gemfile changes also became incoherent with `rates.rb` (`country` declared while `countries` remained required), producing Bundler incompatibility and `GemNotFound`. This further rules out a dependency-selection-only mitigation; the candidate must make current source, dependency contract, and validation state available together before coding.

### Cross-walk comparison — provisional, not a candidate

The reconciled shipping evidence maps directly to existing `docs/audits/battery-pair-walk.md` classes: stale or repeated source/plan state (classes 3, 5, and 14), guards/continuation text that conflicts with the legal recovery action (class 6), unsupported absence/remedy statements (class 9), and a tool/dependency research surface that prevents grounding an API contract (classes 8 and 15). No novel heuristic is justified: the next candidate must be a minimal, demonstrated repair to one of those existing mechanisms, replayed against the exact shipping capture before implementation. The remaining five cell walks are required to establish whether any survivor is cross-cell rather than shipping-specific.

Wave 5's ten read-only walkers completed shipping segments 041–050. The Supervisor verified every explicit CALL citation against named chunks. The same failed assumption persisted through a successful bundle: the observed failure was an undefined `Countries::Country` constant, but critics/coders continued to treat it as installation/version selection and declared incompatible or nonexistent `iso3166`; compaction also failed to produce a usable bounded handoff. This confirms the provisional mapping above and does not yet select a candidate.

Wave 6's ten read-only walkers completed shipping segments 051–060. The Supervisor verified every explicit CALL citation against named chunks and inspected the material findings. The confirmed failure chain now includes an environment-specific, invalid Bundler command in a denial; a response that inserted `Bundler.setup` into the Gemfile and caused `SystemStackError`; and continued use of the disproved `Countries::Country` API after its runtime `NameError`. This strengthens the existing class-8 denial and classes-9/15 ungrounded-remedy evidence; it does not support a new dependency-specific assist.

Wave 7's ten read-only walkers completed shipping segments 061–070. The Supervisor verified every explicit CALL citation against named chunks. New corroboration is still within established scope: a deliverable observer invented a task-implied test filename despite being instructed to name only explicit whole files, and a denial repeatedly prescribed Bundler's removed `--path` flag even after the checker reported that exact incompatibility. No candidate is selected.

Wave 8's ten read-only walkers completed shipping segments 071–080. The Supervisor verified all explicit CALL citations against their named chunks. Findings are being held as leads pending the complete shipping coverage and cross-cell comparison; no repository change or candidate selection is justified from a partial same-class wave.

Wave 9's ten read-only walkers completed shipping segments 081–090. The Supervisor verified all explicit CALL citations against their named chunks. These findings remain leads until the final shipping wave and the other-cell walks establish the intervention boundary.

Wave 10's ten read-only walkers completed shipping segments 091–100. The Supervisor verified all explicit CALL citations against named chunks. Shipping segments 101–102 completed in the mixed wave; the Supervisor verified their explicit CALL citations against named chunks. Shipping-rates-rb now has lossless walk coverage for all 102 assigned segments. Cart-billing-go segments 001–008, Wave 11 segments 009–018, Wave 12 segments 019–028, Wave 13 segments 029–038, and corrected Wave 14 segments 039–048 completed with explicit citations verified against canonical assignment targets; cart remains in progress. Cart Wave 15 segments 049–058 completed with canonical target files and every explicit CALL citation verified. Final cart segments 059–066 also completed with canonical target files and every explicit CALL citation verified; cart walk coverage is complete. Rust segments 07–08 and Wave 2 segments 09–18 completed with exact canonical targets and citations verified; rust remains in progress. Orders-api-py Wave 14 completed all 10 assigned segments; the Supervisor verified every explicit CALL citation against its named capture chunk. Cross-cell reconciliation is next; no candidate has yet been selected from the orders findings. Feed-pipeline-java Wave 15 segments 001–010, Wave 16 segments 011–020, and segment 021 completed with every explicit CALL citation verified; feed walk coverage is complete. Handles-cli-node segments 01–03 and rust-toml-cli segments 01–06 also completed with exact assignment targets and every explicit CALL citation verified.

## Accepted units / replay / reruns

### Candidate C2 — pending strategy-reset analysis

- **Causal chain:** exact rerun capture CALL0096 records a successful `bundle install`; the later final `shipping_cost` rejects a country code through `ZONE_BASE.key?` before its `zone_for` fallback executes. The prior archive-only dependency diagnosis was corrected; the actionable failure is dispatch order, not missing gems.
- **LANG / MODEL / HARNESS:** Ruby is incidental (any API accepting an alias plus canonical key has this ordering invariant); the coder had task and source context but still selected an unreachable fallback; cria must identify the upstream state/steer/check boundary that failed to make the contradicted input contract actionable without dictating an implementation.
- **Accepted C2:** exact CALL0124 fixture proves `_drive_locked` returned at a tool-less harness checkpoint before recording its structural history rewrite, losing the pending continuation state before the next actionable turn. Commit `028f6541` records the stable-session shape before tool availability is tested, retaining the sticky rewrite only for a later actionable continuation; an adversarial ordinary tool-less turn remains unmarked. Independent Reviewer accepted. Focused replay 16 passed; full pytest 4959 passed, 6 skipped; pushed and `cria.service` restarted with healthy `/health`. **C2 rerun invalidated:** `c2-shipping-rerun-028f6541.service` began at 04:00 for `028f6541`, but `cria.service` was restarted to C3 `0df1c4dd` at 04:40 while it was active. The resulting mixed-service run is not comparable to either HEAD and was stopped; no usefulness result may be recorded. The later `cart-billing-go_nemotron-elastic_codex_pon_1790077545` C3 cart attempt was also deliberately stopped after its 30-minute checkpoint: its workspace, capture directory `/home/jesse/.cria/calls/20260922T044555-01a0c8ef-d51a-7ce3-aa24-75420d4599f8`, and frozen checkpoint are preserved, but it has no terminal suite row or final usefulness packet and is evidence only, never a cell result. **Measurement invariant:** never restart/swap cria while an authoritative comparable run is active; serialize service stability, one flocked run, terminal archive/usefulness judgment, then the next operation. **Active-run reporting invariant:** while any comparable unit is active, post a user report every 10 minutes containing (1) a **fresh holistic usefulness judgment as an integer percentage** from the live workspace and current checks and (2) material changes since the prior report (new workspace/checkpoint, terminal state, service/model change, or `none`). `pending`, “no usefulness judgment happened”, a last comparable percentage, process liveness, and “still active” are not reports and cannot replace the fresh percentage; the prior comparable result may appear only as additional context. Keep exactly one recurring (not one-shot) 10-minute heartbeat for the active unit. Its prompt must require the exact report fields and it remains live until the Supervisor has personally recorded the terminal `suite/usefulness.py` packet and posted the terminal report. No other work may defer a due report. **Post-C3 shipping strategy reset:** `~/.cria/walk-findings/2026-09-22/shipping-c3-strategy-reset.md` rejects a fourth assist: CALL0096 wrote the unreachable dispatch before the C2 checkpoint, without a later country-code probe or completion acceptance; later Bundler failure is separate coder-authored environment state. Neither establishes a model-agnostic cria-caused transition. Shipping reruns are paused pending the record's required new evidence. Bonsai 2 live non-regression remains open. The first uncontaminated C3 comparable run is active: `c3-cart-rerun-0df1c4dd.service`, flocked, planner on, exact note `BATTERY2 L5 nemotron-elastic 0df1c4dd p4`; one 10-minute heartbeat `bd2117d6` is active.

### Candidate C3 — selected, completion-state brake

- **Causal proof:** orders `seg-010`, chunk44 CALL0064 returns `satisfied:false`; chunk45 CALL0065 nevertheless receives `TASK COMPLETED`. Shipping corroborates the same unsafe boundary: `seg-081`, chunk230 CALL0277 accepts red `rake test`, then CALL0278 completes.
- **Boundary / acceptance:** at the single completion/briefing funnel, a latest authoritative false blocks completion instructions, pending-done, completion compaction, and final text until a later current true. It is LANG/MODEL/HARNESS neutral. Commit `0df1c4dd` adds state replay, plan-off proxy-escape regression, and later-true pass case. Reviewer accepted after re-review. Focused tests `37 passed, 4 subtests passed`; full pytest `4962 passed, 6 skipped`; pushed. `cria.service` restarted and `/health` returned `{"status":"ok"}`. Bonsai risk is low (only continues work; bounded completion policy remains); live non-regression and comparable reruns remain open.

### Candidate C5 — accepted pending-read survey handoff

- **Causal proof:** handles CALL0003→0005 and CALL0022→0026 show a workspace read with no delivered bytes becoming exact-repeat-refused before the asynchronous survey can answer it. `e047632e` preserved a queued read and returned one survey carrier; independent review found its conflation of that state with an explicit oversize/unreadable `!` survey answer. The correction makes only a body demand actually queued in `wsview` pending; a known current undeliverable body remains an honest unknown and cannot enqueue another carrier.
- **Boundary / replay:** `b2d42321` (`Fix deferred planner read state`) uses the existing `wsview`/planner/SurveyBootstrap owner, adds no repeat guard, and keeps model-facing wording in `cria/prompts/planner_steers.txt`. Exact successful-retry replay and empty answered-repeat replay remain covered; the new real survey `!` replay proves no C5 survey carrier, truthful unknown, and normal repeat refusal. Independent Reviewer re-review accepted the correction.
- **Validation / live:** focused planner tests passed; full `python -m pytest` passed **4969 passed, 6 skipped**. Commit pushed to `main`; `cria.service` restarted and `/health` returned `{"status": "ok"}`. Bonsai risk is bounded: answered reads retain their existing repeat policy; an undeliverable body remains unknown rather than absent or successful. Eligible rerun: handles-cli-node only, under the exact `BATTERY2 L5 nemotron-elastic b2d42321 p4` contract. It launched detached as active non-collected user unit `c5-handles-rerun-b2d42321.service` with durable script/log `~/.cria/nemotron-l5-c5-handles-b2d42321.{sh,log}`; exactly one recurring 10-minute heartbeat is active: `b4087b05`.

### Post-C5 strategy reset — no shared survivor yet

A fresh read-only cross-cell proof pass rejected another single-candidate rerun. Exact evidence remains divergent: Orders CALL0064→0065 is the C3 false-satisfaction bypass; Shipping CALL0277→0278 has a positive `consistent` verdict despite red check evidence rather than that stored false predicate; Handles CALL0003→0005 / CALL0022→0026 was the C5 async read state; Cart CALL0233 ends before an unsupported negative diagnosis demonstrably changes a later action; Feed and Rust expose no language-neutral cria-owned transition. No further GPU rerun is authorized until one of the recorded focused capture/replay predicates is proven in two language-distinct cells. This corrects the prior claim that shipping corroborated C3. Focused extraction confirmed the correction: Shipping's `0136-satisfaction` false response is followed by `0137-satisfaction-noreason`, while its cited CALL0277→0278 is a separate `consistent:true` step-confirm/replan pair; it is not a false-satisfaction-to-`TASK COMPLETED` replay.

### Handles C5 terminal rerun

- Comparable run `handles-cli-node_nemotron-elastic_codex_pon_1790127621` completed at `b2d42321` under the required note/planner/L5 contract; archive and capture are preserved at `/home/jesse/.cria/suite/handles-cli-node_nemotron-elastic_codex_pon_1790127621` and `/home/jesse/.cria/calls/20260922T184031-01a0cbeb-ed8d-79e2-bc59-4c484a4d2145`.
- Final independent usefulness packet was recorded immediately: **30%**. Read workspace evidence: implementation uses `https` rather than required built-in `fetch`, `--json` before a handle becomes the positional handle, tests rely on unavailable `describe`/mock semantics, and Dockerfile runs `npm ci` without a lockfile. The run is open, not a rerun authorization; the C5 heartbeat `b4087b05` was removed only after terminal packet and terminal report.

### Candidate C6 — accepted gate-plumbing wire boundary (implementation active)

The 101-call C5 Handles rerun has complete lossless walk coverage: all 36 substantive findings are under `/home/jesse/.cria/walk-findings/2026-09-23/handles-c5/findings/`. The focused proof at `/home/jesse/.cria/walk-findings/2026-09-23/c5-gate-cross-cell-proof.md` is accepted: model-received proxy prompts in Node CALL0095/0096/0101, Ruby CALL0018 (`shipping` chunk005), and Java CALL0047 (`feed` chunk29) serialize the raw completion-gate command and transport internals. The deterministic predicate is a coder-bound prompt containing `⟦ctx:gate⟧`, `__cria_`, `___CRIA_GATE_`, `___CRIA_SURVEY_`, or its transport program/envelope. Source tracing proves `probegate.clean_gate_results` works at local consumers but is absent from `Upstream._prep`, the last common serialization boundary. C6 is limited to applying that existing cleaner at the wire with an exact outgoing-body fails-before/passes-after test that preserves cleaned checker evidence. Implementation landed as `5c50d1cf` and repair `ad7328d0`: `Upstream._prep` applies provenance-linked cleaning only when stamped gate call IDs exist; the mixed-history repair scopes check deduplication to those IDs, preserving ordinary marker-shaped tool results byte-identically. Focused implementation tests passed (98 passed, 20 subtests; repair 81 passed); full suites passed `4972 passed, 6 skipped` then `4973 passed, 6 skipped`. Independent review rejected the initial mixed-history regression, then accepted the repair; focused re-review passed `77 passed`. Both commits are pushed; `cria.service` restarted and `/health` returned `{"status":"ok"}`. C6 is eligible for serialized open-cell reruns. The first eligible cell, Handles, launched detached as `c6-handles-rerun-ad7328d0.service` from `~/.cria/nemotron-l5-c6-handles-ad7328d0.sh`, with exact note `BATTERY2 L5 nemotron-elastic ad7328d0 p4`, L5/planner on. It ended `milestone-stalled-45min`; final packet `/home/jesse/.cria/suite/_usefulness_evidence/handles-cli-node_nemotron-elastic_codex_pon_1790130431.txt` was recorded at **55%**, and the battery report was refreshed. Terminal archive evidence: the configured test fails on `assert.propertyExists`; `cli.js` does not query the holder endpoint and uses `data.length`; its real API test does not invoke the CLI. The sole heartbeat `bb4c9127` was removed after the terminal packet and report. Handles remains open; no further Handles rerun is authorized pending a C5/C6 strategy-reset causal proof at `/home/jesse/.cria/walk-findings/2026-09-23/handles-c5-c6-strategy-reset.md`.

### Candidate C7 — accepted planner invalid-draft admission (implementation active)

The C5/C6 Handles strategy reset is proven in `/home/jesse/.cria/walk-findings/2026-09-23/handles-c5-c6-strategy-reset.md`. C5 logged the same missing live API CLI E2E deliverable on its final draft then emitted `plan.final_recovered`/`plan.submitted`; C6 logged final ungrounded-host URLs, explicitly cleared `bad`, then emitted the same admission events. The shared deterministic owner is `Planner._gather_and_plan`: after `MAX_PLAN_HANDBACKS`, it admits a draft that existing typed guards have rejected. Distinct terminal coder defects are downstream consequences, not the predicate. C7 fails closed only on known final-draft invalidity, returning existing retriable no-plan state. Commits `63b12c97` and `7cd57f5f` add exact C5 coverage/C6 URL and URL→host→repeated-host capture-shaped replays; the latter repaired the initial review finding that host checking could be skipped after its handback budget. Focused re-review accepted; full suites passed `4973 passed, 6 skipped` then `4974 passed, 6 skipped`. Both commits are pushed. `cria.service` restarted and `/health` returned `{"status":"ok"}`. C7 is eligible for one serialized rerun; the campaign must still halt a cell after a non-convergent rerun and perform another strategy reset rather than repeat it blindly. The eligible C7 Handles evaluation launched detached as `c7-handles-rerun-7cd57f5f.service` from `~/.cria/nemotron-l5-c7-handles-7cd57f5f.sh`, exact note `BATTERY2 L5 nemotron-elastic 7cd57f5f p4`, planner on/L5. It terminally stalled at 45 minutes; final packet `/home/jesse/.cria/suite/_usefulness_evidence/handles-cli-node_nemotron-elastic_codex_pon_1790134773.txt` was recorded at **55%**, battery report refreshed, and heartbeat `cb047ab1` removed after its terminal report. Archive evidence: built-in-fetch CLI/Dockerfile are present, but the test lacks an imported `test` global and is red; Chai/node_modules plus lockfile violate the no-node_modules contract. Handles is paused from further reruns pending a distinct strategy reset.

### Candidate C8 — accepted completion approval barrier

The five-cell reset at `/home/jesse/.cria/walk-findings/2026-09-23/five-cell-cross-boundary-reset.md` proves a Python/Ruby boundary: Orders CALL0064 `satisfied:false` still reaches a completion briefing; Shipping CALL0277 approves a step despite a current red check, marks it done, and tail-replans past it. C8 extends the existing C3 negative-satisfaction latch to the sole per-step `_advance` owner, preserving current item/evidence and renudging instead of marking it done or replanning; later positive satisfaction releases ordinary advancement. Commit `24e556ed` is pushed; focused loop suite passed 401, focused boundary 33, and full pytest `4976 passed, 6 skipped`. Independent review accepted. `cria.service` restarted and `/health` returned `{"status":"ok"}`. C8 is eligible for one serialized Shipping rerun; no Handles rerun is authorized. Shipping launched detached as `c8-shipping-rerun-24e556ed.service` from `~/.cria/nemotron-l5-c8-shipping-24e556ed.sh`, exact note `BATTERY2 L5 nemotron-elastic 24e556ed p4`, planner on/L5. It terminally stalled at 30 minutes; final packet `/home/jesse/.cria/suite/_usefulness_evidence/shipping-rates-rb_nemotron-elastic_codex_pon_1790138116.txt` was recorded at **30%**, battery report refreshed, terminal report posted, and heartbeat `79301367` removed. Archive evidence: threshold work landed, but ordinary rates raise unassigned `surcharge`, automatic oversize/free still returns 0, and express/country/dependency/rate-table deliverables remain absent. No further GPU rerun is authorized pending a cross-candidate strategy reset.

### C5–C8 global strategy reset — shared candidate rejected

`/home/jesse/.cria/walk-findings/2026-09-23/c5-c8-global-strategy-reset.md` rejects a new universal rerun candidate. C5/C6 were known-invalid final-plan admissions; C7 instead has a deterministic post-submission URL corruption by `repoint_unusable_paths` treating `/api.handle.me/openapi.json` inside `https://...` as a workspace path; C8's suspected dependency deletion was explicitly refused by the preservation guard and the gem step reached the coder. Those are different control flows, so a generic planner label would not be causal evidence. **No GPU rerun is authorized.** The C7 URL owner-local repair landed as `7a967570` and its parenthesized-route correction `94cecf88`; exact C7 and valid parenthesized URL replays now preserve URL bytes while standalone external and workspace path behavior remains covered. Focused suites passed 77 then 78; full suites `4977 passed, 6 skipped` then `4978 passed, 6 skipped`; independent re-review accepted. `cria.service` restarted and `/health` returned `{"status":"ok"}`. Its direct C7 replay is being evaluated once, not treated as global authorization: Handles launched detached as `c9-handles-rerun-94cecf88.service` from `~/.cria/nemotron-l5-c9-handles-94cecf88.sh`, exact note `BATTERY2 L5 nemotron-elastic 94cecf88 p4`, L5/planner on. C9 terminally exited; final packet `/home/jesse/.cria/suite/_usefulness_evidence/handles-cli-node_nemotron-elastic_codex_pon_1790141421.txt` was recorded at **50%**, battery report refreshed, terminal report posted, and heartbeat `8974c56c` removed. Archive evidence: green direct API test/Dockerfile/dependency-free manifest, but `lookup.js` still reads `resolved_addresses[0]`, never calls `/holders/{holder}`, and the test does not execute the CLI. No further Handles rerun is authorized. Per-cell evidence must still be reconciled into a genuinely shared predicate before any subsequent battery evaluation.

### Candidate C10 — living-plan coverage refusal reset

The C5–C9 Handles reset proves the later owner `Loop._replan_tail`: a typed coverage refusal emitted `loop.replan_uncovered`, then `loop.replan_noop`, preserving and serializing a stale old cursor despite known dropped requirements. C10 commit `706b1ea3` resets only this typed refusal into existing raw-task/single-item framing, suppresses replayed serialized plan cursors, and persists/injects uncovered evidence once across restoration. Initial review found stale-history and restart-delivery gaps; the repair was re-reviewed and accepted. Focused suites passed 413 then 8; full suite passed `4981 passed, 7 skipped` (the later count includes a new skipped test). Commit pushed; `cria.service` restarted and `/health` returned `{"status":"ok"}`. C10 is cross-language proven in `/home/jesse/.cria/walk-findings/2026-09-23/c10-cross-language-proof.md`: Cart/Go full CALL0178–0181 chain records typed `loop.replan_uncovered` then declined noop then serializes stale `discounts.json` cursor; Orders/Python and Rust independently match. Feed/Java and Shipping/Ruby are deliberately rejected because their replan outcomes differ. This establishes a language/task-agnostic event/state predicate, not a planner label. Cart-shaped and C8 preservation-negative regressions landed in `e5f7cc33`; loop suite passed 407, full pytest `4984 passed, 6 skipped`, and `git diff --check` passed. `cria.service` restarted and `/health` returned `{"status":"ok"}`. The sole eligible Cart evaluation launched detached as `c10-cart-rerun-e5f7cc33.service` with note `BATTERY2 L5 nemotron-elastic e5f7cc33 p4` terminated `milestone-stalled-30min` after 189 calls. Its authoritative packet is `/home/jesse/.cria/suite/_usefulness_evidence/cart-billing-go_nemotron-elastic_codex_pon_1790145358.txt`; final usefulness **15%** is recorded and battery report refreshed. It added `discounts.json` but left `go.mod` syntactically invalid, so no Go check could run; decimal/rounding/fallback/stderr delivery remains unverified. Heartbeat `4fcafcbe` was removed after terminal handling. No successor rerun is authorized.

### Global terminal-delivery reset

`/home/jesse/.cria/walk-findings/2026-09-23/global-terminal-delivery-reset.md` rejects the demanded universal C5–C10 boundary rather than inventing one. Full packets and captures establish distinct causes: C5/C6 initial planner admission despite negative ground truth; C7 URL corruption plus later living-tail refusal; C9/Cart baseline living-tail refusal/noop; C8's preservation guard correctly retained a required gem and does not instantiate that branch; Cart C10 terminal module-file churn. Thus C10's event-state repair is real Node/Go coverage but has not changed the terminal build/tooling failure transition. `/home/jesse/.cria/walk-findings/2026-09-23/c6-c10-tooling-churn-reset.md` separately reads all C6–C10 packets and decisive full chains and rejects the proposed universal tooling-churn boundary: C6/C7 are real JS test-interface churn, C10 is real Go dependency-loop churn, while C8 is a Ruby calculation regression and C9 is an unverified E2E/task-contract failure without a failed-runner transition. Existing package-probe/gate/repetition assists are cadence/claim triggered, not a mandatory fresh probe + judged redirect after every check. A cross-language keyword bucket would falsify C8/C9. The highest-frequency owner-local class is now closed for one validation only: declared JavaScript runner/interface reset commits `5c605088` and `be7c060c` use deterministic declared-runner/workspace facts plus one judged reset, preserve actual checker output, pin the exact runner and no-`node_modules` contract, and memoize definitive RESET/ON_TRACK outcomes. Capture tests include C6/C7 and repeated ON_TRACK; full pytest `4989 passed, 6 skipped`; independent re-review accepted. `cria.service` restarted and health returned OK. The single targeted Handles validation `c11-handles-rerun-be7c060c.service` (note `BATTERY2 L5 nemotron-elastic be7c060c p5`) exited after 106 calls. Authoritative packet `/home/jesse/.cria/suite/_usefulness_evidence/handles-cli-node_nemotron-elastic_codex_pon_1790148627.txt` was recorded at **30%**, and battery report refreshed; heartbeat `205ff126` was removed after terminal reporting. It has built-in fetch, Dockerfile, and a spawned-CLI test, but `npm test` has no script, test globals are unavailable, parsing still assumes `resolved_addresses.ada`, and it never queries the holder endpoint. The C11 generated workspace lacked a declared runner, so its intentionally scoped trigger could not fire. However, the proposed C5/C6/C7/C9/C11 shared premise is false: `docs/audits/2026-09-23-node-no-declared-runner-premise.md` verifies C5/C6/C7/C9 each did declare `scripts.test`; C9 also lacks a structured failed declared-runner transition. Commit `5c9da509` records this read-only proof (focused runner tests 5 passed; full suite `4989 passed, 6 skipped`) rather than broadening the assist dishonestly. No successor is authorized. The later requested C5/C9/C11 universal Handle CLI predicate is also rejected and recorded in `6487da01` / `docs/audits/2026-09-23-c5-c9-c11-node-cli-contract-predicate.md`: full frozen capture chains prove C5 correctly called `/holders/{holder}` and read `total_handles`, while C11’s test used `child_process.execFile` rather than a direct API fetch. C9 alone carries both asserted defects; OpenAPI/task facts were already model-visible. No valid generic assist or fixture correction follows from the false shared predicate.

### Other synthesis decisions

`~/.cria/walk-findings/2026-09-22/cross-cell-candidate-synthesis.md` is the citation-verified post-walk record. **C4 accepted as existing safeguard:** cart `seg-46` chunk179 CALL0233 unsupported `missing_content` is already suppressed by `_verify`/`_negative_diagnosis_nudge` without semantic interpretation while retaining `done:false`; capture-derived replay and valid checker-line adversarial test were Reviewer-accepted (historical 2/2 fails-before; focused 15 passed; full 4964 passed, 6 skipped). It is test-only and does not affect the closed Bonsai 2 row. C5 remains held. Feed and Rust have been rejected pending a language-neutral causal predicate. All Phase-2 walk coverage is complete.

### Candidate C1 — accepted

- **LANG:** `bundle install --path vendor/bundle` is a Bundler CLI contract, not Ruby task logic; the exact shipping capture records Bundler rejecting that option as removed.
- **MODEL:** the coder followed cria's denial verbatim, so the next failed command was induced by the tool surface rather than a judgment the coder could ground.
- **HARNESS:** `cria/dirguard.py` and its tests currently author the obsolete route; this is a model-agnostic refusal-message defect at the boundary.
- **Minimal proposed change:** replace only the obsolete Ruby/Bundler install route with a currently valid, project-local command; add a fails-before/passes-after denial/advice test; adversarially replay the exact denial shape before acceptance. Bonsai 2 risk is bounded to Ruby install-refusal wording and requires regression assessment after tests.
- **Acceptance:** independent Reviewer accepted C1 against exact CALL0209 after reading the capture and focused suite. Fails-before/passes-after deterministic replay is `test_exact_capture_denial_uses_bundler_4_project_configuration`; it feeds CALL0209's denied `gem install countries -v 0.9.3 -N --no-ri --no-rdoc -d .` to `dirguard.install_refusal` and proves the new route plus absence of `--path vendor/bundle`.
- **Implementation:** commit `7bbf9245` (`Fix obsolete Bundler install refusal route`) is pushed to `main`. Focused tests: 37 passed (Reviewer observed 40 related tests); full `python -m pytest`: 4957 passed, 6 skipped. `git diff --check` passed.
- **Live/Bonsai assessment:** `cria.service` restarted and `/health` returned `{"status":"ok"}`. The change is confined to a Ruby install-refusal route; no Bonsai 2 row was rerun yet, so non-regression remains open.
- **Comparable rerun launch repair:** initial root-owned detached unit correctly failed closed before swapping because `/root/.cria/codex-home/config.toml` was absent. The first corrected unit then exposed a shared harness environment issue: systemd's PATH lacked `codex`, so `suite/run.py` failed before spawning the harness (after the model/service swap). Corrected unit `c1-shipping-rerun-f0cc7fddc.service` runs as `jesse` with the interactive PATH, is active, GPU-serialized, and invokes shipping-rates-rb at L5/planner on with exact note `BATTERY2 L5 nemotron-elastic f0cc7fdd p4`. Heartbeat `f42a8a1c` is active. Its final usefulness remains pending.
- **Final C1 rerun judgment:** `shipping-rates-rb_nemotron-elastic_codex_pon_1790072412` exited after 124 calls; authoritative `suite/usefulness.py` judgment is **30%**, so shipping remains open (not >75%). Archive `/home/jesse/.cria/suite/shipping-rates-rb_nemotron-elastic_codex_pon_1790072412`; packet `/home/jesse/.cria/suite/_usefulness_evidence/shipping-rates-rb_nemotron-elastic_codex_pon_1790072412.txt`. The packet establishes that bundle install completed in-session; the archive-only absence of vendored dependencies is not evidence of a session dependency failure. The capture-derived C3 strategy reset separately rejects a speculative shipping rerun until new model-agnostic causal evidence exists.

*(One entry per accepted change: causal chain, commit, fails-before/passes-after test, full-suite
result, exact-capture replay evidence, service restart/health, and the comparable rerun(s) it
produced — plus the Bonsai 2 closed-row regression assessment.)*

## Campaign conclusion — 2026-09-23

**Terminal verdict: criterion not met; campaign stopped, not handed to a person.** The authoritative latest comparable cells are the six rows in the acceptance ledger above; none is strictly above 75%. There is no active suite unit, rerun heartbeat, scheduled successor, or authorized GPU work.

This is an evidence-backed conclusion about cria's unresolved delivery assistance, never an attribution to the coder. The complete campaign record rules out treating a green cria unit suite as delivery evidence: C5/C6 initial invalid-plan admission, C7 URL mutation, C8 Ruby calculation regression, C9 unverified CLI/E2E contract, C10 Go module-state churn, and C11's absent test script are distinct captured transitions. The consolidation sources are `global-terminal-delivery-reset.md`, `c6-c10-tooling-churn-reset.md`, `2026-09-23-node-no-declared-runner-premise.md`, and `2026-09-23-c5-c9-c11-node-cli-contract-predicate.md`; each contains full-packet/capture citations and explicit counterexamples to the proposed umbrella predicates.

The only highest-frequency owner-local candidate that passed capture tests was the declared JavaScript runner reset (`5c605088`, `be7c060c`), independently reviewed and live. Its single scoped C11 validation was 30%, and establishes a new boundary fact: C11 lacked the declared runner required to trigger it. The later frozen-workspace audit proves that this is not a C5/C6/C7/C9 common extension, so broadening it would be a keyword fallback rather than a causal fix.

**Final causal adjudication:** `/home/jesse/.cria/walk-findings/2026-09-23/final-c5-c13-causal-adjudication.md` is the authoritative reconciliation of this conclusion against every C5–C13 terminal packet and its cited complete decisive chains. Verdict: **NO CAPTURE-PROVEN TRANSITION**. This is not an attribution outside cria: it says only that the remaining terminal ceilings have no recorded still-unfixed cria owner/state transition that demonstrably changes the model-visible operative obligation before the actual failure. Earlier C5/C6 plan admission, C7 URL mutation, C10 living-tail/module paths, and C9 E2E coverage transition were real and repaired; C8's preservation branch and C13's green read-only checks are explicit counterexamples to turning them into an umbrella. The report's previous `0df61e4c` campaign conclusion is thereby confirmed, not reopened.

**Re-entry condition:** before any future single serialized rerun, an owner must select one cell, read its frozen packet and full decisive capture, identify a new deterministic cria-owned transition that precedes that cell's actual failing check, and land a capture-shaped fails-before/passes-after test whose replay changes that transition. Full pytest, independent review, push, service restart/health, and exactly one target-language rerun with one heartbeat are then required. No aggregate hypothesis, planner label, score pattern, or passing proxy test authorizes a rerun.

**C9 execution:** full C9 capture inspection found one preceding, bounded owner: a later planner coverage transition explicitly accepted a direct upstream API request as the required end-to-end test, immediately before the archive's direct-API test. Wrong `resolved_addresses[0]` parsing and absence of `/holders/{holder}` predate that event and are not claimed fixed. Commit `e70127e3` changes the coverage prompt to distinguish CLI/tool invocation from upstream API access and adds a capture-shaped failing/passing planner regression; full pytest passed `4990 passed, 6 skipped`, push/restart/health are complete. Independent review accepted the C9 boundary (planner tests `107 passed`); the scoped C12 validation was launched as `c12-handles-rerun-e70127e3.service`, note `BATTERY2 L5 nemotron-elastic e70127e3 p6`, planner on/L5. It was deliberately stopped before terminal evidence when its initial live workspace again had no test files/Dockerfile and `npm test` had no script; this is non-comparable and has no usefulness packet. Heartbeat `ab529088` was removed after the stop report. The C5/C9/C11/C12 holder-endpoint reconciliation is complete in `03bdc3ac` / `docs/audits/2026-09-23-c5-c9-c11-c12-holder-predecessor-reconciliation.md`: full traces disprove the asserted universal predecessor. C5 correctly used `.ada` and `/holders/{holder}`; C11 had the correct address shape; C12's partial script built the holder request. C9 alone had both defects. No behavioral candidate follows.

**C10 single-cell execution:** Cart's full C10 capture selected the actual failing transition: a typed failed Go module test was delivered without a fresh read-only module-state recovery boundary, after which the coder speculated and degraded `go.mod`. `e5e45138`, repaired by `485f6d58`, adds command-associated, one-shot REANCHOR/ON_TRACK judgment from read-only `go test`/vet facts, preserving checker output and forbidding package/version/API guesses. It has C10 periodic-gate capture replay including an omitted preceding probe section; full pytest `4994 passed, 6 skipped`; independent repair review accepted. Service restart/health succeeded. The sole C13 Cart validation `c13-cart-rerun-485f6d58.service` exited after 386 calls; final packet `/home/jesse/.cria/suite/_usefulness_evidence/cart-billing-go_nemotron-elastic_codex_pon_1790152793.txt` is recorded at **25%**, battery report refreshed, and heartbeat `7d545342` removed. Its archive is the unchanged seed float implementation (`cart.go`, `cart_test.go`, `go.mod` only): Go test passes but no requested decimal/rounding/JSON/fallback/stderr work was delivered. No successor GPU work is authorized.

## Campaign resumption — 2026-09-23

The prior `Campaign conclusion` section is superseded as an orchestration failure, not campaign closure: all six strict cells remain open and the root criterion is unmet. Reconciled live state at resumption: `main` is `da471763`; no repository dirty paths, active battery queue, or active run heartbeat; `cria.service` and `llama-nemotron-elastic.service` are healthy, serving `nemotron_elastic_12b_a2b_q4km` with `n_ctx=49152`. The latest Cart comparable row is C13 (`cart-billing-go_nemotron-elastic_codex_pon_1790152793`, 25%), correcting the stale table entry above. Preserved evidence remains under `~/.cria/suite/`, `~/.cria/calls/`, and `~/.cria/walk-findings/`.

## Ledger reconciliation — 2026-09-24

Resumed from `a54cce45` (clean `main`, no suite unit/heartbeat active, `cria.service` active). The
acceptance table was stale (it still listed Phase-0 / C8 / C19 / C20 rows). Reconciliation against
`suite/results/results.jsonl` and `~/.cria/suite/_usefulness/` found a **measurement-record defect**:
the fourteen terminal rows p8–p21 except p19 (`1790190648` … `1790255585`) had frozen
`_usefulness_evidence` packets but **no recorded `suite/usefulness.py` verdict** and no
`usefulness_percent` on their rows (`usefulness.py pending` listed all fourteen). The dated sections'
"final packet records N%" wording referred to evidence packets, not recorded judgments. Each was
judged now by the Supervisor from the archived workspace with the real checks rerun, and recorded:

| Run | Note | Recorded | Deciding check |
|---|---|---:|---|
| `cart…_1790190648` | `0dbf1441 p8` | 5% | only `discounts.json` added; seed `go test` passes |
| `cart…_1790198063` | `08215092 p9` | 50% | `go test`: undefined `decimal.ROUND_HALF_UP`, `ToFloat64` |
| `handles…_1790205888` | `810a517e p10` | 50% | working fetch CLI; `npm test` missing script |
| `handles…_1790210315` | `cdf0e2f2 p11` | 50% | `npm test` → `lookup.js` still requires `request` |
| `handles…_1790213771` | `027e9de2 p12` | 0% | unchanged seed |
| `handles…_1790216479` | `3206b06b p13` | 45% | working CLI; no test script |
| `handles…_1790217729` | `69d8e894 p14` | 70% | `npm test` green but API-only test |
| `handles…_1790223605` | `bf8fe41d p15` | 0% | unchanged seed |
| `orders…_1790228055` | `0df1c4dd p16` | 40% | pytest hangs after two seed tests |
| `handles…_1790231549` | `3cf2697a p17` | 70% | live CLI correct (holder endpoint, exit 1 on 404), spawned-CLI test passes; `npm test` red: `real-api.test.js` requires removed `node-fetch` |
| `cart…_1790238295` | `ad8a8c9b p18` | 0% | `git status` clean |
| `orders…_1790242392` | `ad8a8c9b p18` | 50% | route/migration/index/parameterized query present; integration `setUp` binds port 0 then polls port 0 forever |
| `rust…_1790252780` | `c435329c p20` | 30% | `cargo test`: unresolved `toml::Error`; also `env::argc`, `Value::parse_str`; integers print a placeholder |
| `shipping…_1790255585` | `a9087c45 p21` | 35% | `require 'countries'` unloadable; no `Shipping.zone_for` (duplicated `zone_for_code` using `Country.new(code).in_eu?` as a `when` value); express test outside the rake glob; seed tests pass with the require removed |

Rust p20 is recorded at 30%, not the 35% milestone figure quoted in its dated section; all others
match the dated sections. `usefulness.py pending --since 1790000000` is now empty.
**Feed-pipeline-java has had no comparable rerun since Phase 0** (`1790068525`, 20%) although ~40
accepted changes landed after it; it is the first measurement due.

### P22 Feed launch — 2026-09-24

Feed-pipeline-java had no comparable measurement since Phase 0, so it was run first at the
reconciled HEAD: `p22-feed-rerun-9ded52bc.service` (user unit, not collected), script/log
`~/.cria/nemotron-l5-p22-feed-9ded52bc.{sh,log}`, flocked, note `BATTERY2 L5 nemotron-elastic
9ded52bc p22`, planner on/L5. Exactly one recurring 10-minute heartbeat: `67248cb2`.

### P22 Feed terminal result

- Comparable run `feed-pipeline-java_nemotron-elastic_codex_pon_1790268418` (`BATTERY2 L5 nemotron-elastic
  9ded52bc p22`) ended `milestone-stalled-45min` after **190 calls**; milestones 30min 20% continue,
  45min 20% stalled; final usefulness **20%** (`suite/usefulness.py`), battery report refreshed,
  heartbeat `67248cb2` retired.
- Archive: Commons CSV dependency, large `Importer.java` rewrite, `REVIEW.md`; `mvn -o test` fails on
  invented Commons CSV members (`CSVParser.DEFAULT_FORMAT`, `readHeader`, `readNext`, `CsvException`) and
  other missing symbols; rows accumulated twice; `main(String)`; no tests. The planner fetched no CSV
  documentation; 30→45 min the coder issued ~20 consecutive `read_file`s of `Importer.java` with
  degenerate-rumination aborts and no steer. Same class as Rust P20's second half (see C31 and the
  invented-API lead).

### Candidate C28 — gate blind to a check that outlives the harness exec yield

- **Observed chain (P18 Orders, session `20260924T023334-01a0d2c3`):** the coder wrote an
  integration test whose `setUp` polls port 0 forever. Raw inbound capture
  `inbound-ce7f6c3d-responses.json` shows cria's composed gate `exec_command` carrying
  `"yield_time_ms": 300000`, and Codex returning `Wall time: 30.0008 seconds / Process running
  with session ID 51757 / Output:` (and in a later gate `441.6866 seconds / Process running`), with
  no transport opener. `probegate.ingest_transport` → `fail_transport("transport page opener did
  not arrive")` → the coder receives `probe_transport_unknown.txt` ("did not arrive completely …
  UNKNOWN") — 28 of 29 gates in that session (`gate.transport_unknown` events). The composed
  script's own `timeout -k 5 240` would have produced exit 124 plus the partial pytest output
  (`..` then the hanging test id), which `interpret_gate` already renders as "a check did not
  finish (timed out) … It printed this before it was stopped", but that byte stream never reached
  cria. Meanwhile the coder's own `pytest` calls returned `Process running … Output: ..`, which its
  reasoning read as success (CALL0092: "pytest exits with success code 0 and no output").
  C26 Orders (`01a0d1e8`) had 4 such unknowns with the same hang; Handles C9 (`01a0ccbe`) logged 8
  `opener did not arrive` at offset 0 (no raw inbound capture exists for it, so its shape is
  corroboration only).
- **Owner:** `probegate.plan_gate` script composition + `loop.guard_gate_transport` bridge. The
  gate's correctness depends on the harness honoring a 300 s yield; Codex does not (clamps/returns
  early), and nothing polls the still-running script.
- **Candidate:** make the gate script's completion observable across turns without trusting the
  harness yield: run the composed probe block detached into the existing spool, have the reader
  wait a bounded interval for a completion marker, and return a typed *running* envelope when not
  done; the existing transport bridge re-issues the read (read-only, idempotent) until completion
  or a cria-side deadline derived from the probes' own timeouts, then pages as today. A hang then
  surfaces as the existing exit-124 timeout rendering with the real partial output (tool voice
  preserved). Deadline exhaustion stays explicit UNKNOWN (fail closed).
- **LANG / MODEL / HARNESS:** keys on a transport state (script not finished), not on any runner,
  language, model, or error text; uses only the shell primitive every harness has; a harness that
  honors long yields sees the first read complete inline, so its turn count is unchanged.
- **Additive / regression-only:** changes no verdict for a gate that already completes within the
  yield; replaces UNKNOWN with the check's own output only when the check actually finished.
- **Bonsai 2 risk:** shared gate transport; fast gates must stay byte-for-byte equivalent in
  interpreted result and not gain turns. To be asserted by tests.
- **Measurement constraint:** implemented while p22 is active, so no existing file under
  `cria/prompts/` may be modified and `cria.service` must not be restarted until p22's terminal
  packet is recorded.

### Candidate C29 — declared test entry point withheld by a quote-blind shape check, then reported absent

- **Observed chain (C27 Handles, session `20260923T233251-01a0d21d`):** CALL0316 the coder added
  `__tests__/real-api.test.js` requiring `node-fetch`; CALL0336 wired `package.json`
  `"test": "node __tests__/integration.test.js && node __tests__/real-api.test.js"`; CALL0352 its
  own `npm test` exited 1 (`Cannot find module 'node-fetch'`). CALL0364 the satisfaction judge
  approved anyway (reasoning: the tests "exist"); the C23 participation barrier held completion
  (CALL0365 `REQUIRED`). But the coder-bound message at CALL0366 then said: "the repo's own checks
  that ran reported no error-class problems. The checks above cover syntax only — no test command
  was composed … Test files for jest/vitest are present …, but no command to run them was found in
  this project", and the steer opened "The repo's automated checks pass". Both contradict the
  project's declared script and the coder's own red run. The coder never repaired the import;
  CALL0372 claimed it had, CALL0373 the judge (correctly) named it, and the run stalled at 60 min
  with `npm test` red (70%).
- **Owner:** `probediscovery.build_js` drops a declared script when the classifier does not
  recognise its body AND `_COMPOUND_SCRIPT` (`&&|\|\||[;&|]`, not quote-aware) matches. C27's
  `node a && node b` is dropped as compound; C21 (`handles…_1790210315`, 50%) declared
  `node -e "require('./test/handle-resolver.test');"` and was dropped only because of a `;` inside
  double quotes. `probediscovery.tests_with_no_command` then renders "no command to run them was
  found in this project" — a false fact (#5b) whenever a declared test entry was withheld rather
  than absent.
- **Prevalence (final archived workspaces, all models):** 56 declared allow-listed scripts; 2
  withheld — exactly these two nemotron Handles runs.
- **Candidate:** (a) decide "compound" from the existing quote-aware shell structure in
  `probeclassify` (operators outside quotes), and admit an exit-status-preserving `&&` chain whose
  every segment would be admitted alone and passes `has_unsafe_segment`; keep rejecting `;`, `||`,
  `|`, `&`, and newline chains (they can mask a failure or background a service → false green).
  (b) When a declared test entry exists but was withheld, never say "no command … was found"; state
  the withheld declaration truthfully.
- **LANG / MODEL / HARNESS:** the rule is shell semantics (quoting; exit-status propagation of
  `&&`), not a runner, package, or error keyword; it lives in the shared shell-structure owner and
  the one adapter that reads declared script bodies. Not a remedy or steer: the gate simply runs
  what the project declares and reports the tool's own output.
- **Additive / regression-only:** admits strictly more declared commands under the same safety
  vet; a previously admitted body is unchanged. Bonsai 2 risk: a Bonsai workspace with an `&&`
  test chain would now be exercised by the gate (none in the archive).

### Candidate C30 — an exhausted plan-admission guard re-plans forever and no coder ever runs

- **Observed chain:** Cart P18 (`20260924T012515-01a0d284`, 814 calls, 0%): 775 planner calls, 38
  proxy calls, **zero coder calls**, no `loop.start`. Events: `plan.host_unread hosts=discounts.json,go.mod`
  → `plan.rejected_exhausted check=host` → `plan.retriable`, repeated six times (plus one
  `check=url`), for 35 minutes. The host judge (CALL0016) received the task-named file
  `discounts.json` as an "unread name" and its reasoning never applied the criteria ("That is a name
  that remains unread … So we must output that name"). The same terminal shape — admission rejected
  → retriable → re-gather every turn → no plan session, no coder — ended C22 (`01a0d10e`, 0%) and C25
  (`01a0d1a4`, 0%) on Node. Three 0% runs, two languages.
- **Owner:** `planner.Planner._gather_and_plan`: every exhausted admission guard (url, host,
  coverage, test-execution, undecidable/not-applicable readiness) sets `_retriable_failure = True`.
  `Loop` treats a retriable failure as "re-plan next turn" and skips its existing fallback
  (`_synthetic_plan` → guarded single-item raw-task drive, which keeps gate/guards/steers). So a
  guard that keeps rejecting (correctly or not) blocks all coding unboundedly — failing closed on a
  non-completion decision, against #13 ("fail open only toward keep working") and #2 (never block
  the first fix).
- **Candidate:** keep C7's invariant (a draft cria rejected is never admitted as the plan cursor),
  but an exhausted admission guard is a planning give-up, not a transport retry: the session falls to
  the existing synthetic single-item guarded drive for that task. Transport/model errors and survey
  deferral stay retriable.
- **LANG / MODEL / HARNESS:** keyed on the planner's typed outcome, not on any guard's content,
  language, or model. The fallback path already exists and is exercised for unparseable plans.
- **Additive / regression-only:** changes nothing when a plan is admitted; converts an unbounded
  no-work loop into guarded work on the raw task. Bonsai 2 risk: sessions whose guard exhausted and
  whose later re-gather would have produced an admissible plan now proceed on the raw task instead.
  Measured prevalence of that recovery must be checked in logs before landing.

### C28/C29/C30 cohort — integrated, reviewed

- Commits `1a89220b` (C28), `42605223` (C29), `ab1e4e68` (C30); integrated `python -m pytest` **5070 passed,
  5 skipped**; `git diff --check` clean. Not yet live (cria.service not restarted).
- Independent review: **C29 accepted** (7/16 new tests fail on `fda145eb`, pass after; quote tracking
  identical to `split_chain`). **C28 rejected**: reproduced on real Codex 0.156 (`codex exec --yolo` against a
  fake Responses server) that the `.done` marker and cmd cleanup run in a wrapper subshell killed with the
  harness process group, so a finished >8 s gate never reads as done and ends UNKNOWN at the deadline — a
  regression against pre-C28 inline completion. **C30 rejected**: the give-up writes the process-wide
  task-text-keyed negative cache, so a later session with the same task never plans (#23). Both repairs are
  assigned to their original owners with the reviewer's reproductions.

- **Repairs and re-review (accepted):** C28 `b7be2ef9` moves the `.done` write and cmd cleanup inside the
  detached `setsid` session (fails-before killpg test reconstructs the pre-repair guard); re-review on real
  Codex: 14 s probe → running ×3 then complete, fast probe 1 turn as before, no leftovers — but found the new
  `umask 077` leaked into probes (probe `umask` 0077, a 0o644-asserting check turned red). `57fed0f6` scopes
  the umask to cria's two files only; re-review: probes `0022`, workspace file `0o644`, spool/cmd `0600` —
  **C28 accepted**. C30 `64155d4d` removes the process-wide negative cache and keys the exhaustion count by
  (session, task), threaded from `Loop._plan_for`; re-review: session B with the same text now plans (6
  reasoner calls, `plan.submitted`; 0 before), P18 shape with a deferral every turn still gives up
  boundedly through the real Loop; 5/9 new tests fail on `ab1e4e68` — **C30 accepted**. Non-blocking
  follow-ups recorded by the reviewer: unstable `task:` session keys re-plan each turn (Codex uses stable
  `sid:`); counter entries not pruned; the pre-existing unparseable-plan negative cache keeps its
  cross-session property; one C28 permissions test leaves an empty `.done` in `/tmp`; C29 now admits npm's
  default failing `test` stub (0 of 627 sessions); a script withheld as *unsafe* is still told "Run it
  directly".

### Live: C28+C29+C30 (`c6e97a5d`); C31 rejected and reverted pending repair

- C31 review (commit `8a53a245`): P20 shape fails-before/passes-after (6/9), visibility ordering and session
  key verified, "not blocked" true — but **rejected**: `server._harden_compaction_reply` renders the ledger
  with no session, freezing "Its body is NOT in this conversation" into harness compaction history; after the
  invited re-fetch the live block says "in this conversation above" for the same URL and ledger elision no
  longer collapses them (reviewer repro `/tmp/c28rev/c31contra.py`). Reverted on main (`c6e97a5d`) so the
  accepted cohort could go live; repair assigned to the C31 owner (location-free frozen copy).
- Integrated suite at `c6e97a5d`: **5079 passed, 5 skipped**. `cria.service` restarted, `/health` ok.
- **P23 Handles launched** (cell closest to closure; C27's decisive transition is C29's): unit
  `p23-handles-rerun-c6e97a5d.service`, script/log `~/.cria/nemotron-l5-p23-handles-c6e97a5d.{sh,log}`, note
  `BATTERY2 L5 nemotron-elastic c6e97a5d p23`, planner on/L5; `run.py`'s own cria restart (11:32:25) preceded
  the C31 owner's re-application (11:32:32), so the run executes clean `c6e97a5d`. One heartbeat: `888cb7b7`.

### Candidate C31 — fetch ledger claims a page body is "in this conversation above" when it is not

- **Observed chain (Rust P20, `20260924T052642-01a0d361`):** the planner fetched
  `https://docs.rs/toml/latest/toml/`, `https://crates.io/crates/toml` and
  `https://docs.rs/crate/toml/latest/source/`; the coder never fetched anything. Every later coder
  body carries `⟦ctx:facts⟧ PAGES YOU HAVE ALREADY FETCHED — these SUCCEEDED … Its body is in this
  conversation above`, closing "code against THOSE rather than re-fetching". After compaction the
  coder body at CALL0120 has five messages and no page body. Coder reasoning repeatedly says "Let's
  verify by reading the crate's documentation" (CALL0099, 0141, 0149, 0150) and then recalls the API
  from memory (`get_map`, `Value::parse_str`, `toml::Error::Missing` — none exist); the run stalled
  uncompilable (30%). The exact-repeat fetch gate is visibility-aware, so a re-fetch would have been
  allowed; only cria's false location statement discouraged it.
- **Prevalence (campaign coder prompts 2026-09-22..24):** 1,821 `body_inline` claims, 1,045 with no
  fetch of that URL anywhere in the body the coder received (Rust P20 336/336, Shipping P21 128/128,
  Handles C27 155/200, Cart/Orders/Handles others 2–84).
- **Owner:** `loop._format_fetches` renders `fetched_facts_sections.body_inline` for every
  no-structure 2xx page that was not spilled, without checking the messages being sent.
- **Candidate:** render `body_inline` only when that URL's result is actually visible in the outgoing
  messages (same visibility owner the exact-repeat gate uses); otherwise state truthfully that the body
  is not in this conversation. No new advice, no re-fetch instruction beyond the true fact.
- **LANG / MODEL / HARNESS:** pure provenance of cria's own ledger; applies to any page, any
  language. **Bonsai 2 risk:** wording change only where the old sentence was false.
- **Timing:** touches `loop.py` (C28 in progress) and requires a prompt-map key; implement after C28
  lands and after p22 terminates (existing prompt file must not change during a live run).

- **C31 re-landed and accepted:** `34b70d4a` re-applies `8a53a245` with a location-free frozen compaction copy
  (`server._harden_compaction_reply` → `location=False`) and bound-before-insert in `set_visible`; re-review found
  the `no_spec_here` label's own "its body is in the transcript above" still contradicted the absent sentence (799
  coder prompts carry that label, all 200 of C27). `7de23bdd` adds a location-free `no_spec_here` variant (new
  prompt file only) whenever visibility is known or the copy is frozen; re-review with both reproductions: exactly
  one location claim per URL across the coder body, none in the frozen copy — **accepted**. Owner full suite
  5098 passed, 5 skipped. Goes live at the next restart after p23 (non-blocking: the now non-identical
  frozen/live one-line entries are no longer elided, so that line appears twice without contradiction).

### P23 Handles terminal result — C29 engaged; new false completion hold (C32)

- Comparable run `handles-cli-node_nemotron-elastic_codex_pon_1790274745` (`BATTERY2 L5 nemotron-elastic c6e97a5d p23`)
  ended `milestone-stalled-45min` after **327 calls**; milestones 30min 65% continue, 45min 65% stalled; final
  **65%**; battery report refreshed; heartbeat `888cb7b7` retired.
- Archive: dependency-free built-in-fetch `index.js` (holder endpoint, `--json`, `--help`, exit 1 on unknown
  handle), `request` removed, Dockerfile, declared `npm test` spawning the CLI against the live API — green.
  Gaps: handle only via `--handle`, old `lookup.js` still requires `request`, no failure-path test.
- C29 engaged: the gate composed `npm run test` and fed its red output ("describe is not defined") to the coder,
  which then repaired the test script. C28/C30 not exercised (no hang, plan admitted).
- **Decisive transition (C32):** once `npm run test` was green (exit 0, `executed_test_sources` =
  `test/real.test.js`), `participation.collect` still reported test `participated/passed = unknown` because the
  plain test program prints no runner tally; the satisfaction judge said `satisfied:true` (0291) but the C23
  barrier (`test_participation_requirement REQUIRED`, support unknown) held completion from 30 to 45 min, telling
  the coder its required tests were unproven. Owner-local fix assigned: a completed declared test interface whose
  body maps an executed test file counts as participation with `passed = exit==0`.

### C32 landed (review pending); P24 Orders launched

- C32 `3d82a022`: a completed declared test interface whose body executes a mapped test file counts as test
  participation (`passed = exit==0`); tally precedence kept; timeout/launch failure/unmapped stay unknown. 6/8
  new tests fail before; integrated full suite **5106 passed, 5 skipped**. Independent review in progress.
- **P24 Orders** launched at `3d82a022` (C28 gate transport, C29, C30, C31 live; C32 present but inert for this
  cell — `declared_interface` is set only by `probediscovery.build_js`): unit `p24-orders-rerun-3d82a022.service`,
  script/log `~/.cria/nemotron-l5-p24-orders-3d82a022.{sh,log}`, note `BATTERY2 L5 nemotron-elastic 3d82a022 p24`;
  `run.py` restarted cria at 12:52:58, `/health` ok. One heartbeat: `8c72974f`.

### C32 accepted; C33 candidate; C28b live defect in P24

- **C32 accepted** after repair `993c315b` (failing `&&` chain → participants unknown; E2E judge receives only
  executed sources; inference limited to bare or `&&`-only bodies). Re-review: P23 shape PROVEN, exit 1 FAILED,
  tally precedence, timeout/wrappers unknown; 28 C29/C32 tests pass; owner full suite 5110 passed, 5 skipped.
- **C33 (in progress):** 47 of 181 periodic check-ins (26%) in 2026-09-22..24 logs were survey-only
  (`periodic_gate_result ran=False` + `loop.gate_survey_only`) and said nothing — the completion path replans after
  a survey-only result but `guard_periodic_result` does not. Feed P22 had 5 of 7, covering its entire 30→45 min
  stall (so `gate_stall` never advanced and the thrash steer could not fire); Handles P23 5 of 8.
- **C28b (live defect, P24 Orders, session `01a0d4fa`):** C28 engaged (`gate.transport_running`) on the hanging
  integration test, but each running poll resends the ~7 KB launch script; after ~12 polls Codex compacts its
  history, `guard_probe_reissue` composes a NEW gate (survey-only → replan → new detached gate), abandoning the
  running one before its 240 s timeout; this repeats every ~100 s (20:02:07, 20:03:49, 20:05:32, 20:07:14 …) with no
  coder turn. Repair assigned to the C28 owner: running envelope carries the resolved path (narrow polls), a
  compaction during a running transport re-polls the same plan, and polls use the tool's declared yield budget.
  P24 is left to reach its canonical milestone (a valid measurement of `3d82a022`).

### P24 Orders terminal result

- `orders-api-py_nemotron-elastic_codex_pon_1790279578` (`BATTERY2 L5 nemotron-elastic 3d82a022 p24`) ended
  `milestone-stalled-30min` after **70 calls**; milestone 30min 40% stalled; final **40%**; battery report refreshed;
  heartbeat `8c72974f` retired.
- Archive: in-place status migration + customer index, parameterized lookup, customer route (no aggregate total);
  integration test calls `serve()` in `setUp` and hangs. From 13:02 the workspace never changed: the session sat in
  the C28b reissue loop (15 `loop.probe_reissued`, zero coder actions). The same hang class as C26/P18; C28 now
  sees the check running, but C28b prevents it from ever finishing.

### C28b + C33 accepted; live

- `6510f2dd` (C28b + C33) review: P24 compaction-while-running path verified on real Codex (narrow 1.75 KB polls
  after the first running reply, same-transport poll after compaction, timed-out rendering with partial output,
  25 s waits honoured, fast gate 1 turn); **C33 accepted** (one replan per check-in, periodic semantics, red result
  advances `gate_stall`). C28b rejected on a lost *final* page (reader had unlinked the spool → phantom `running`
  until deadline). Repair `6d78545c`: reader never unlinks, typed `gone` envelope, completed spools removed by exact
  path at the next gate; re-review on real Codex: lost final page recovered immediately with identical bytes —
  **C28b accepted**. Integrated suite **5131 passed, 5 skipped**. Non-blocking: last spool per workspace remains in
  `$TMPDIR` (0600) until the next gate/restart; gate tests leave spools in `/tmp` (teardown follow-up).
- **P25 Handles launched** at `9fab19d9` (C28/C28b, C29, C30, C31, C32, C33 live): unit
  `p25-handles-rerun-9fab19d9.service`, script/log `~/.cria/nemotron-l5-p25-handles-9fab19d9.{sh,log}`, note
  `BATTERY2 L5 nemotron-elastic 9fab19d9 p25`; cria restarted by `run.py` at 14:29:53, `/health` ok. Heartbeat `52d268fb`.
- Rejected lead (prevalence): a "task-quoted identifier absent from workspace" fact for completion judges — measured
  over all 33 campaign archives, only Shipping P21/C8 had a meaningful absent name (`Shipping.zone_for`); the rest
  were noise (`node_modules`, `go.mod`, files the task asks to create). Not built.

### P25 Handles terminal result

- `handles-cli-node_nemotron-elastic_codex_pon_1790285393` (`BATTERY2 L5 nemotron-elastic 9fab19d9 p25`) ended
  `milestone-stalled-45min` after **276 calls**; milestones 30min 35% continue (argv regression), 45min 50% stalled;
  final **50%**; heartbeat `52d268fb` retired.
- Archive: built-in-fetch positional CLI, `--json`/`--help`, exit 1 on unknown, Dockerfile; `handle_count` =
  `data.length`; no `test` script; tests assert the address equals the handle.
- C33 engaged (`loop.periodic_replan_after_survey`). The C23 barrier correctly held (no executed tests). Decisive
  cria transition: satisfaction verdicts named real defects (0136: the test asserts `'goose'`), but every
  negative-diagnosis support question was lost to the 16-token cap (C34), 10 suppressions, so the coder only ever
  received "the check did not name which deliverable is unfinished".

### Candidate C34 — 16-token caps on one-word judges: 69 of 69 answers lost

- Census over every nemotron campaign capture (2026-09-22..24): each call with `max_tokens: 16` (reasoning
  `none`, temperature 0) returned empty content, `finish_reason: length` — **69/69**: compaction-validate 18,
  module-state 10, satisfaction-diagnosis 9, critic-diagnosis 9, critic-confirm-diagnosis 5, runner-reset 5,
  test-participation-requirement (capped variant) 15, test-e2e-requirement 2, retries 2. The model emits a short
  reasoning preface even with reasoning off; the cap cuts it before the word. The same questions at 1024 tokens
  answered 38/38. Consequences: every self-compaction candidate rejected; C10 Go module-state and declared JS
  runner-reset assists never able to fire; correct negative diagnoses suppressed — e.g. live P25 `0136`
  satisfaction named the real defect (test asserts `resolved_address == 'goose'`), `0137` support answer lost →
  `negative_diagnosis_suppressed`, coder got "the check did not name which deliverable".
- Owner: `cria/loop.py` `max_tokens=16` at the judge call sites (principle #6 violation). Fix assigned: shared
  judge budget, reasoning off, strict parsing unchanged, no retries. Model-agnostic; for models that answer inside
  16 tokens nothing changes except the ceiling.

- **C34 accepted** (`9002f8ba`): reviewer recount 76/76 empty at 16 tokens (P25 added), 49/49 answered at 1024 (max
  364 output tokens); read P25 `0137` and C13 `0215-module-state` in full; no tiny caps remain; parsing/retries
  unchanged. Newly live paths to watch: self-compaction acceptance, module-state/runner-reset steers, delivered
  negative diagnoses and E2E participation verdicts. Follow-ups: unify `ask_closed`'s 1024 default under
  `JUDGE_MAX_TOKENS`; module-state judge context contains raw gate transport text (pre-existing).
- **P26 Cart launched** next (C30's cell; also first live run of C34).

### P26 Cart live observations; Candidate C35

- P26 (`785d6523`) Cart: **C30 fired exactly on the P18 shape** — `plan.rejected_exhausted check=host` ×2 →
  `plan.admission_given_up` → `loop.start synthetic=True planner_fallback=True` within 35 s; the coder was working
  (192 coder calls by 10 min vs **0** in P18).
- **C35:** with C34 live the module-state judge now answers, but as the coder ("**Files that were changed / added**",
  reasoning "We need to respond with final answer…"): its prompt is one 100 KB system message containing the serialized
  session with raw gate transport base64 and the harness frame. Census: raw `___CRIA_GATE_TRANSPORT_`/`___CRIA_SURVEY_`
  in module-state 19/19 and runner-reset 7/7 judge prompts, no other phase. Owner: both steers serialize
  `_reasoner_session(...)` without `probegate.clean_gate_results` / `_drop_harness_frame`, unlike every other reasoner
  consumer. Fix assigned (reuse the shared scrub; no prompt change).

### P26 Cart terminal result; C35 accepted; C36 in progress

- `cart-billing-go_nemotron-elastic_codex_pon_1790289581` (`BATTERY2 L5 nemotron-elastic 785d6523 p26`) ended
  `milestone-stalled-45min` after **243 calls**; milestones 30min 30% continue, 45min 25% stalled; final **25%**;
  heartbeat `78b4e05e` retired. C30 turned P18's 0-coder session into real work (discounts.json + fallback, decimal
  Total with stderr log, 48.58 regression test) but `go.mod` pins nonexistent `shopspring/decimal v0.57.0`, no
  `go.sum`, invalid decimal APIs, discount multiplied instead of subtracted.
- **C35 accepted** (`0ee35ea7`): offline replay of P26 0068 — judge session 92.9K→25.0K chars, zero transport markers,
  zero "cria", no harness frame; coder actions and checker output retained. Reviewer found the remaining prompt shape
  (session is the last text, no trailing one-token instruction) still invites a coder-role answer → **C36** (prompt
  restatement, now allowed since no run is live) assigned.

### Row p27 freeze

- **C36 accepted** (`aae1d664`): replayed P26 0068 prompt now ends with "Return exactly `REANCHOR` or `ON_TRACK`.",
  28.6K chars, zero "cria"; parser unchanged; sweep found no other closed-verdict judge ending in raw transcript.
  Non-blocking: strip backticks before the strict compare (module-state and runner-reset).
- Row p27 contains C28 (+ review repairs), C28b, C29, C30, C31, C32, C33, C34, C35, C36 — all independently
  reviewed and accepted; integrated full suite 5143 passed, 5 skipped. Row HEAD = the commit recording this entry.
  Queue: every open cell (all six are open at freeze), one note, one heartbeat; no behavior change may land until the queue ends.

### Row p27 launched

- Row HEAD **`f6df9eea`** (full suite 5143 passed, 5 skipped; `cria.service` restarted, `/health` ok). Queue
  `row-p27-f6df9eea.service` (user unit, not collected) runs `~/.cria/nemotron-l5-row-p27-f6df9eea.sh`: six cells in
  order shipping → cart → orders → feed → handles → rust, each flocked on `suite-gpu.lock`, note
  `BATTERY2 L5 nemotron-elastic f6df9eea p27`; the script aborts before a cell if HEAD moved or `cria/` is dirty.
  Log `~/.cria/nemotron-l5-row-p27-f6df9eea.log`. Started 16:47:21. One heartbeat: `44347c64`.
  Queue defect found and routed around without touching the running cell: the first script's guard compared
  `HEAD`, which this doc-only ledger commit (`4813fec3`) moved, so it would abort after shipping. Continuation unit
  `row-p27-f6df9eea-cont.service` (`…-cont.sh`) waits for the first unit to exit, then runs cart → rust at the same
  note, guarding only the live-behaviour tree (`cria/`, `suite/run.py`, `suite/sampling.py` identical to `f6df9eea`,
  `cria/` clean). The first unit's expected `ABORT before cart-billing-go` line is this handover, not a failure.

### Row p27 — cell results as they finish

- **shipping-rates-rb** `…_1790293641`: `milestone-stalled-60min`, 289 calls; milestones 15/continue, 20/continue,
  15/stalled; final **15%** (regressed from 35%). Archive: README rate table, countries gem, express/zone_for
  scaffolding, but `case … when ZONE_BASE.key?(x)` breaks every zone (5/7 seed tests error), undefined
  `Shipping::Country`, surcharge dropped on free shipping, no express tests. Queue handover worked
  (first unit ABORT line, continuation START cart 18:00:41).

- **cart-billing-go** (active): 30-min milestone recorded 20%/continue. **Process defect:** the checkpoint froze at
  18:30 and its judgment was only recorded at 20:20 — heartbeat firings in between were not processed. `run.py`
  measures active minutes, so the cell's measurement is unaffected, but the queue lost ~110 min. Rule applied from
  here: every heartbeat first clears `suite/milestones.py pending` for the row's run ids before anything else.

- **cart-billing-go** `…_1790298041`: `milestone-stalled-60min`, 290 calls; milestones 20/continue, 30/continue,
  30/stalled; final **30%**. Real `shopspring/decimal v1.4.0` + go.sum resolved (an improvement over p26's invented
  version), discounts.json + fallback, decimal path, stderr log, 48.58 test — but compile fails from 45→60 min on
  `NewFromString` single-value use and nonexistent `Quantize`/`RoundingModeCeiling` (invented API class again).

- **Row walks started while the row runs (read-only):** p27 shipping capture `20260924T164732-01a0d5d1` → 95 segments
  (`~/.cria/walk-findings/2026-09-24/p27-shipping/`), p27 cart `20260924T180052-01a0d614` → 80 segments
  (`…/p27-cart/`). Wave 1: shipping seg-01..10, ten fresh read-only walkers; later waves follow after each wave's
  finding files are verified. Row p28 will be frozen at a NEW HEAD containing the fixes this row justifies (not
  `f6df9eea`) and will queue only cells still ≤75%.

- **orders-api-py** `…_1790308843`: `milestone-stalled-45min`, 170 calls; milestones 35/continue, 35/stalled; final
  **35%**. Migration + index + parameterized lookup + customer route, but the route raises on `sqlite3.Row` attribute
  access and the integration test calls `serve_forever` inline (hang) — the Orders hang class for the fourth run.

- **feed-pipeline-java** `…_1790312004`: `milestone-stalled-45min`, 174 calls; milestones 20/continue, 20/stalled;
  final **20%**. Commons CSV + large rewrite that never compiles (illegal regex escapes; invented `CSVParser(Reader)`,
  `readNext()`); no REVIEW.md or tests.

- **handles-cli-node** `…_1790315045`: `milestone-stalled-60min` (budget 4 intervals); milestones 40/continue,
  35/continue, 40/stalled; final **40%**. Built-in fetch, `request` removed, plain lookup, `--help`, non-zero exit,
  correct Node-free Dockerfile (ENTRYPOINT) — but `--json` crashes (`const jsonOutput` reassigned, lookup.js untouched
  23:42→60 min), count is `data.length` (5, holder total 15), the only test is mocha on `resolve()` (no CLI e2e),
  `node_modules` + mocha lockfile present. rust-toml-cli started 00:07:21.

- **rust-toml-cli** `…_1790320041`: `milestone-stalled-45min`; milestones 20/continue, 15/stalled; final **15%**.
  Cargo on `toml 0.8`, dotted walk via `Value::get`, stderr+exit paths, README (YAML example) — never compiles:
  invented `toml::Value::parse_str` (same member as P20), then `Value::try_from(&content)` (serializes, not parses),
  then `use toml::Value` dropped. **Row p27 queue finished 00:56:02**; heartbeat `a5c06791` deleted after the
  terminal packet. Row p27: shipping 15, cart 30, orders 35, feed 20, handles 40, rust 15 — all six still open.

- **Supervisor takeover 2026-09-24 23:38 PDT** (previous Supervisor stalled; not contacted). Old heartbeat gone;
  single new heartbeat `a5c06791` (*/10). No milestone pending at takeover. handles-cli-node live report 23:40:
  usefulness=35% (post-milestone change: Dockerfile only, still broken — `npm ci` with no lockfile; `--json` still
  parsed as the handle, count still `data.length`). Cart walk seg-71..80: ten fresh readers launched. Feed capture
  `20260924T215334-01a0d6e9` materialized → 49 segments (`~/.cria/walk-findings/2026-09-24/p27-feed/`), waves follow.
  C37/C38/C39 implementation started in isolated worktrees `../cria-shepherd-c3{7,8,9}` (branches `cand-c3x`);
  nothing lands until the row ends and each unit is reviewed.

### Row p27 post-row: walks, reconciliation, candidates (2026-09-25)

- **Walks:** cart 80/80 verified (syntheses `p27-cart/synthesis-{1-27,28-54,55-80}.md`); feed 40/49 verified, 41-49 in
  flight; rust capture `20260925T000732-01a0d764` → 56 segments; handles `20260924T224416-01a0d717` → 81 segments.
- **Partial cross-cell reconciliation** (`~/.cria/walk-findings/2026-09-24/p27-cross-cell-partial.md`, shipping/cart/orders):
  C37 confirmed in 3/3 (shipping CALL0045/46 origin, cart CALL0280, orders CALL0051); invented third-party API 2/3
  (orders is stdlib-only); C39 orders-only. Regression lead (UNVERIFIED, no prior-HEAD walk): C34–C36 turned
  previously-empty one-word judges into answering ones; cart CALL0122 steer-code answers `SUPPORTED` for `go mod tidy`
  while go.mod pins the REFUSED `v0.5.0` — Supervisor opened it: the action names no version, so this is a
  rubric gap (the action implicitly relies on the refused pin), not a clean contradiction. Not yet a candidate.
  Compactor length-with-empty-content: measured on authoritative responses — 1–4 per session, 0 in orders/feed;
  the `*-noreason` retry repeats identical parameters (`reasoning_effort=none` does not stop nemotron reasoning). Low
  prevalence; recorded, not selected.
- **Invented-API origin** (`~/.cria/walk-findings/2026-09-24/invented-api-cross-cell.md`): 4 cells (cart, shipping,
  feed, rust — rust repeats P20's `Value::parse_str` exactly). Origin: no cria-side probe of the resolved
  dependency's real surface, although it sits in the local cache for every cell. **C40** (trigger: RefusalLedger's own
  SUCCEEDED event, not error text — answers P19) is in implementation on `cand-c40`.
- **Reviews:** C37, C38, C39 each REJECTED by independent review; repairs are with the same owners. C37: Codex's
  compaction ask stays in the writer/validator evidence (drop it by position, not by marker), and the no-reasoner
  fail-safe is not implemented. C38: a size-dropped body sticks in the session cache, and the cache leaks across
  roots; the replay was not recorded. C39: the false red becomes "no signal either way", so the timeout is still
  hidden (`clean_gate_output` must abstain per section and state a 124 timeout).
- **Repair re-reviews:** **C37 ACCEPTED** (`54fcf014`: the ask is dropped by position on both paths, verified
  identical to the marker filter across 118 real compaction inbound captures; the no-reasoner guard is implemented;
  5156 passed). **C38 ACCEPTED** (`bbf00bb1`: the cache is keyed by (session, root); a cached body is trusted only
  after this request's tree confirms its size; forget-on-drop; the replay is recorded in
  `walk-findings/2026-09-24/c38-replay/`; the 5 faithful replan rows go 0/5 → 5/5; 5154 passed). **C39** was
  rejected twice more: the per-section abstain made a hard-kind launch failure read as clean, and then the no-plan
  fallback dropped superseded green gates from history (older transports render without a plan). Each repair
  created a new failure class, so a **strategy reset** was ordered: an invariant matrix (a)–(f) through
  `clean_gate_results` across 2+ gates, then the simplest design (persist per-transport candidate facts, or drop
  absent modules at plan time like `program_is_installed`).
- **Walk misreading rejected (Supervisor-verified from raw bodies):** cart "Class E" (0279→0280) and rust
  "Class C" (0142→0143) claimed that tool-confirmed writes were lost across calls. They were not. Each call's
  prompt re-renders the whole history, so a `read_file`/`cargo` result placed BEFORE the newest `write_file` is
  older than the write. In cart, 0280's msg 44 is exactly 0279's response write (same id `hOf15eG…`, same
  md5); in rust, 0143 carries 0142's write at msg 13–14 and the newer lib.rs read after it. There is no state
  loss, and this is not a candidate. Walker prompts now warn about history order.
- **C40 first cut** (`e43d6a57`, trigger = RefusalLedger SUCCEEDED): its own replay shows it never fires on cart
  (the capture has no `go: added` line, only `go: downloading … v0.5.0/v0.6.0`); rust has `Adding toml v0.8.23`.
  Returned to the owner for a coverage table across all 4 cells plus P20, and a structural lockfile/manifest+cache
  trigger if coverage is under 3/4.
- **C40 redesign** (`a2e69556`): measured with cria's own ledger over all 5 sessions, the SUCCEEDED trigger fired
  **0/5**. It was replaced by a structural trigger: a coordinate declared in go.mod, Cargo.lock, Gemfile.lock or
  pom.xml (read through the wsview body seam) AND exactly that version present in the local cache. JVM is covered
  via a zipfile listing plus `javap -public`. Replays now fire for cart, rust and JVM. Disclosed limit: in cart,
  shipping and feed the invented member was written BEFORE the manifest settled, so the note helps the repair phase
  (30+ minutes in each cell), not the first write. Integrated over main: 5207 passed. Under independent review.
- **C39 narrowed** (`44d7d403`, after the strategy reset and one more reject): the acceptance boundary is ONLY "cria's
  own absent lint probe is never the repo's error". The lint floor composes the pyflakes console script under
  `toolpath.resolved`'s name, so an absent tool is dropped at composition. probegate, proberun and prompts are
  byte-identical to base. Naming an empty timeout is a pre-existing base gap; it is split out as a follow-up unit,
  with its matrix tests kept as labelled skips. Under final re-review.
- **Walks complete for all six cells** (shipping 95, cart 80, orders 40, feed 49, handles 81, rust 56 segments; all
  with syntheses). Final reconciliation: `~/.cria/walk-findings/2026-09-24/p27-cross-cell-final.md`.
  - C37's class is confirmed in **6/6** cells (the classifier answered Codex's compaction request as a task).
  - Invented API: 4/6 (orders is stdlib-only; handles misused REST fields instead).
  - Judges certifying against their own quoted evidence: 4/6 (cart 0122, rust 0114 steer-code `SUPPORTED`;
    handles 0103/0104 satisfaction; shipping on-target).
  - Diagnosed-but-not-executed: 5/6. In 6 of 8 clean instances the call ended normally with a different tool call
    and no guard cut (`diagnosed-not-executed.md`). Held: its proposal re-injects the coder's own reasoning, so the
    bar is high and prevalence must be measured first.
  - **Supervisor measurement (authoritative prompt text, all six p27 sessions):** judge `⟦ctx:files⟧` blocks carrying
    "NAMED, NOT SHOWN" (task files whose bytes never reached the judge):

    | cell | blocks with NAMED, NOT SHOWN | blocks with 0 bodies |
    |---|---|---|
    | shipping | 14/15 | — |
    | cart | 3/8 | — |
    | orders | 13/17 | — |
    | feed | 6/6 | — |
    | handles | 76/80 | 12 |
    | rust | 11/12 | — |

    Judges mostly decide without the code; this is C38's family (bodies not persisted across requests). Row p28
    (C38 live) will measure whether it drops; if not, it is the next candidate.
  - Regression hypothesis: REFINED, not confirmed. Judges answering wrongly occurs in cells that held too, so
    C34–C36 is a real cross-cell mechanism but does not by itself predict which cells regressed.
- **Landed between rows** (each with full suite, push, `cria.service` restart, `/health` ok):
  - C37+C38 at `cf98f830` (5167 passed).
  - **C39** at `371d0139` (5182 passed, 9 skipped). The final re-review accepted the product fix; its one blocker was
    a deleted base test. The Supervisor verified `test_timeout_with_no_output_stays_a_bare_no_signal` was restored
    verbatim (function-body diff against `d5294fe9`).
- **C38b** (`1772eab6`): the cross-request body cache is now confirmed by size AND mtime, so a same-length
  unobserved edit (`go get` v1.4.0→v1.5.0) is no longer trusted stale. Under independent review.
- **C40 round 3:** B1 (durable anchor) and B4 (path/option injection) are fixed. Remaining findings:
  - R1: after a same-length version bump the note keeps claiming the old version (needs C38b).
  - R2: the `go doc` filter drops grouped consts and struct fields but is labelled COMPLETE.
  - R3: a JVM read hint up to 70 KB is re-rendered every request.
  - R4: `go doc` can reach the network via GOPRIVATE.
  These are back with the owner.

### Row p28 freeze (2026-09-25)

- New accepted units since p27, each with fails-before/passes-after tests, independent review, full suite:
  - **C37** harness compaction recognized, then hardened;
  - **C38** delivered bodies persist per (session, root);
  - **C38b** that cache is re-verified by size AND mtime against every later survey, replayed writes included;
  - **C39** the absent pyflakes probe is dropped at composition via `toolpath.resolved`;
  - **C40** a declared direct dependency's real exported surface is read from the local cache (go doc -all /
    registry source / gem lib / javap) and anchored durably on a fixed message. Trigger = manifest/lockfile
    coordinate + exact cached version. Bounded at 6 KB per note and 24 KB per request. Path/option-injection safe.
    Went through six review rounds.
- Integrated `e634d866`: 5288 passed, 9 skipped. `cria.service` restarted, `/health` ok.
- Row HEAD = the commit recording this entry. All six cells are open (p27 max 40%). One queue, one note, one
  heartbeat.
- What p28 must measure (from p27 evidence):
  - does C37 remove the raw handoff re-seeding (6/6 cells)?
  - do the judge `NAMED, NOT SHOWN` rates (p27: 14/15, 3/8, 13/17, 6/6, 76/80, 11/12) drop with C38/C38b?
  - does a C40 note reach cart/rust/feed/shipping, and is it acted on?
- Split-out follow-ups (not in p28): naming an empty timeout (C39b); the judge rubric certifying against its own
  quoted evidence (4 cells); diagnosed-but-not-executed (held, prevalence first).

### Row p28 launched

- Row HEAD **`8e362162`**. The service code is identical to `e634d866` for cria/ and suite/; `cria.service` was
  restarted and `/health` is ok.
- Unit `row-p28-8e362162.service` runs `~/.cria/nemotron-l5-row-p28-8e362162.sh`, with the log in
  `~/.cria/nemotron-l5-row-p28-8e362162.log`. The six cells run in order shipping, cart, orders, feed, handles, rust,
  flocked on `suite-gpu.lock`, with note `BATTERY2 L5 nemotron-elastic 8e362162 p28`. Started 07:06:02.
- The guard checks only cria/, suite/run.py and suite/sampling.py against the row HEAD (fixing the p27 first-unit
  defect), so ledger commits are safe.
- One heartbeat: `8bd45449` (*/10).

### Row p28 ABORTED at 27 min — C37 exposed a campaign-wide reasoning-off defect (C41)

- In shipping `…_1790345162` (session `20260925T070628-01a0d8e3`), C37 recognized Codex's compaction (`0078` YES) and
  routed it to the hardened writer.
  - The writer `0079` and its retry `0080` each produced 37,719 completion tokens (the full 49,152 window) with
    **zero content**, 228 s each.
  - Log: `route.compaction_retry` then `route.compaction_no_briefing`. 7.5 active minutes lost, and no briefing.
- **Root cause (Supervisor-verified):** `[backends.local] reasoning_style = "openai"` was written for Bonsai 2.
  - The served Nemotron template (`/props`) consumes `enable_thinking` (4 refs) and never `reasoning_effort`.
  - So every `reasoning = "off"` role and every `*-noreason` retry has been a no-op for the whole campaign. This is
    the p27 "noreason retries repeat identical parameters" and compactor-empty-at-length finding, now hit on every
    compaction because C37 routes them there.
- Queue stopped (`systemctl --user stop row-p28-8e362162`); heartbeat `8bd45449` deleted. Shipping p28 is **invalid
  (aborted)** and is not a result.
- **C41** is in implementation: resolve the backend's think protocol from the served template, and bound the
  writer. A live replay of `0079` is allowed while no row runs. p28 will be re-frozen at a new HEAD once C41 is
  reviewed.
- C39b (naming an empty timeout) is in progress in a separate worktree.

### Row p28 re-freeze (2026-09-25, after the abort)

- **C41 ACCEPTED** (`1c673c91`, merged `6babdb9f`):
  - `Upstream._prep` rewrites a reasoning knob into the convention the served template demonstrably consumes
    (`/props`: Nemotron → `enable_thinking`), and emits `reasoning.convention_autocorrect`.
  - Bonsai-2's real template mentions both conventions, so it is ambiguous and left untouched.
  - The compaction retry carries `SUMMARIZE_MAX_TOKENS`.
  - Live replay of p28's `0079` body: 37,719 tok / 228 s / empty → **421 tok / 4.7 s / 1,677 chars of briefing**.
  - Reasoning-ON bodies are unchanged in effect (the template defaults thinking on).
  - Review follow-ups (non-blocking): the effort-only test fixtures misstate Bonsai-2; the rewrite also runs at
    engagement level 0.
- **C39b ACCEPTED** (`f1566336` + `8dfa98ac`, merged `257d49b0`):
  - Per-transport facts are registered in `ingest_transport` (bounded FIFO), so an exit-124 section is named with
    its command both while newest and after being superseded.
  - After a restart or eviction it falls back to the generic label and the turn is kept.
  - Model-facing sentences are in `cria/prompts/checks_*.txt`.
  - p27 Orders replay: `python3 -m pytest -q` did not finish (timed out). On main the gate turns were dropped.
- Integrated: 5307 passed, 5 skipped; pushed; `cria.service` restarted; `/health` ok.
- p28 carries C37, C38, C38b, C39, C39b, C40, C41. Row HEAD = the commit recording this entry.

### Row p28 launched (re-frozen)

- Row HEAD **`51e82781`** (live code = `257d49b0`). Unit `row-p28-51e82781.service` runs
  `~/.cria/nemotron-l5-row-p28-51e82781.sh`, with the log in `~/.cria/nemotron-l5-row-p28-51e82781.log`.
- Six cells, with note `BATTERY2 L5 nemotron-elastic 51e82781 p28`. Started 08:26:49. One heartbeat (*/10).
- The aborted `8e362162` attempt is void.

### Row p28 live observations

- **C41/C37 are healthy live.** Shipping session `20260925T082715-01a0d92d`:
  - Compactions `0080`/`0137` were recognized (YES).
  - Writer `0081` returned an 826-token briefing with `finish=stop`, versus 37,719 empty tokens before C41.
  - The validator lens answered.
- **C40 gap (Ruby, suite-specific but real):** Gemfile.lock declares countries 0.9.3, but no note was delivered.
  - `_ruby_gem_dir` looks only in `<ws>/vendor/bundle` and `~/.gem`.
  - The suite's cell env puts gems in `~/.cria/suite-installs/<cell>/gem` (GEM_HOME), and in this run the gem was
    not installed there at all.
  - Go (`~/go/pkg/mod`), cargo and Maven caches are shared, so they are unaffected.
  - Candidate direction for after p28: resolve a dependency's location through the HARNESS environment. The
    harness already runs cria's survey script, so a `Gem::Specification`/`go list -m`/`cargo metadata` line in that
    script would report the real path. Reading cria-host guesses is the weaker option.
- **Shipping milestones:** 20/continue at 30 min (the invented `Countries::Country.find_by_alpha2`, gem not
  installed, zone names routed through `zone_for`); 25/continue at 45 min (routing fixed, 11 tests, two wrong
  express expectations, no README table).

### Row p28 — cell results

- **shipping-rates-rb** `…_1790350009`: `milestone-stalled-60min`, 234 calls; milestones 20/continue, 25/continue,
  25/stalled; final **25%** (p27: 15%).
  - Done: the `>=` fix, express rates, name/code routing, 11 tests.
  - Missing or wrong: the invented `Countries::Country.find_by_alpha2`; the gem was never installed in the cell; two
    wrong express expectations; no README table.
  - The last interval was spent on gem searches.

- **cart-billing-go** `…_1790354407`: `milestone-stalled-75min` (budget 5 intervals); milestones 20/continue,
  25/continue, 30/continue, 30/stalled; final **30%** (p27: 30%).
  - C40 fired live: "THE VERSION OF github.com/shopspring/decimal v1.2.0 DECLARED IN go.mod", a COMPLETE root-package
    surface from call 0125 on, listing Round/RoundBank/RoundCash (v1.2.0 has no RoundCeil).
  - The coder converged to `Round(2)` and `.Float64()`, then rewrote back to the invented
    `Quantize(2, decimal.ROUND_UP)`. The note was present and the coder still invented the member: the delivery works,
    but uptake is the next gap to walk.
- **Process defect (Supervisor):** the 75-minute cart milestone froze at 11:07 and was recorded only at 13:50, so the
  queue lost 2 h 43 min. The heartbeat firings in between were queued but not processed.

### Row p28 BLOCKED after cart — the served model was swapped by a separate user session

- At 13:50 the queue aborted before orders: `ABORT before orders-api-py: live-behaviour tree differs from 51e82781`.
- Cause: a separate user session (paseo agent `0289cfe4`, "setup this model", started 13:05 PDT) is setting up
  Defiant-Fable. `:18084` now serves `Qwen3.5-9B-The-Defiant-Fable…MTP-Q5_K_S.gguf`, and `suite/sampling.py` has an
  uncommitted `defiant-fable` entry (plus a `docs/walk-prompt.md` edit).
- Both p28 results (shipping, cart) predate the swap and are valid.
- The Supervisor did NOT swap the model back, and did NOT touch the user's uncommitted files.
- Remaining p28 cells (orders, feed, handles, rust) wait on the user's decision about the GPU/model.
- p28 walks continue meanwhile; they use no GPU.

### Row p28 walks (shipping 64/64, cart 92/92) — while the model swap blocks the queue

- Walkers now run at thinking `low`, at the user's request (launched with a hold prompt, switched to `low`, then
  given the segment).
- **Shipping:**
  - C40 never fired: the gem was never installed, because a Gemfile `source` syntax loop blocked `bundle` for 10+
    segments. That points to a manifest syntax gate (Class A).
  - C37 handoffs were correct but carried no "already refuted" memory.
  - The shipping synthesis claimed a dropped write (Class E). **REJECTED:** a history-order misreading; in 0226 the
    read is msg 4 and the edit is msgs 22–23.
- **Cart:**
  - C40 fired correctly many times, yet the invented `Quantize`/`ROUND_UP` survived about 150 calls. Nothing
    connects `undefined: decimal.X` in `⟦ctx:checks⟧` to the anchored surface. Three independent syntheses agree.
    → **C43** is in implementation.
  - A **false dedup pointer** was Supervisor-verified in 0160. Msg 21 (the `grep "type Cart"` result) reads
    "(duplicate of content shown IN FULL further down …)", but no later message carries that content, which
    violates principle 5. → **C42** is in implementation.
- Classes present in both cells: invented third-party API; diagnosed-but-not-executed; judges contradicting their own
  evidence; a semantic regression (`sub.Mul(pct)`) introduced while chasing compile errors.

### Row p28 resumed (2026-09-26) — the four unrun cells at the same HEAD

- The user stopped Supervisor aad2cc97 on 2026-09-25 to use the GPU for another model, then authorized taking it
  back. A new Supervisor resumed the row.
- Verified before launch:
  - `main` = `origin/main` = `11e10e79`; `git diff 51e82781 11e10e79 -- cria suite/run.py suite/sampling.py` is
    empty, so the live-behaviour code equals the row HEAD. The user's two uncommitted files are untouched.
  - `:18084` served `defiant_fable_9b_mtp_q5ks`. `suite/run.py`'s swap stops only the units in its `SERVICES` map,
    which does not list `llama-defiant-fable`, so the continuation script stops every active non-nemotron
    `llama-*.service` before each cell.
  - `~/.cria/cria.toml` after the runner's own `sampling.apply`: identical to the pre-Defiant-Fable backup except
    `[server] host = "0.0.0.0"` (was `127.0.0.1`), the other session's listen-address change. That does not touch the
    model wire, so it was left alone. Cadence is back to 60/30, and Codex's model/window were re-synced to nemotron
    (49152).
  - After the swap: `/v1/models` = `nemotron_elastic_12b_a2b_q4km`, `/props` n_ctx 49152, cria `/health` ok.
- Unit `row-p28-51e82781-cont.service` runs `~/.cria/nemotron-l5-row-p28-51e82781-cont.sh`, appending to the same
  log. It runs orders, feed, handles and rust with note `BATTERY2 L5 nemotron-elastic 51e82781 p28`, flocked on
  `suite-gpu.lock`, guarded on cria/, suite/run.py and suite/sampling.py (diff and dirty state) against
  `51e82781`. Started 14:18:48 PDT. Orders run id `orders-api-py_nemotron-elastic_codex_pon_1790457529`.
- One heartbeat: `95bfca36` (*/10).
- **orders-api-py** `…_1790457529` (session `20260926T141925-01a0df96`): `milestone-stalled-45min`, 202 calls;
  milestones 35/continue, 25/stalled; final **25%** (p27: 35%).
  - Done: parameterized `get_order` (the seed's only string-formatted lookup); `status` column + in-place migration
    (after an invalid `PRAGMA index_info(orders, 'idx_customer')` crashed `init`, `CREATE INDEX IF NOT EXISTS`).
  - Broken: the customer route totals `row[3]*row[4]` over a 4-column SELECT; `tests/test_integration.py` was written
    early and never runnable (`conn.read()` without `getresponse()`, `http.server` not imported).
  - **Regression, 30→45 min:** `orders/db.py` rewritten whole — `row_factory`, `path=` params and `all_orders` lost,
    `create_order` returns `conn.lastrowid`; the repo's own `tests/test_db.py` now fails (2 failed, verified on a
    scratch copy). Walk: 70 segments at `~/.cria/walk-findings/2026-09-26/p28-orders/`, wave 1 (segs 1–5) running.
- **feed-pipeline-java** `…_1790460639` (session `20260926T151107-01a0dfc5`): `milestone-stalled-30min`, 118
  calls; milestone 15/stalled; final **15%** (p27: 20%).
  - Done: a real `commons-csv:1.10.0` dependency, plus an `Importer` outline (skip-reason counters, currency
    stripping, a fixed thread pool, a compatible `Summary`).
  - It never compiles. It uses invented commons-csv members (`csv.exceptions.CsvValidationException`,
    `new CSVFormat()` + setters, `parseHeader`/`getHeaderCount`/`parseRecord`) and has type errors.
    `REVIEW.md` has no file:line references.
  - C40 FIRED (`writeproxy.dependency_surface_reanchored`, jvm commons-csv), and the invention survived: this is
    the cart class in a second cell.
  - Every compaction validation answered PLAN (C44, 4th cell).
  - No writes after 15:35; the last calls were re-reads and a rumination abort.
  - Walk: 48 segments at `~/.cria/walk-findings/2026-09-26/p28-feed/`.
- **handles-cli-node** `…_1790463051` (session `20260926T155119-01a0dfea`): `milestone-stalled-45min`, 283 calls.
  Milestones 25/continue (recorded by the completion-gate agent at 16:21, not the Supervisor; the verdict was checked
  and is sound) and 20/stalled. Final **20%** (p25: 50%).
  - Done: `request` removed, built-in `fetch`, a Dockerfile that builds.
  - Regression: the 16:27 rewrite of `lookup.js` crashes on every call (`ReferenceError: args is not defined`).
  - `test/lookup.test.js` is API-only; `test/cli.test.js` cannot run.
  - The final `task_complete` claims a README and a test file that do not exist.
  - Walk: `~/.cria/walk-findings/2026-09-26/p28-handles/`.
- **rust-toml-cli** `…_1790466042` (session `20260926T164108-01a0e018`): `milestone-stalled-60min`. Milestones
  35/continue, 55/continue, 25/stalled. Final **25%** (p20: 30%).
  - At 45 min it built and worked end to end (`server.port` → 8080, missing key/file → stderr + exit 1).
  - Three later whole-file rewrites broke it: the tests were deleted twice, and it invented `Value::Number`,
    `as_i64`, `Value::parse`.
  - Walk: 90 segments at `~/.cria/walk-findings/2026-09-26/p28-rust/`.
- **Row p28 queue finished 18:06:35. All finals are recorded.** Heartbeat `95bfca36` deleted.

### Row p28 — complete (HEAD `51e82781`)

| Cell | Run | Final | Previous comparable |
|---|---|---:|---:|
| shipping-rates-rb | `…_1790350009` | 25% | 15% (p27) |
| cart-billing-go | `…_1790354407` | 30% | 30% (p27) |
| orders-api-py | `…_1790457529` | 25% | 35% (p27) |
| feed-pipeline-java | `…_1790460639` | 15% | 20% (p27) |
| handles-cli-node | `…_1790463051` | 20% | 50% (p25) |
| rust-toml-cli | `…_1790466042` | 25% | 30% (p20) |

- All six cells are still open (≤75%).
- Cross-cell classes seen so far (walks are in progress):
  - (1) the post-compaction handoff is empty or appendix-only in every cell (C44);
  - (2) invented third-party members survive or precede the real surface: cart, feed, rust (C43 + a pre-declaration
    gap);
  - (3) whole-file rewrites discard working code: orders, handles, rust;
  - (4) fixes diagnosed but never executed, and false `task_complete` claims: orders, handles.
- **Post-row replays** (unit `post-p28-replays`):
  - **C43 FAILED live.**
    - On 0126 and 0166 the reasoner answered `1: NONE\n2: Quantize, Round`, a verbatim copy of the prompt's own
      example. Its example vocabulary is lifted from the cart capture (#20).
    - Only one package is numbered, so line 2 is dropped and nothing is refuted.
    - The 0202/0219 controls ran away to 68+ `N: NONE` lines.
    - Back to Coder `076fca0c`: fix the question format and prove it live.
  - C44 replay is running.
  - **C44 FAILED live** (103 real calls; `~/.cria/review-scratch/c44/live_replay_results.json`):
    - Part B: **0 of 18** real compactions shipped validated prose (12 appendix-only, 4 empty). The retrospective
      lens rejected 9, the retry was also rejected, and the scope lens rejected 9.
    - Part A: the reworded lens **accepts 7 of 13 plan-bearing drafts**. That is a false-accept regression on a lens
      that self-compaction shares.
    - Controls held.
    - Verdict: rework.
      - C44a keeps only the deterministic truthfulness fixes: the `⟦prose-dropped⟧` marker + unconditional strip,
        the truthful dropped/appendix frames, and the `prompts.render` include order.
      - Revert the lens rewording, the closing ask and the retry.
      - **C45** is the strategy reset on the real outcome, the coder losing its memory at every harness compaction.
        A proposal comes first; nothing is implemented before the Supervisor selects.
  - **C43 round 4** (`5970fb93`, 5341 passed):
    - Example-free, one-package question with a 64-token answer cap. Live: the 0202/0219 controls now answer
      `NONE` in 3 tokens, 0214 is not asked, and PARTIAL gives no text.
    - The target still fails live on 0126/0166. The model names `decimal.Quantize` but repeats it until
      `finish_reason=length`, and cria correctly discards a length-cut answer. Result: silence, never a false claim.
    - The Coder's `repeat_penalty=1.3` override is inert. Supervisor-verified in `reasoning.apply_sampling`:
      `[backends.local] reasoning_style = "openai"` doubles as the SAMPLING dialect, and the openai dialect DROPS
      `top_k`/`min_p`/`repeat_penalty` for every role.
    - **C43 is parked, not accepted.** Four rounds, and the live target is still 0 of 2.
  - **New lead C46 (config/dialect):** `reasoning_style` conflates the reasoning-knob convention with the sampling
    dialect.
    - C41 corrects only the reasoning knob at `_prep`. Every llama.cpp extension sampler is still dropped on the
      local backend.
    - Nemotron's sampling spec sets none of them, so p28 is unaffected.
    - Bonsai-2 declared `top_k = 20` under `reasoning_style = "openai"`. If that was set during the Bonsai-2 runs,
      its `top_k` never reached the server. Check before touching it: the closed Bonsai-2 evidence was measured that
      way.
  - **C42 LANDED** (`a83aeb32`, merge of `cand-c42` `e6395f37`): full suite on main 5317 passed, 5 skipped; pushed;
    `cria.service` restarted; `/health` ok. The row p28 results records were committed as `bd57c685`.
  - **C44a** (`81ec69dc` on `cand-c44`, 5324 passed):
    - The lens, closing-ask and retry changes were reverted to the pre-C44 bytes.
    - It keeps the `⟦prose-dropped⟧` marker + unconditional strip, the truthful frames and the render-order fix.
    - Re-review by `9eaadebe`.
  - **C45 selected** (the proposal is at `~/.cria/review-scratch/c45/proposal.md`):
    - Findings: the task root survives compaction (Codex keeps user turns; the floor pins the task). The SCOPE
      lens rejected 13 of 13 in the live replay.
    - Chosen: a compact, deterministic **action ledger** derived from the messages, one line per real coder call
      with its target and observable outcome, no bodies. It rides the harness-compaction appendix.
    - The proposal's verbatim `_work_log` was rejected: it would re-inflate the compacted history.
    - A live A/B replay is required on the real post-compaction coder bodies (N=5): re-read / redo / progress
      rates.
    - (c2) is a note on whether each fronted harness preserves the task root, with no gate change yet.
    - Coder `c24505f1` on the new `cand-c45`, based on main with C42.
  - **C44a LANDED:** `cand-c44` `3be99624` merged to main.
    - The review's last blocker was that the render include-order change had no test. The Supervisor added one,
      which fails on `3cde247a` because the fragment gets spliced in, and removed three stale retry comments.
    - Accepted by `9eaadebe`. Full suite on main 5329 passed, 5 skipped; pushed; `cria.service` restarted;
      `/health` ok.
  - **C45 action ledger REJECTED on its live A/B** (`6faa595a` on `cand-c45`, not merged):
    - 17 real post-compaction coder turns × N=5 × 2 arms = 170 live calls.
    - Re-reads went 68/85 → 76/85, forward progress 12/85 → 8/85, no-tool turns 5/85 → 1/85. Redone edits: 0
      in both arms.
    - After a compaction the coder legitimately needs current bytes, which a body-less ledger cannot give, so
      re-reading is not the harm the walks implied.
    - Report: `~/.cria/review-scratch/c45/ledger_replay_report.md`.
    - (c2) note: cria's suite fronts only Codex, which keeps user turns, and the floor pins the task, so the scope
      lens's premise does not hold on this harness. No gate change without a wider harness census.

### Row p29 freeze (2026-09-26)

- **New accepted units since p28** (each with fails-before/passes-after tests, an independent review and the full
  suite):
  - **C42** (`a83aeb32`): the dedup fold keys a tool result on its owning command, so there are no cross-command
    false pointers.
  - **C44a** (`b06b2777`): truthful post-compaction frames when prose was dropped (the appendix is presented as
    re-derived ground truth, never "the handoff below"), the `⟦prose-dropped⟧` marker stripped unconditionally
    inbound and at `_prep`, and `prompts.render` expanding includes before caller values.
- Not carried: C43 (parked, live target 0/2), C44's lens/closing-ask/retry (live 0/18, lens false-accepts), and
  C45 (live negative).
- Main at freeze: full suite 5329 passed, 5 skipped. `cria.service` restarted, `/health` ok.
- Row HEAD = the commit recording this entry. All six cells are open (p28 max 30%). One queue, one note, one
  heartbeat.
- What p29 must measure:
  - post-compaction frames: are they truthful, and are they acted on correctly?
  - does a dedup pointer ever point across commands?
  - baseline rates for the p28 classes, to pick the next candidate: whole-file rewrites of working code (orders,
    handles, rust); invented API with fetch tools available (feed, handles, rust); diagnosed-not-executed.
- Next candidate in design during p29, with no GPU until the row ends: **C47**, regression-only protection against
  a whole-file rewrite that discards working, checked code (principle 2).
  - Process note: the Supervisor's C43 diagnostic call ran while the C44 replay was active. The server has one slot
    (`total_slots` 1), so requests queued rather than interleaved, and both runs are temperature 0.

### Candidate C44 (row p28, cross-cell) — the compaction validator rejects every briefing, so the coder's memory is emptied

- **Chain (Supervisor-verified, orders session `20260926T141925-01a0df96`):**
  - `0047`: the compactor writes an accurate retrospective briefing (what works / what is broken / what I was doing
    last). It contains no imperative.
  - `0048`: the RETROSPECTIVE lens (thinking off, "If uncertain, answer PLAN") answers `PLAN`.
  - `server._harden_compaction_reply` then sets `text = ""`, so Codex stores only the inventory+checks appendix.
  - From `0049` on, the coder sees `⟦ctx:continuation⟧ … Handoff account (unverified):` followed by nothing.
  - The coder re-reads files it had already read (walk seg-09/10; chunk028 L560–568). The frame's claim "the
    handoff below" is itself false (#5b).
- **Prevalence** (`context.compaction_validation`, after C41 went live): **18 of 18** validations in row p28 were
  rejected with `PLAN`.
  - Shipping: 4 harness compactions. Cart: 4 harness + 1 self. Orders: 7 harness + 1 self.
  - The only acceptance was the C41 replay.
  - Before C41 the same judge answered `""`, which was also a rejection.
  - So C37, which routes every harness compaction here, has been emptying the coder's memory in every p28 cell.
    This is a direct C37/C41 interaction the p28 freeze did not measure.
- **Correction after a full read of all 18 candidates** (Coder `c24505f1`; the Supervisor spot-checked orders 0047/0048
  and feed 0049):
  - **13 of 18 rejections are correct.** The writer ended an otherwise accurate retrospective with a forward "next
    step" sentence, although line 2 of its prompt forbids that. Example, feed 0049: "The next step is to complete
    the CSV-parsing fix, enable workers, …".
  - **5 of 18 are false rejects:** cart 0274; orders 0048, 0110, 0130 and 0143.
  - The consequence is unchanged: all 18 left the coder an empty memory.
  - First candidate (`cand-c44`, 5324 passed):
    - It sharpens the RETROSPECTIVE lens prompt, which addresses the 5 false rejects.
    - It adds a truthful empty-handoff reframe (fails before on the 0049 shape).
  - That is not enough. The owner is upstream (A): the writer emits forward sentences.
  - Follow-up sent to the same Coder: find why the writer does this on the harness path (for example, the harness's
    own "next steps" instruction in the transcript), and fix at the writer, or add one bounded re-validated writer
    retry.
  - The replay must measure the end-to-end outcome: how many of the 18 real requests yield a non-empty validated
    handoff, with `ruby_eu` still blocked.
- **Assigned:** Coder `c24505f1` in its own worktree `cand-c44`.
- **C44 round 2** (`cand-c44`, 5328 passed):
  - **Cause A:** `_compaction_body` already strips Codex's own compaction instruction. The forward sentence follows
    the LAST thing the writer reads, `compact_closing_ask.txt`, which ends on "what you were doing last" with
    nothing closing it. That ask now forecloses a forward clause.
  - **Safety net for C:** `server._retry_dropped_plan_briefing` makes ONE bounded writer retry on a rejected
    non-empty draft, only when a validator role exists. The writer re-selects from its own draft (cria edits no
    sentence), the result is re-validated by all three lenses, and it falls back to appendix-only if still rejected.
    New prompt `compaction_retry_retrospective.txt`.
  - **Tests:** 4 scripted end-to-end `_harden_compaction_reply` tests, which fail before the fix.
  - **Replay:** PART B re-runs the 18 real writer requests. Its acceptance was corrected: those 13 plan cases are the
    target (a non-empty validated handoff), shipped handoffs are re-checked, and `ruby_eu` must never ship.
- **C44 review (`9eaadebe`) REJECTED `211169a7`:**
  - B1: the truthful frame fires only on a blank summary. The common shape is prose dropped with the appendix kept
    (shipping 0084/0141, cart 0079, orders 0087/0191, feed 0052/0088). There the frame still says "the handoff
    below is an ungrounded account" and labels re-derived ground truth as ungrounded.
  - B2: the lens examples were lifted from battery cells, including the `ruby_eu` control (#20; this contaminates
    the replay). The final rule classes naming a file as PLAN.
  - B3: the retry fires on any rejection (fidelity, scope, empty) but tells the writer it "contained a next step".
  - B4: the replay is not the production path. It gives the validator no evidence, re-implements the pipeline, and
    runs at temperature 0, so N=3 is one sample.
  - Also, only 1 of the 4 retry tests fails before the fix.
  - All findings went back to Coder `c24505f1`, with the reviewer's replay acceptance: real path; per-case lens,
    retry and shipped text; untainted `ruby_eu` + synthetic controls; a Bonsai-2 arm.
- **C44 re-review of `1b7c2f1e`:**
  - B2 and B3 are accepted. The `prompts.render` reorder is byte-identical across all 246 prompts (1,362 renders).
  - B1 is fixed for Codex at level ≥3 only.
  - Not accepted on two blockers:
    - R1: the new dropped-prose marker `⟦cria:prose-dropped⟧` reaches the model at level <3 (`<<<LOCAL_COMPACT>>>`
      path) and when a harness stores the reply as an assistant message (#17). It must be stripped unconditionally
      and at the wire.
    - R2: replay flaws. The controls count any shipped text as a leak; Part B re-implements the harden decision;
      the retry evidence is not compaction-time; Part C is not a real Bonsai-2 arm under Nemotron.
  - Back to Coder `c24505f1`.
- **C44 ACCEPTED on review** (`4d47ea48` on `cand-c44`; full suite 5340 passed):
  - R1 is closed. The marker, now `⟦prose-dropped⟧`, is stripped unconditionally in `_strip_and_reframe_inbound`
    and at `Upstream._prep`. 4,714 captured bodies are byte-identical through `_prep` when no marker is present.
  - The replay script (`~/.cria/review-scratch/c44/live_replay.py`) is accepted after three Part B fixes: the real
    task is restored; `prose_shipped` comes from the validation events; the checks are framed once. Verified by an
    offline fake-provider dry run over all 18 cases.
  - **Still required before it goes live:** the real-model replay after the row. It must report how many of the 18
    real compactions ship a validated handoff, show that neither control ships its invented API, and include a
    separate Bonsai-2 Part C after a model swap.
  - Hand-label the rejected candidates, using the p27 `ruby_eu` plan-bearing reply as the must-reject control.
  - Prove the upstream cause (lens design, evidence framing, reasoning budget, or writer prompt), and decide the
    rejection behaviour so it is not whole-memory loss.
  - Fix the empty-handoff frame.
  - Write capture-shaped tests and a real-model replay of all 16 captured in-row validator bodies. The replay runs
    after the row.

### C42 / C43 independent reviews (2026-09-26, during p28)
cand-p29-int re-merged on main as `c5368315`: 5330 passed, 5 skipped. Both reviews ran in isolated worktrees and
both REJECTED. The Supervisor confirmed the key findings in code. Repros are in `~/.cria/review-scratch/c4{2,3}/`.

- **C42 (`240bee5e`):**
  - The command-aware fold (mechanism b) is accepted.
  - The wire verify/restore (mechanism a) is rejected:
    - It compares raw bytes while the fold keys on `volatile_key`, so about 40% of correct noise-only folds are
      undone.
    - It restores after `contextfloor.fit`, so the body can exceed the window and the refit raises
      `ContextRefitNoChange`.
    - It restores after `merge_for_alternation`, which deletes another message's text.
    - Its cited incident does not hold: in 0105 msg 59 the promised copy exists at msg 65, and 0 of 43 pointers in
      that session are broken.
  - Repair: measure (a)'s prevalence, and drop (a) unless real incidents are found.
- **C43 (`fce1194b`):**
  - The structural trigger is accepted.
  - Rejected for false facts:
    - B1: it asserts absence over PARTIAL surfaces, which say themselves not to assume a member is fake.
    - B2: the claimed name is never checked to occur in the findings (`NONE.` would render as a refuted member).
    - B3: the pointer claims an anchor is "earlier" when the body does not carry it (0214/0217/0218).
    - B4: the output is not byte-stable across renders with several dependencies.
    - B5: the tests fail before only by AttributeError, and none goes through `_frame_for_item`.
  - The real-model replay spec is recorded for after the row.
- Repairs are with two Coders, each confined to its candidate worktree: C42 `b184c06d`, C43 `076fca0c`.
- **C42 ACCEPTED on re-review** (`e6395f37` on `cand-c42`):
  - Mechanism (a) was removed entirely. The prevalence scan covered 167 sessions and 13,681 bodies, keyed on the
    fold's own key: 7,861 promises held and 0 broke between fold and wire. The reviewer's spot-check on
    20260922T001020 agrees (31 held, 0 broken).
  - `bodykeys`, `contextfloor` and `upstream` are byte-identical to the merge-base. Only the command-aware fold in
    `dedup.py` remains.
  - Fails before: `test_two_different_empty_searches_are_not_folded` gives `1 != 0` on `1dd90a44`. The new `_prep`
    end-to-end same-command test fails at `240bee5e`.
  - Full suite: 5311 passed, 5 skipped.
  - It lands after row p28 ends.
- **C43** is back with its Coder: its fails-before evidence is still an AttributeError, not a behavioural failure.
- **C43 re-review (`03c5afec`):**
  - B1, B2, B4 and B5 are closed.
  - The fails-before is now real: 14 tests fail against the rejected `fce1194b`, and 15 on base.
  - Not accepted, on two blockers:
    - R1: anchor presence and position are decided on `clean_gate_results`' INPUT list, which drops no-signal gate
      results and later transport pages. So "anchored earlier" can still point at an anchor the sent body lacks.
      547 of 3,530 inbound bodies have that newest-message shape.
    - R2: `live_replay.py`'s coder A/B compared identical bodies, so the probe was never invoked. It defaulted to
      the main tree and re-implemented the probe.
  - Back to Coder `076fca0c`, which will also restore a real per-session ask bound and add a drive-level `sess_key`
    test.
- **C43 ACCEPTED on second re-review** (`eb51614d` on `cand-c43`):
  - R1 is closed. The append is a post-pass over the list that is actually sent; the repro3 no-signal and
    transport cases are now silent.
  - The post-pass was run over all 3,759 captured inbound bodies with a recording probe: 885 firings, 0 mistargets.
  - R2 is closed. `live_replay.py` calls the real probe from the candidate tree. The offline stub gives
    0126/0166 → `Quantize`, 0202/0219 → none, 0214 → not asked. Variant B differs in exactly one message.
  - A real per-session ask bound is in place, and a drive-level `sess_key` test exists. Full suite: 5338 passed.
  - **Still required before it goes live:** the real-model replay (`~/.cria/review-scratch/c43/live_replay.py`)
    after the row ends. C43 is a new assist.
- `cand-p29-int` re-merged main + `cand-c42` + `cand-c43` as `9c67f497`; its full suite is running.

### Candidate C37 (row p27 cross-cell class) — harness compaction is never recognized, so its hardening never runs

- **Walk evidence (p27 shipping seg-03, verified by the Supervisor):** CALL0046 (23:49:26 UTC) is Codex's compaction
  request ("You are performing a CONTEXT CHECKPOINT COMPACTION. Create a handoff summary…"). cria classified it as an
  ordinary coding task (`decision engagement=task reason='create handoff summary'`) and proxied it to the coder model;
  the reply invented the `ruby_eu` gem, a `RubyEU::EU.member?` API and a fake GitHub citation, as a forward plan.
  Codex stored it as the session's memory and CALL0048's `⟦ctx:continuation⟧` carried "Chose the `ruby_eu` gem for EU
  detection" — the origin of the p27 shipping `ruby_eu` / two-argument `require` / `RubyEU` chain.
- **Owner:** `server._is_compaction_request` recognizes a harness compaction only by the operator-wired
  `<<<LOCAL_COMPACT>>>` marker. `~/.cria/codex-home/config.toml` sets no `compact_prompt`, so **every** harness
  compaction in the campaign (206 proxy + 36 classifier calls across 29 sessions, 2026-09-22..25, all six cells) used
  Codex's default prompt and bypassed `_harden_compaction_reply` entirely: no validator (C34 made it able to answer),
  no fetch/inventory/check appendices, no empty-briefing retry, no compactor sampling.
- **Candidate direction (principles #8/#18):** detect harness-agnostically, not by Codex metadata or prompt wording.
  Deterministic trigger: the request's tool menu is empty (Codex compaction sends `tools: []`) → one focused closed
  judgment ("is the latest user turn a request to summarize this conversation for continuation?") → route through
  the existing `_harden_compaction_reply`; the marker path stays. No keyword list.
- **Constraint:** implementation must not touch the live worktree while row p27 runs (the queue aborts if `cria/` is
  dirty) — needs an isolated checkout or waits for the row to end.

### Candidate C38 (row p27) — surveyed manifest bodies are lost between requests, so declared test tasks flap out of the gate

- **Evidence** (diagnosis `~/.cria/walk-findings/2026-09-24/c38-rake-test-diagnosis.md`, read-only, decoded wire bytes;
  walk seg-21/25/27): in p27 shipping the gate script's survey `WANT` list asked for `Rakefile`, and the harness
  returned its exact bytes (decoded from transport spool `.cria-gate-b4d52e71…`), yet `build_ruby` saw no body:
  `server._bind_workspace_view` builds a fresh empty `wsview.View` per request (`server.py:1000`), and
  `replan_after_survey` (`probegate.py:2137`) fires only when the tree had never been surveyed. `rake test` was
  composed on ~2 of ~12 gates; the rest ran `ruby -c` only and told the coder "no command to run them was found in
  this project" (false: the Rakefile declares `Rake::TestTask`). Ruby sessions in window: 01a0d306 2/6 gates,
  01a0d38c 0/4, 01a0d5d1 ~2/12. Every builder that reads a manifest body via `read_text` is structurally exposed
  (JS/JVM/Python/Go/Rust by code reading; capture confirmation still needed).
- **Candidate direction:** the owner is the per-session body knowledge in `wsview`/`probegate`: a body the harness
  delivered must reach the next plan (session-scoped, generation-checked so an edited manifest is never read stale),
  or a plan that missed a wanted body must replan when it arrives. Additionally (#11b) the absence sentence must not
  render when a declared manifest's body is unknown for this plan.

### Candidate C39 (row p27, Orders walk) — cria's own absent lint probe is reported as the repo's error

- **Evidence (Supervisor-verified, p27 orders chunk107):** the gate call (represented to the coder as
  `python3 -m pytest -q`, yield 300000) returns `⟦ctx:checks⟧ the repo's own checks report these error-class problems
  … /usr/bin/python3: No module named pyflakes` — the ONLY finding — while the real pytest hang (312 s, still running)
  appears outside the checks block. `lint_floor_candidates` composes `python3 -m pyflakes` (`composed_by_cria=True`)
  and documents "an absent tool abstains ('failed to launch'), never blocks", but the gate interpreter treats a
  missing Python module (exit 1) as a failed check; only `linterprobe.escalate_pyflakes` honors absence.
- **Prevalence:** coder prompts carrying that false red: 01a0c862 2, 01a0d1e8 84 (C26 Orders), 01a0d2c3 69 (P18
  Orders), 01a0d4fa 16 (P24 Orders), 01a0d6b9 80 (p27 Orders) — every Orders run with the integration-test hang.
- **Candidate direction:** make cria's own composed probes report tool absence through the existing launch-failure
  path (e.g. the composed command pre-checks the module and exits 127 when absent), no output keyword parsing; the
  hang's real timed-out output then stands alone in the checks block. Language-agnostic for any cria-composed probe.

### Cross-cell lead — invented third-party API members (not yet a candidate)

Rust P20 (`toml` `Value::parse_str`, `toml::Error::Missing`), Feed p22 live (`org.apache.commons.csv.exceptions`,
`CSVParser(BufferedReader)`, `readHeader`), Cart C19 (`decimal.ROUND_HALF_UP`, `ToFloat64`) and Shipping P21
(`Country.new(code).in_eu?`) all fail on members the dependency does not provide, while the dependency itself
resolves. C31 removes one cria-authored reason not to read the real documentation; whether a further
language-neutral grounding step is needed is to be decided from post-C31 evidence, not assumed.

Next bounded unit: the latest Cart C13 capture is materialized losslessly at `~/.cria/walk-findings/2026-09-23/cart-c13/` as 29 compaction-safe segments (6,281,741 bytes / 388 calls). All 29 durable findings now exist and their cited chain was reconciled against the materialized capture; no battery run is in flight, so no heartbeat is required.

### Candidate C14 — planner rewrite-frame false workspace fact (pending independent review)

- **Causal record:** C13 `chunk025.txt` CALL0101 directly shows the planner receiving (a) the complete workspace fact `cart.go`, `cart_test.go`, `go.mod` only and (b) the raw handoff stating a nonexistent `cartsvc/cart.go` plus unperformed work. The body opens with the categorical statement that the summarized completed work **ALREADY EXISTS**; CALL0102 follows its stale pathname and gets `does not exist`, while CALL0103 confirms root `cart.go`. The same contradiction recurs through the complete walk; `chunk104.txt` CALL0337 shows the proxy generating false completion claims after an authoritative three-file `ls`, and CALL0338 re-delivers them to the planner. This is not a claim about the coder: the model-facing affirmative fact is created deterministically at `Loop._drive_locked` rewrite → `Planner._gather_and_plan(rewrite_summary=...)` → `prompts.render("plan_rewritten")`; `cria/prompts/plan_rewritten.txt` line 1 contains the exact false assertion (introduced in `5996d0c`).
- **Smallest candidate:** replace only that post-harness-compaction planner frame's affirmative completion/existence and no-redo assertions with the existing `compaction_reframe.txt` truth contract: summary is attempted/unverified, inspect current workspace/checks, and act from those facts. Keep `plan_continuation.txt` for actual prior completed work unchanged. The candidate is model-, language-, and harness-neutral because it keys only on the planner rewrite boundary and truth provenance, not Cart/Go/Codex terms. It is additive/regression-only: it removes false authority without choosing code/actions.
- **Required proof before landing:** exact C13 summary rendered through the real planner frame must fail before (contains the false workspace assertion) and pass after (contains no affirmative completion/existence claim while retaining raw summary/task); regressions must preserve genuine prior-work continuation and rewritten root selection. Independent review approved this bounded correction and warned not to copy `compaction_reframe.txt`'s own existence assertion. C14 landed as `7434a753` (`Ground planner rewrites in workspace evidence`), pushed and live-restarted healthy; its focused replay suite passed `21 passed, 8 subtests`. C15 below removed the unrelated mutable-capture test failure; supervisor acceptance `python -m pytest` passed **4998 passed, 5 skipped**. The exact C13 rewrite replay and genuine-prior-work regression remain passing. C14 is now eligible for one serialized Cart rerun. Bonsai 2 risk: shared planner compaction framing; live non-regression must be assessed before campaign closure.

### Candidate C15 — mutable live-capture measurement test (accepted)

- **Root cause / scope:** C14 full pytest exposed a pre-existing red in `tests/test_planner_cut_off.py::MeasurementTests.test_the_5_of_8_split_is_what_the_captures_still_say`. The test (introduced by `57f6380d`) scanned mutable `~/.cria/calls` and asserted a historical corpus split. Its behavioral cutoff invariants already lived in deterministic tests (complete trailing arguments survive, malformed trailing argument is dropped, surviving real result reaches the next planner turn).
- **Accepted repair:** `f516387b` first replaced that census with committed capture-shaped forms. Independent review correctly rejected it because its valid envelope was a `finish_reason=tool_calls` retry, not itself a cutoff. Repair `2f199d12` makes the test boundary explicit: captured fragment and valid terminal envelopes provide the raw argument forms; the fixture applies `finish_reason="length"` to both to exercise the actual cutoff gate, with no claim that the valid retry was an observed complete cutoff. The test asserts classification comes from raw terminal arguments, not finish reason. This is test-only and does not alter product behavior or create runtime model/task logic.
- **Evidence / review:** focused `python -m pytest tests/test_planner_cut_off.py` passed **12 passed**; canonical `python -m pytest` passed **4998 passed, 5 skipped**. The same independent Reviewer re-reviewed `2f199d12` and accepted, finding the fixture’s provenance now truthful and the gated classification invariant covered. Both commits are pushed to `main`; the unrelated report dirty state was preserved through the repair.

### C14 Cart terminal rerun — strategy reset required

- Comparable run `cart-billing-go_nemotron-elastic_codex_pon_1790190648` ran under exact note `BATTERY2 L5 nemotron-elastic 0dbf1441 p8`, planner on/L5, and ended `milestone-stalled-30min` after **662 calls**. The canonical 30-minute verdict was **5%, stalled**; final independent packet `/home/jesse/.cria/suite/_usefulness_evidence/cart-billing-go_nemotron-elastic_codex_pon_1790190648.txt` records the same terminal usefulness.
- Archive evidence: only untracked `discounts.json` and research material were added; `cart.go`, `cart_test.go`, and `go.mod` retained seed behavior. The requested decimal integration, rounding repair/regression test, fallback consumption, and stderr logging were not delivered. `go test ./...` passed against the unchanged implementation. The C14 heartbeat `a2fab6b6` remains only until this terminal report is posted, then must be removed.
- **Rerun authorization:** none. C13 (25%) → C14 (5%) is a changed/worsened outcome, not convergence. Select and prove a new upstream deterministic transition from a complete decisive capture before any further GPU run.

### Candidate C19 — preserve unstamped checker tool voice

- Complete C14 walk (82 lossless segments) rejected C16 (downstream critic provenance already suppressed) and C17 (unrecognized compaction summary cannot be faithfully repaired). C18 traced the independent earliest repeat-loop producer: `probegate.clean_gate_results` replaced C14 CALL0028/CALL0392’s non-stamped proxy checker results with synthetic repeat prose, destroying the real tool output and inducing identical rechecks.
- `705301ac` returns non-stamped results after existing structural cleanup, preserving every real checker line; provenance-stamped C6 cleaning remains `linked_only=True`. C14-shaped fails-before/passes-after replay, stamped-gate, and ordinary marker-shaped regressions landed. Focused checks passed; full `python -m pytest` **5000 passed, 5 skipped**. Independent re-review accepted (108 focused tests), commit pushed, `cria.service` restarted and `/health` OK.

### P21 Shipping terminal rerun — missing country dependency

- Comparable run `shipping-rates-rb_nemotron-elastic_codex_pon_1790255585` under `BATTERY2 L5 nemotron-elastic a9087c45 p21` exited after **117 calls** at **35%**. It added rate/README/test work, but loading the delivered code failed with `cannot load such file -- countries`. Heartbeat `57f6ab86` was retired.
- No generic Shipping rerun is authorized; walk the raw-inbound capture to verify whether compaction provenance engaged and classify this load failure.

### P20 Rust terminal rerun — crate API compilation stall

- Comparable run `rust-toml-cli_nemotron-elastic_codex_pon_1790252780` under `BATTERY2 L5 nemotron-elastic c435329c p20` ended `milestone-stalled-30min` after **163 calls** at **35%**. A Rust project and tests were created, but repeated nonexistent TOML crate APIs left `cargo test` uncompilable. Heartbeat `031bbea6` was retired.
- Generic reruns are paused pending a strategy-reset assist at the capture-proven compaction boundary.

### P19 Shipping terminal rerun — dependency/API delivery stall

- Comparable run `shipping-rates-rb_nemotron-elastic_codex_pon_1790246809` under `BATTERY2 L5 nemotron-elastic ef1fe654 p19` ended `milestone-stalled-60min` after **805 calls** at **30%**. It made threshold/rate-table/partial express work, but Bundler could not resolve locked gems and the delivered express API/country mapping remained unvalidated.
- The live inbound capture seam is available for this new terminal capture; walk this capture before another Shipping rerun.

### P18 Orders terminal rerun — integration-test hang

- Comparable run `orders-api-py_nemotron-elastic_codex_pon_1790242392` ended `milestone-stalled-30min` after **142 calls** at **50%**. It added application/database work and an integration test, but `python -m pytest -q` hung after two tests. Heartbeat `e6324bfc` was retired.
- No generic Orders retry is authorized; walk this new terminal capture if Orders is selected again.

### P18 Cart terminal rerun — no engagement

- Comparable run `cart-billing-go_nemotron-elastic_codex_pon_1790238295` at `ad8a8c9b` ended `milestone-stalled-30min` after **814 calls** at **0%**. The workspace remained clean; baseline `go test ./...` passed, but no deliverable work was made. Heartbeat `ed6732f3` was retired.
- **No generic Cart retry is authorized.** Canonically walk session `20260924T012515-01a0d284` for the no-engagement transition.

### C27 Handles terminal rerun — strategy reset

- Comparable run `handles-cli-node_nemotron-elastic_codex_pon_1790231549` under note `BATTERY2 L5 nemotron-elastic 3cf2697a p17` ended `milestone-stalled-60min` after **372 calls** at **70%**. It reached 80% with a passing CLI-invoking test, then regressed when a later real-API test imported removed `node-fetch`; `npm test` became red. Heartbeat `184e16fb` was retired.
- **No generic Handles rerun is authorized.** Canonically walk the later node-fetch regression boundary before any candidate.

### C26 Orders terminal rerun — strategy reset

- Comparable run `orders-api-py_nemotron-elastic_codex_pon_1790228055` under note `BATTERY2 L5 nemotron-elastic 0df1c4dd p16` ended `milestone-stalled-30min` after **204 calls** at **40%**. It added route/migration/integration artifacts, but the integration test hung pytest after two tests; heartbeat `2f1c4568` was retired.
- **No immediate Orders rerun is authorized.** Cross-cell p9–p16 evidence must establish whether recent barriers fire, are reached, or no longer match the failure class.

### C25 Handles terminal rerun — strategy reset

- Comparable run `handles-cli-node_nemotron-elastic_codex_pon_1790223605` under note `BATTERY2 L5 nemotron-elastic bf8fe41d p15` exited after **64 calls** with **0%** and no workspace changes; terminal heartbeat `1984a886` was retired.
- **No Handles rerun is authorized.** C25 repeats C22’s no-coder shape. Canonically walk the capture to establish whether recent plan READY admission/E2E source binding suppressed plan admission before selecting a correction.

### C24 Handles terminal rerun — strategy reset

- Comparable run `handles-cli-node_nemotron-elastic_codex_pon_1790217729` under note `BATTERY2 L5 nemotron-elastic 69d8e894 p14` ended `milestone-stalled-45min` after **490 calls** at **70%**. Its CLI, Dockerfile, dependency removal, and runner exist, but the passing test directly calls the API rather than invoking `lookup.js`; heartbeat `b9c1e5f7` was retired after terminal reporting.
- **No further generic Handles rerun is authorized.** C20–C24 remain below 75% in the test-delivery family. Walk C24 to the exact CLI-E2E acceptance divergence before selecting a different intervention.

### C24 completion participation extension (no rerun)

- C24's complete finding (`~/.cria/walk-findings/2026-09-24/c24-cli-e2e-reset.md`) traces the false acceptance to `loop._test_participation_blocks_completion`: CALL0383 wrote an API-only `tests/lookup.test.js`; CALL0384's `npm test` passed it; CALL0465 accepted satisfaction. The selected test reached the upstream API but not `lookup.js`, despite the original task and plan requiring a real-request CLI end-to-end test.
- Review found the initial extension could inspect a named-but-unbound, unavailable, or stale cached workspace file. The repaired owner-local path stores an exact test-source mapping on the selected declared runner candidate, forces that source into the same gate survey, and preserves only bytes whose survey generation is the PROVEN gate event's generation. Once it proves a test ran, a focused semantic judgment first decides whether the task requires a CLI/tool end-to-end test. Only a mapped source with available event bytes reaches the read-only completion judge, which must return `PROVEN` only if that executed test invokes the requested CLI/tool and checks output or exit status. Missing mapping/bytes, `UNVERIFIED`, `UNDECIDABLE`, or an unreadable answer keeps the existing corrective completion route; `NOT_REQUIRED` preserves ordinary proven tests. No JavaScript process-launch keyword rule and no plan-coverage change were added.
- Capture-shaped C24 tests place the passed `npm test` event beside the direct API-only `tests/lookup.test.cjs` and prove positive satisfaction is held; paired CLI invocation/output-status and non-E2E cases preserve approval. The production-path replay drives the declared runner through `plan_gate`, asserts its mapped test path is emitted in the generated survey command, feeds the transport-wrapped returned survey and probe sections to `interpret_gate`, then binds only that survey generation's bytes to the gate event; a prior-cache/no-new-blob replay through that same path remains unverified. Focused completion/participation and prompt cohorts passed; repaired full `python -m pytest` passed **5017 passed, 5 skipped**. No battery rerun is authorized by this unit.

### C23 Handles terminal rerun — strategy reset

- Comparable run `handles-cli-node_nemotron-elastic_codex_pon_1790216479` under note `BATTERY2 L5 nemotron-elastic 3206b06b p13` exited after **52 calls** at **45%**. It produced CLI/Dockerfile/test artifacts but no `npm test` script; terminal heartbeat `a1f25c47` was retired.
- **No C24 Handles rerun is authorized.** Canonically walk C23 first to classify this stall against the C20–C22 runner-readiness family; if shared, use a different intervention class.

### C23 completion barrier candidate (no rerun)

- Canonical C23 segments 006–007 establish a distinct terminal boundary: `test/lookup.test.js` directly fetches the API, no runner command is composed, and the gate records `test=unknown` / no tests executed, but CALL0043 returns `satisfied:true`. This is not the C20–C22 planner/readiness path; existing runner discovery already disclosed the missing command.
- The owner-local repair is `loop.judge_satisfaction`: on a positive verdict whose authoritative `ParticipationReport` does not prove test participation, it asks one focused semantic question whether the original task requires executed tests. `REQUIRED` or an unreadable answer holds completion; `NOT_REQUIRED` preserves a non-test task; an actually proven test run takes no new branch. It reads the structured gate event, never task keywords, test paths, source text, runner names, or completion prose.
- Capture-shaped candidate tests cover C23’s direct-HTTP artifact plus syntax-only/unknown gate, a non-test task with the same event, and a runner tally proving execution. Fails-before: C23 satisfaction accepted and the non-test path never asked the requirement question (2 failed, 1 passed). Passes-after: focused completion/participation cohort `428 passed`; full `python -m pytest` `5012 passed, 5 skipped`. No rerun was launched.

### C22 Handles terminal rerun — strategy reset

- Comparable run `handles-cli-node_nemotron-elastic_codex_pon_1790213771` under note `BATTERY2 L5 nemotron-elastic 027e9de2 p12` exited after **91 calls** with **0%** usefulness and no workspace changes. Heartbeat `ed79d166` was retired after its terminal packet.
- **No Handles rerun is authorized.** C20 stall → C21 50% stall → C22 no-change regression requires a cross-capture reset: compare C22’s predicate/coding path to C20/C21 before choosing any successor.
- **C22 readiness boundary repair (no rerun):** the bounded comparison found that CALL0040's exact `TEST_EXECUTION_PATH_READY` was converted to `MISSING` by a lexical post-judge detector because CALL0039 quoted `node ./tests/lookup.test.js` with single quotes rather than backticks. That conversion exhausted the existing test-execution handback and caused `plan.rejected_exhausted` then the proxy CALL0041; no `PlanSession` or `coder-s1` body existed. The repair removes only that post-READY lexical veto: exact READY now admits, while MISSING, NOT_APPLICABLE, malformed, and unavailable verdict behavior remains typed and fail-closed. The capture-shaped replay supplies C22's manifest, five submitted steps, and READY response; it proves a five-item plan, stored `PlanSession`, and one `coder-s1` body. Its paired MISSING replay proves no plan session or coder body. Review found the initial repair still admitted a parsed `NOT_APPLICABLE` despite that same manifest fact. The follow-up closes that token only on the manifest-present readiness route; the no-manifest path still does not ask this judge. Its paired loop replay proves no plan session or coder body for parsed `NOT_APPLICABLE`. `python -m pytest` passed **5009 passed, 5 skipped** before the follow-up validation. This is a deterministic admission repair, not authorization for a GPU rerun.

### C21 Handles terminal rerun — comparison required

- Comparable run `handles-cli-node_nemotron-elastic_codex_pon_1790210315` under note `BATTERY2 L5 nemotron-elastic cdf0e2f2 p11` ended `milestone-stalled-30min` after **290 calls**, at **50%**. It did add a test script and test artifact, but `npm test` crashed before assertions when the test read nonexistent `execFileSync` result fields. Heartbeat `82a81a26` was removed after terminal reporting.
- **No immediate C21 walk/candidate is authorized.** First compare C20/C21 authoritative planning captures to establish whether `cdf0e2f2` engaged, was bypassed, or engaged but was insufficient.

### C20 Handles terminal rerun — strategy reset

- Comparable run `handles-cli-node_nemotron-elastic_codex_pon_1790205888` under exact note `BATTERY2 L5 nemotron-elastic 810a517e p10` ended `milestone-stalled-30min` after **200 calls**. Final packet `/home/jesse/.cria/suite/_usefulness_evidence/handles-cli-node_nemotron-elastic_codex_pon_1790205888.txt` records **50%**.
- C20 left no `package.json` test script: `npm test` fails, and its attempted test artifact was renamed to `test_old`. Heartbeat `2fc1a34c` was removed after terminal reporting.
- **No further generic Handles rerun is authorized.** Canonically walk C20 to its pre-stall absent-test-runner transition before selecting another candidate.

### C19 Cart terminal rerun — strategy reset

- Comparable run `cart-billing-go_nemotron-elastic_codex_pon_1790198063` under exact note `BATTERY2 L5 nemotron-elastic 08215092 p9` ended `milestone-stalled-45min` after **494 calls**. Canonical milestones were 55% continue then 50% stalled; final packet `/home/jesse/.cria/suite/_usefulness_evidence/cart-billing-go_nemotron-elastic_codex_pon_1790198063.txt` records **50%**.
- The archive contains a substantial decimal/JSON/test attempt, but `go test ./...` first lacked `go.sum` and then exposed incompatible shopspring decimal API/type use across `cart.go` and `cart_test.go`. The heartbeat `66810bea` was removed after the terminal report.
- **No further generic Cart rerun is authorized.** C13 25% → C14 5% → C19 50% does not establish convergence. The next unit must walk C19’s full decisive capture to the transition where unsupported decimal API/type assumptions reached the coder, prove a new deterministic owner and capture-shaped replay, or select another unmet cell.

## Rejected candidates

*(Every rejected candidate with the evidence that rejected it. Rejections are load-bearing:
they stop the next session from re-deriving a dead end.)*
