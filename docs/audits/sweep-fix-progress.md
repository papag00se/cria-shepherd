# Sweep fixes — running ledger

Working through [`application-sweep.md`](application-sweep.md). Each entry: what was wrong, what the evidence said, what landed. Every fix ships with tests proven to fail on the old code, and the full suite green before commit.

Newest last.

## Landed

### 1. The compaction retry was grounded worse than the pass it replaces
`_harden_compaction_reply` re-asks for the briefing when the first reply came back empty, truncated, or as a hallucinated tool call — and composed that retry with no workspace inventory, while the first pass passes one. It also derived the session key twice. **Fixed**: both grounding facts threaded, key derived once.

The gate plan was threaded into `compaction_request` at the same time (it was the one caller of four that dropped it), and **recorded as inert**: a raw gate blob does not reach that call, because `___CRIA_GATE_` is an anchor marker and both callers strip anchors from the summarizer input. 0 of 70 real self-compact prompts carry one.

### 2. The harness-compaction detector had never fired — not rarely, never
`loop.history_rewritten`: **0 events, ever**. `route.compaction`: **139** in the same window. 256 persisted shapes, all `sid:`-keyed, **0** pending. Four mechanisms hang off that boolean, so a gate result destroyed by a compaction was simply gone.

The premise was wrong. "Compaction REPLACES the conversation root" is one way to rewrite a history and it is not Codex's: Codex keeps every user message, the original task among them, and drops the assistant/tool items behind them. What changes is the LENGTH — and `observe_shape` was already being handed `n_messages` and storing it without ever comparing it.

Measured across 141 real sessions: inbound length dropped **108 times, all 108 after a compaction**, no false positives. 56 of the 60 compacting sessions show it; the drops are 144→4, 172→4, 169→4. **Fixed**: both signals kept. The continuation planner was corrected to match — it was handed the root as "the harness's summary", which under Codex's shape is the original task.

### 3. A gate cria READ was thrown away when the turn returned through a different door
`guard_probe_steer` reads the same probe result the completion gate reads — same call id, same plan — and recorded none of it, then returned the steer. So a gate that went green→red on a redirect or wheel-spin turn left `last_gate_red` False and `gate_fresh` True, and the completion backstop, the satisfaction judge, the rollup override and the steer author were all answered with the PREVIOUS gate. Failing open toward "done" is the one direction #13 forbids.

Three readers of one fact, two writing it inline and the third writing none — **fixed by extraction**: `record_gate_state` is the only place a reading becomes state. A fourth reader turned up while wiring it (`guard_periodic_result`, omitting `last_gate_ran`) and was folded in, keeping its one real difference: a periodic check-in must not set `gate_fresh`.

A follow-up commit deleted a private redness function this fix had itself introduced — `gate_error_text` already existed and is better.

### 4. The window is a measurement, not a constant
When `/props` cannot be read, cria commits to `_FALLBACK_WINDOW = 8192`. **52 floor runs happened against it: over-budget on 52 of 52, 934 protected messages destroyed** across 6 sessions — while the real window was 49,152, and the server was answering every one of those calls and reporting the real token counts back in `usage`.

Erring large is recoverable (`_overflow_refit` re-preps once against the server's own count, 47 of them in the same window). Erring small is silent and permanent. **Fixed**: `_calibrate` raises the window to what the server demonstrably fit, and `_overflow_refit` adopts the `n_ctx` the 400 states — which it was logging and discarding.

The runaway-abort guard was gated on `_window_final`, which answers "stop probing", not "is this number real", so it was off before the first probe and forever after a fallback. **Fixed**: gated on `_window_guessed`.

Its test module asserted the rule and never drove the path — eight tests, all `inspect.getsource`, constant values and arithmetic on literals, all green while the guard had never once fired and 4 of the 14 runaway calls (43,873 / 42,673 / 40,720 / 38,025 completion tokens, every one totalling exactly 49,152) happened AFTER it shipped. Rewritten to stream real SSE frames.

### 5. `_failed_edit_ids` guarded a function that has never existed
`hasattr(editrecovery, "is_edit_failure")` with a substring fallback — the attribute has always been missing, so the fallback WAS the rule (#4). **Fixed**: keyed on `EDIT_MARK`, which every edit-failure directive carries. Costs nothing today (the two rules agree on all 9,248 captured matches) but `old_string` is an ordinary token and reading any file that documents the edit tool would have collapsed the coder's own payloads. The test hand-typed a fixture the production path cannot emit; it now builds them with `editrecovery.compose`.

### 6. The name rode into a command the coder reads
`_COMPILEALL_SKIP_RE` listed `.cria` among its skip directories, and the coder reads the gate's command line — **2,050 captured coder prompts** carry it. It was also dead: cria never writes into the workspace (#7). `_named_gap` composed "What cria's own checks currently report" as an inline f-string (#17 and #22 in one line); latent, 0 captured prompts.

Rule 17 was tested over the prompt FILES only, which is why both survived. **Fixed**: the test now drives `probediscovery.discover` and `syntax_floor_candidates` over a fixture project and asserts over every composed argv element.

### 7. `loop.spin_probe_result` recorded a literal
`spoke=True` was hardcoded, so the log said "spoke" on **121 of 121** occasions and could not have said anything else (#12). **Fixed**: records who authored the steer and whether it carries ground truth. Swept the other 41 literal booleans in emitted events; the rest are one branch of a two-branch fact.

### 8. One copy of a repeated payload in the coder's view
Rule 5's first exception is de-duplication, and cria had the machinery pointed at exactly one thing: the fetch ledger. Replaying every captured coder prompt (6,614) through the new fold: **882 of them (13%) carry a byte-identical payload twice or more; 2,088,194 bytes, roughly 522K tokens.** Largest groups: cria's own refusal re-earned verbatim (352), a source file read twice (216), a spec file read twice (130), cria's own edit directive (126), one fetched page delivered twice (150).

Newest copy wins; n pointers plus one full copy, so the repeat count survives. Never an assistant turn, never a system message, never an anchor.

### 9. A judge's proposed fix cleared a lower bar than a steer
`proposed_fix` is authored text the coder acts on and faced one guard — the invented-route check — while an authored steer goes through all of `_grounded_steer_or_none`. **134 proposed fixes reached the coder across 41 sessions**; replayed through the steer guards, 10 are dropped for naming a URL, among them `https://github.com/guyp/decimal`, a repository that does not exist. **Fixed**: the evidence the judge itself saw is threaded to all four call sites, so a URL it legitimately read still goes through. No model call added.

### 10. dirguard judged tokens before establishing they were a command
Replayed over every captured refusal, each with its real workspace root: **51 distinct / 1,225 occurrences refused before, 31 / 733 after — 20 distinct / 492 occurrences (40%) that never should have been.**

- A **parameter value is not an access**: a weak model wrote a tool signature as a shell command (`exec_command cmd="go mod tidy", …, shell="/bin/bash"`) and cria refused it for the interpreter in the last parameter. Nothing there is changeable — the string was never a shell command (#5b). 9 distinct, 229 occurrences.
- A **suffix on an unresolved expansion is not a path**: `ls $(go env GOPATH)/pkg/…` contains no path the coder wrote, so whether it lands inside the workspace is unknowable (#11b). 11 distinct, 263 occurrences.

Everything the guard is for still holds.

### 11. One owner for "is this a test file"
`execcheck` kept a private regex in which `Test`/`Tests` had to END the stem, so JUnit's prefix convention `TestImporter.java`, `ImporterTestCase.java` and jest's `__tests__/` all read as ordinary source — while `TEST_CONVENTIONS` listed all three by name. In execcheck that decides whether a workspace has a program at all. **Fixed**: the classifier moved beside the table it reads; both callers defer. `conftest.py` is now correctly not a test.

## Still open

From the sweep, not yet addressed:

- the steer author's "don't re-diagnose unchanged findings" guard — 0 fires in 5 days
- "The repo's automated checks pass" when the gate never ran — 80 fires, honest wording 0
- superseded-write stamps: six stamps for one file at four different byte counts
- a spill file named before it exists
- `guard_truncation` "partway through writing the file" on turns marked not-a-write
- Go's deleted-test detector (structurally dead: `go test` without `-v`)
- `package.json` bare node test yields zero probes
- `focus_tools` can delete the harness shell tool on Gemini/Cline
- `_runnable` refuses `rake test` / `mix test` / `make run` that `corroborate` accepts
- `satisfaction_done_note` claims the repo's checks verified a run where none ran
- the periodic check-in restating check output 140 bytes above it
- `failover.run` has zero production callers; `Upstream(context_window=)` has no TOML key
- test modules that certify a rule the code no longer follows, and two that execute zero assertions
