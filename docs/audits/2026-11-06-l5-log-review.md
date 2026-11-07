# November 6 L5 reruns: combined 17-cell log review

Campaign: `red-20261106-l5`, deployed source `f132382e`, planner OFF. This is a diagnosis-only review of the 17 authorized final attempts, not another campaign, a rescore, or an implementation change. See [campaign record](2026-11-06-red-l5-reruns.md) for judgments and the correction that selection used historical scores rather than latest standing red cells.

## Scope and standard of evidence

All 17 final harness logs were searched and selected chronological incident neighborhoods inspected. Selected full model-facing prompts, semantic responses and reasoning were read for every cell; additional long captures were inspected only in bounded neighborhoods where explicitly identified below. The detailed qwen3.8_9b_distill / Java follow-up is recorded in its cell section. This is not a byte-by-byte read of every log or an all-call reasoning walk. In particular, the k2_horizon_7b / Java response's large raw generation-evidence payload was parsed for its semantic message and metadata, not read byte-for-byte. No behavioral prevalence or counterfactual usefulness improvement is claimed.

Three read-only investigators covered phi4, ling3.0_tiny, and qwen3.8_9b_distill/k2_horizon_7b. The parent completed the two Python review walks and checked source-level confirmation, gate and participation control flow. Initial investigator notes contained incomplete coverage and hypotheses; this combined document supersedes those provisional claims where corrected below. Candidate defects, review errors, delivered guidance, suppressed guidance and campaign stopping observations are distinguished. No candidate code was executed, no tests written or run, no service restarted, and no result rows or battery report changed for this review.

## Confirmed findings, in priority order

### 1. Unobserved confirmation was accepted as approval

**phi4 / Node**, review `0030-satisfaction`, turn `050f8804`.

The full prompt carries the original requirements for built-in fetch, real end-to-end tests and Dockerfile; actual paired source reads show `require('node-fetch')`. The response declares completion and explicitly says tests/Dockerfile are not original deliverables. That is a false review, not an ambiguity in the task.

The downstream sequence is `loop.confirm_unchecked` with `workspace not surveyed` → `loop.satisfaction_confirm confirmed:true` → `loop.task_review satisfied:true/status:approved`. Source `cria/completionconfirmation.py::confirm` returns `Status.UNCHECKED, confirmed=True, observed=False` for an unsurveyed workspace. The satisfaction caller in `cria/loop.py::judge_satisfaction` tests the confirmation boolean rather than requiring observed confirmation. This establishes a fail-open scheduled approval path. It does **not** establish terminal task acceptance: subsequent completion checks ran and then encountered the separate loop below.

### 2. Completion-check setup loop delayed delivery of an already observed failure

**phi4 / Node**, inbound turns `990ece73`, `cf7cc814`, `ad931c62`.

Complete decoded captured check outputs show an alternating sequence: `npm test` fails with `mocha: command not found`/exit127; another probe set returns a complete survey including the manifest declaring `mocha`; a subsequent set again reports the same test failure. The structured sequence repeatedly settles as survey-only/replan and immediately issues another check rather than another coder generation. These selected transitions are cria control flow, not repeated coder-initiated tests.

Mechanism: `cria/probegate.py` computes `replan_after_survey` after applying newly returned observations; `cria/repositorychecks.py::record` makes that state non-fresh; the completion path in `cria/loop.py` reissues a probe before returning errors to the coder. The exact reason probe selection kept changing is not yet isolated. Repeated `loop.history_rewritten` is correlated, not proven to invalidate the survey. There was some intervening upstream activity outside the selected immediate transitions, so the whole late run must not be described as uninterrupted check-only execution.

### 3. A second positive review confused current schema with migration

**qwen3.8_9b_distill / Python**, full `0256-satisfaction` prompt, response and reasoning, turn `7ebd5dc8`.

The original task explicitly requires migrating existing databases containing live data. The supplied complete current `orders/db.py` only executes `CREATE TABLE IF NOT EXISTS` with the new column in the creation schema. The actual schema of one already-updated database and passing tests against fresh databases do not establish migration of old tables. Nevertheless the reviewer approves all requirements, after mentioning migration in its own requirement list and then dropping it from the justification.

**Downstream outcome matters:** this positive response was not accepted as task completion. The required-test participation check returned `unverified-source`; task review and completion critic rejected. The next coder (`0260`) received a generic required-tests-not-proven steer, not this missing-migration diagnosis, and requested more source reads. This is a confirmed review false positive caught by another brake, not another observed terminal fail-open.

### 4. Test execution evidence did not become usable test-source evidence

**qwen3.8_9b_distill / Python**, same `0256` → `0257` → `0260` sequence.

The gate report says test participation is proven and quotes the actual successful pytest summary, but reports unknown test participants and an empty `executed_test_sources`. `cria/completionapproval.py::test_participation` consequently returns WITHHELD before inspecting whether the executed tests satisfy the HTTP requirement. The recorded gate used `python3 -m pytest -q`; the displayed quiet result did not identify the individual executed test sources. Source ownership of mapped test bodies resides in `cria/participation.py`; a compileall participant list is not proof that those files ran as tests.

Withholding unknown evidence is appropriate. The failure opportunity is upstream evidence acquisition and the resulting feedback: green tests, rejected completion, generic instructions, then more reads rather than an established route to obtaining the missing participation/source link. This selected sequence includes a real coder turn, and the full review prompt retains earlier migration research. Do not claim an uninterrupted check-only loop, that migration was never considered, or that tests passing would make the unfinished migration complete.

### 5. Compaction supplied false state, including a changed task location

- **qwen3.8_9b_distill / Java:** the full `0124` review prompt contains a successful compile and the actual subsequent `ConcurrentModificationException`. Inspection continues through `0125`/`0126`; the final verdict is negative but lacks usable evidence fields, so cria suppresses its diagnosis. The next accepted compactor response `0127` replaces that situation with obsolete type-mismatch compile errors. Full subsequent coder `0131` has neither the runtime exception nor the judge's concurrency explanation; its response starts investigating compilation again. This traces a concrete loss of current ground truth through to the immediate next action. It does not prove a particular concurrency fix would preserve totals, achieve4× speed, or change the final campaign outcome. Full initial review and next coder were read; follow-on inspection/compactor prompts were read only around the relevant observations, while their semantic responses/reasoning were read completely.
- **ling3.0_tiny / Java:** full generator `0050-self-compact-noreason` contains a real `pom.xml` read with OpenCSV5.10, but its response says OpenCSV is missing. Full validation calls `0051`/`0052` and the structured event show acceptance; the exact false candidate appears in coder `0053`. This is **model-authored false state accepted and injected by cria**, not deterministic fabrication. The retrospective lens distinguishes state from instructions; file/size lenses did not check the dependency claim. The summary was labelled unverified and contrary source remained present, so sole causation of the stall is not established.
- **k2_horizon_7b / Rust:** full generator `0089` changes original “in this directory” into a nested `toml-key/` task. **Correction to preliminary notes:** that exact response was rejected as PLAN, not injected into `0101`. A different coder-visible rollup in full `0101` independently repeats the nested task description; its generating call was not established. The nested project was created much earlier, so the later summary did not originate the placement error. Its role in preserving that error is plausible, not measured.
- **ling3.0_tiny / Python:** full `0147` retains newer source and failures alongside a false rollup and explicitly historical NameError guidance; reasoning treats the old NameError as current again. The check itself did not falsely report the old failure as fresh. This is a context-grounding failure despite available qualifiers.
- **ling3.0_tiny / Go:** selected late `0208` context conflicts with the explicit unchanged-field-types requirement, and its reasoning proposes changing `Item.Price`. Full earlier `0151` shows appropriate source-reanchor action. The exact late write and summary's causal contribution were not fully walked; the campaign's observed regression must not be attributed solely to compaction.

### 6. Finding a real fixture bug did not result in delivered correction

**k2_horizon_7b / Python**, full `0021-satisfaction` prompt and response including reasoning, turn `1079def0`.

Actual recorded writes show `_start_server` starts the HTTP server on a selected free port but returns `proc.pid`; fixtures use that returned process ID as an HTTP port. This concrete candidate defect is corroborated by final source and later failed tests. The reviewer identifies it, but declares `missing_content/workspace_file` while current workspace bytes are explicitly unavailable and the quoted supposed contiguous snippet omits an intervening `yield port`. It also overstates verification of other requirements from source alone.

Cria suppresses the diagnosis with `workspace file or complete content is unknown`, rejects completion, then starts a periodic gate. There is **no later upstream coder dump in this final session**. The next and final inspected inbound outputs report the same gate transport still running at4.5s and333.1s. Thus this final diagnosis was not delivered to another coder generation before the run stopped. That does not prove no earlier hint reached the coder, nor explain why this check took so long. The review itself consumed roughly six minutes according to its authoritative event timestamps; no timing estimate is inferred from log length.

**Counterexample to treating every suppression as a defect:** phi4 / Go `0037` asserts missing content it could not inspect and uses a detector's repetition claim as file evidence. The downstream negative-diagnosis suppression/withheld review correctly prevented that unsupported diagnosis being injected. Both cases expose the need for reachable fresh evidence, not permission to bypass grounding.

### 7. Node install cache was outside the writable cell environment

**ling3.0_tiny / Node**, actual harness lines7539–7552.

`npm install` fails EROFS opening `/home/jesse/.npm/_cacache/tmp/670e8b2a`; its log directory under `~/.npm` is also unwritable. `suite/run.py` redirects `npm_config_prefix` but not `npm_config_cache`; `XDG_CACHE_HOME` is not npm's cache redirect. This is a concrete suite environment omission, not evidence to relax the sandbox. Installing dependencies was also in tension with the task's no-node_modules requirement; the cache failure does not explain every Node failure.

The candidate's later test invokes `node "${process.argv[1]}"`, meaning the test itself rather than the CLI. That is a separate confirmed test defect and a plausible process-multiplication mechanism. Later OS error11 and the long-running gate do **not** establish that recursion caused process exhaustion; no decisive process tree was captured in this review.

### 8. Environment noise and generic advice displaced task-specific grounding

**phi4 / Ruby** full coder `0021` shows a handoff describing unrelated GitHub tool-version fetching as the task, followed by reads/edits of nonexistent root `shipping.rb` rather than existing `lib/shipping/rates.rb`. Actual file-not-found output is not a dependency outage. Across inspected captures, mise version-resolution403 warnings appear inside real local tool results and then summaries. The source/result contamination is confirmed; a quantitative impact or universal source of the warnings is not established.

Missing `cargo-clippy` in both inspected Rust cells and read-only rustup installation attempts are toolchain/environment issues, not proof the requested Rust behavior is impossible. In k2_horizon_7b / Rust `0101`, reasoning misattributes advice in an unverified handoff to an actual steer. Actual nested tests/builds cannot demonstrate the requested root invocation.

**Qualified guidance concern — k2_horizon_7b / Ruby:** the task expressly permits changing self-added tests, but generic guidance prominently prohibits changing assertions except for a narrow external-system exception. Other sentences preserve flexibility for cases not named by the task; therefore this is mixed/ambiguous advice, not proof of an unconditional ban. Two self-added expectations require21.49 for express2kg where the task's14.99 +2.50/kg equals19.99. That mismatch is a test expectation defect, not evidence that the implementation's19.99 was wrong. The coder noticed the arithmetic; its failure to land a correction cannot be assigned solely to the steer.

## Cell-by-cell coverage and feedback

The following are incident observations, not new usefulness judgments. Capture roots and final run IDs are indexed below.

### phi4

- **Ruby:** full coder `0021` prompt/reply/reasoning, tool-error neighborhoods and turn `edb31804`: wrong-path actions and handoff task drift; actual FileNotFoundError. No proof every action in the batch completed or that completion was accepted.
- **Go:** full review `0037` and earlier `0024`: no readable current production bytes; unsupported negative inference; turn `690c1461` suppresses diagnosis, withholds review, then resumes coding. No demonstrated useful corrective steer from that review.
- **Python:** full coder `0044` prompt/reply includes actual landed snippets: import changes leave `db` references unbound, response headers are ended too early/twice, customer branch references undefined `cursor`. No redirection before the next read in that selected sequence; later repairs are not ruled out.
- **Java:** full `0044-coder-s1-focus1` and returned source in `0046`: actual Maven syntax failure and duplicate declarations/worker blocks. Focus steer elicits a read, not a repair; not proof that a read was locally wrong or caused the eventual stall.
- **Node:** full review `0030`, original events and three decoded check transports: false approved review, unchecked confirmation, then check replanning loop. Distinct defects; overall completion was not shown to be released.
- **Rust:** full coder `0074` prompt/reply shows historical compile errors and unverified passed-work claims, then a multi-edit/check/completion batch. Actual clippy unavailable; later `loop.satisfaction_blocked` at `c01fdf47` prevents simple acceptance. Individual batch edit outcomes were not all decoded.

### ling3.0_tiny

- **Ruby:** full coder `0090` prompt/reply/reasoning contains successful gem install/load and actual ISO3166 source, yet repeats wrong `Countries::Country` namespace. Current NameError/unknown-zone failures were available; not an ongoing installation outage.
- **Go:** full coder `0151` prompt/reply/reasoning, turn `8e0ec34b`: real undefined identifiers → module-state REANCHOR → source reads. Late `0208` adds the explicit-contract regression lead with the limits described above.
- **Python:** full coder `0147` prompt/reply/reasoning: newer source, HTTP404 and accumulated shared-database records coexist with stale NameError guidance. Its added GET-all test expectation is not necessarily a requested route. Coder-side `pytest | head` masks shell exit status; this is not cria's independent gate claiming success.
- **Java:** full coder `0053`, accepted generator `0050`, validators `0051`/`0052`: false dependency briefing plus real missing-import compiler failure. Subsequent reasoning identifies the import without an established landed correction; no single-assist causal claim.
- **Node:** full coder `0021` prompt/reply/reasoning: runner reset is followed by another `describe is not defined` run. Separate cache-isolation failure, later self-invoking tests, and OS error11 are distinguished above. A gate reporting `ran:false` is not a test pass.

### qwen3.8_9b_distill

- **Python:** full review `0256` prompt/reply/reasoning; exact downstream events through `0260`; selected next coder's steer and full reply. False migration approval is caught by participation withholding; actual next action is more reads. Earlier migration research exists. No exhaustive earlier-guidance census or uninterrupted check-only claim.
- **Java:** full `0124-satisfaction` prompt/reply/reasoning and full `0131-coder-s1` prompt/reply/reasoning, plus the `0125`/`0126` inspection replies and `0127` compactor response. Original runtime/log neighborhood distinguishes missing classpath, refused external scratch path, and then real worker failure with `ConcurrentModificationException`; compilation had succeeded. Turn `6938d9b7` performs two inspection rounds: `0124` is not a verdict, `0126` emits the final negative verdict. Its evidence fields are empty and `proposed_fix` repeats a schema instruction; suppression cause is `unknown evidence source`. Completion stays rejected, but the accepted compactor then supplies stale build-failure state. Next coder `0131` receives no exception/concurrency diagnosis and asks for files to investigate compile errors. The judge also assumes four threads imply4× speed; that is not measured performance. Green Maven output with no tests to run does not negate the failed runtime invocation. Large follow-on inspection prompts and the whole compactor prompt were not read end-to-end; this is a bounded feedback trace, not an all-call walk.

### k2_horizon_7b

- **Ruby:** full coder `0048` prompt/reply/reasoning and selected feedback in `0051`: actual EU_COUNTRIES constant error, but source defines a method of that name. Real failing test output and source reach the later prompt; the reply still claims EU works and speculates about stale checkout. Those claims are unsupported. Earlier review turn `4d619fcb` withheld a diagnosis; it is not proof of what fresh later steer was delivered. Incorrect self-added express assertions must not be counted as implementation defects.
- **Python:** full review `0021` prompt and semantic response/reasoning; exact suppression and later gate transports. PID/port mismatch identified, diagnosis not delivered to a subsequent coder before stop; no later coder generation exists in this session. Final no-change interval includes review/check waiting.
- **Java:** full coder `0023` prompt/reasoning and parsed semantic response: original task and seed source are present; generation ends `rumination`, null public content and no tool call. Full following `0024` response to an inspected focus instruction proposes two pom edits, not a source implementation edit. No paired outcome for those proposals was established in the selected capture. Guard elicited proposed action; neither successful landing nor useful task correction is proven. Do not call this blanket task loss or total absence of guard response. Missing OpenCSV5.9.1 was a real version error; later5.9 resolution succeeded, so no general Maven/network outage.
- **Rust:** full `0089` generator and `0101` coder prompt/reply/reasoning: rejected wrong-location summary, different later wrong-location rollup, real nested build/tests, and missing-clippy detour. A location-specific corrective steer reaching the coder was not established. Do not infer requested root behavior from nested green checks.

## Campaign stopping interpretation

The campaign records requirement-pace stops; they are not natural task completions. This review does not reverse those decisions or replace their scores. In particular, the final k2_horizon_7b / Python interval includes an expensive review followed by pending check transport without another coder call. A flat workspace during that interval does not show that the coder ignored a useful delivered diagnosis. ling3.0_tiny / Node checkpoint evaluation was asynchronous with later coder/check activity. The logs establish these timing confounds, not that a specific extension would have completed either task.

Selection's historical-score mistake is separate from the runtime findings. It explains why the authorized selection was not the set of latest standing red cells; it does not explain the observed control-flow defects or erase delivered-code regressions.

## Investigation boundaries and next repair targets

The strongest located repair targets are unchecked approval consumption, nonconvergent survey/replanning transitions, missing test-source linkage in the selected completion evidence, and npm cache isolation. The missing linkage is a confirmed evidence-acquisition bottleneck, not a reason to label its correctly withholding consumer defective. Compaction fidelity and current-evidence delivery also have concrete captured counterexamples. Reproduce those local invariants from the retained captures before choosing implementation changes; this document does not prescribe keyword filters, looser grounding, extra process gates, or relaxed sandboxing.

Still unresolved: exactly which workspace-view transition makes the Node probe choices alternate; why the final k2_horizon_7b / Python gate remained running; provenance of the particular coder-visible Rust rollup; the exact late Go write/summary causal chain; whether recursive Node tests caused the later resource exhaustion; and counterfactual usefulness gains from repairing any assist. Partial capture neighborhoods and generation-evidence limits remain explicit rather than being promoted to an exhaustive audit.

## Evidence locations

Original harness logs: `~/.cria/suite/_campaigns/red-20261106-l5/<run_id>.log`. Original model captures and lane events live under `~/.cria/suite/_lanes/<lane>/rows/<row>/calls/<session>/` and sibling `logs/cria-20261107.jsonl`. Capture numbers in the sections above are relative to their cell's session. The exact index follows.

- `orders-api-py_phi4_codex_poff_1794013263`: `~/.cria/suite/_lanes/3090x4/rows/phi4-L5-1794013252/calls/20261106T170103-01a1b385-f831-70f2-993c-3ead41f28130`.
- `cart-billing-go_phi4_codex_poff_1794013263`: `~/.cria/suite/_lanes/3090x4/rows/phi4-L5-1794013252/calls/20261106T170103-01a1b385-f832-7d41-b518-1c13e2bc2393`.
- `feed-pipeline-java_phi4_codex_poff_1794013263`: `~/.cria/suite/_lanes/3090x4/rows/phi4-L5-1794013252/calls/20261106T170103-01a1b385-f860-7321-984c-1a3db79759fb`.
- `shipping-rates-rb_phi4_codex_poff_1794013263`: `~/.cria/suite/_lanes/3090x4/rows/phi4-L5-1794013252/calls/20261106T170103-01a1b385-f84c-7841-9620-c1797ee75f6b`.
- `rust-toml-cli_phi4_codex_poff_1794015153`: `~/.cria/suite/_lanes/3090x4/rows/phi4-L5-1794013252/calls/20261106T173233-01a1b3a2-ceef-7871-baba-e4e43b62a4af`.
- `handles-cli-node_phi4_codex_poff_1794015153`: `~/.cria/suite/_lanes/3090x4/rows/phi4-L5-1794013252/calls/20261106T173233-01a1b3a2-cef0-7582-b6ee-e951d6b6b21f`.
- `rust-toml-cli_k2_horizon_7b_codex_poff_1794025777`: `~/.cria/suite/_lanes/3090x4/rows/k2_horizon_7b-L5-1794025765/calls/20261106T202937-01a1b444-eafa-7a33-9f12-0f7021a77e5b`.
- `shipping-rates-rb_k2_horizon_7b_codex_poff_1794025777`: `~/.cria/suite/_lanes/3090x4/rows/k2_horizon_7b-L5-1794025765/calls/20261106T202937-01a1b444-eb15-7662-a2bb-8edebf83704e`.
- `feed-pipeline-java_k2_horizon_7b_codex_poff_1794025777`: `~/.cria/suite/_lanes/3090x4/rows/k2_horizon_7b-L5-1794025765/calls/20261106T202937-01a1b444-eb11-76d0-b2b2-929c0239eaab`.
- `orders-api-py_k2_horizon_7b_codex_poff_1794025777`: `~/.cria/suite/_lanes/3090x4/rows/k2_horizon_7b-L5-1794025765/calls/20261106T202937-01a1b444-eb16-7d50-85d3-2587b0c3ff99`.
- `cart-billing-go_ling3.0_tiny_codex_poff_1794013252`: `~/.cria/suite/_lanes/3080x2/rows/ling3.0_tiny-L5-1794013242/calls/20261106T170053-01a1b385-cef4-7852-9415-561fffca06ae`.
- `shipping-rates-rb_ling3.0_tiny_codex_poff_1794013252`: `~/.cria/suite/_lanes/3080x2/rows/ling3.0_tiny-L5-1794013242/calls/20261106T170053-01a1b385-cf10-72a0-98e1-7d2f5b25dbcb`.
- `orders-api-py_ling3.0_tiny_codex_poff_1794015152`: `~/.cria/suite/_lanes/3080x2/rows/ling3.0_tiny-L5-1794013242/calls/20261106T173233-01a1b3a2-ce6b-7510-ab53-adbd28d1a757`.
- `feed-pipeline-java_ling3.0_tiny_codex_poff_1794016014`: `~/.cria/suite/_lanes/3080x2/rows/ling3.0_tiny-L5-1794013242/calls/20261106T174655-01a1b3af-f3de-7071-ac1d-b6d661b859e7`.
- `orders-api-py_qwen3.8_9b_distill_codex_poff_1794025764`: `~/.cria/suite/_lanes/3080x2/rows/qwen3.8_9b_distill-L5-1794025750/calls/20261106T202925-01a1b444-bbfb-7e10-9db1-de488790ff64`.
- `feed-pipeline-java_qwen3.8_9b_distill_codex_poff_1794025764`: `~/.cria/suite/_lanes/3080x2/rows/qwen3.8_9b_distill-L5-1794025750/calls/20261106T202925-01a1b444-bbfb-74f0-9a1e-8dd480a84338`.
- `handles-cli-node_ling3.0_tiny_codex_poff_1794028580`: `~/.cria/suite/_lanes/3080x2/rows/ling3.0_tiny-L5-1794028570/calls/20261106T211621-01a1b46f-b0c3-7f83-b60e-af6b25594555`.
