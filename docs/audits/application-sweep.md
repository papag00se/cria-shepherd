# Application sweep — assists that collide, assists that break the doctrine

Twenty lenses over 33,386 lines, 165 prompts and 206 test files. Each agent worked from a generated inventory of every emit site, guard, prompt and constant, and was held to one standard: **read the source, quote it, and say whether it can actually happen.** Findings that turned out to be deliberate are recorded as such; several lenses came back partly empty and said so.

Three fixes landed during the sweep and are struck through below.

## The dominant pattern: cria has less coverage than it believes

More than a third of the findings are the same shape — **a mechanism that cannot fire, or fires into a field nobody reads.** They pass their tests, they emit their events, and they have never once done their job.

| mechanism | state | evidence |
|---|---|---|
| ~~the gate's finding-set (`last_gate_flag`)~~ | ~~5 readers, 1 writer, unreachable on plan-off~~ | ~~348/410 suite rows and all 129 captured sessions are plan-off~~ **fixed** |
| ~~the test tally + skipped count~~ | ~~read from a field that is a fixed string on green gates~~ | ~~`gate_skipped_count` has returned 0 for every run cria has ever made~~ **fixed** |
| the harness-compaction detector | never fired; 4 mechanisms hang off it | harness compacted 139 times, `loop.history_rewritten` = 0, all 256 persisted flags `False` |
| the steer author's "don't re-diagnose unchanged findings" guard | wiped by the two guards that fire most | `loop.steer_same_checks` = 0 fires in 5 days; 318 steers passed no check text vs 44 that did |
| the window-exhaustion abort | compares SSE **frames** against **estimated tokens** | 0 fires; 5 calls ran to the window limit and had 38–44K tokens discarded |
| `_FALLBACK_WINDOW = 8192` | collapses the budget to the 512-token floor when in force | 52 floor runs, **100%** declared over-budget, 934 protected messages destroyed |
| `_mark_own_notes` | has never marked a line | its 3 keys are the markers that never return; the one that does isn't a key |
| the plan-ON driver | dormant | every completion event in 5 days carries `plan_off=True` |

Several fixes — including ones I landed today — went into paths that no real run takes.

## cria telling the model things that are not true

- **"The repo's automated checks pass" when the gate never ran.** One return value covers green and never-ran; two of three callers hardcode the passing wording. The prompt file holding the `never_ran` alternative opens with a comment recording this exact incident. **80 fires; the honest wording has fired 0.** Twice the same prompt's newest check block showed failing tests.
- **`⟦ctx:live-execution⟧` ends with a hardcoded "Everything else the checks cover passed"** — a claim about the repo's checks from code that never reads them. Caught 37 KB below a Java `COMPILATION ERROR`.
- **Every superseded write is stamped "this exact content is on disk at PATH."** `last_write` is one message index, not one per path: a real prompt carries six stamps for one Ruby file at **four different byte counts**.
- **A spill file is named before it exists** — the path is derived from the doc cache's size, never the filesystem. Observed: prompt 0017 tells the coder to grep a file first announced in 0018.
- **`guard_truncation` told the model "your last write was refused… partway through writing the file" 17 times out of 17** on turns cria itself had marked as *not a write*.
- **"This list is complete" over a filtered listing** — `execcheck` states the rule in cria's own words one module over.

## cria doing the coder's work

- **The dictated-code strip keeps the broken symbol and deletes the fix.** It asks "did the author read this?" by checking tool output — and a compiler error *is* tool output, so the wrong symbol is the best-attested string in the prompt. Live: *"replace `decimal.NewFromInt64` with [code removed]"*.
- **The judges' "Proposed fix" reaches the coder with one guard where a steer gets nine** — 105 instances across 39 of 100 sessions, choosing libraries, base images, filenames, SQL and shell commands. The comment above it claims it is held to the steer's bar.
- **Two prompts still ask a judge for "one executable next step"** — yesterday's fix landed in one file of three.

## The token leak is an order of magnitude larger than measured

- **131,946 occurrences across today's 1,433 coder prompts** — 6.1% of every byte cria sends, 31.6% of the worst single prompt.
- **Three different models copied the wrapper back**, 21 responses across 5 sessions; one reproduced the whole four-probe gate script including the offline leg.
- It **poisons the repetition detector**: the boilerplate contributes ~35 shared words against the real command's 1–4, so `cat main.go` matches `mv cart.go .`. Fired 3 times live, each costing a probe and a reasoned redirect.
- The steer author's transcript is *defanged* so there is "nothing a model can COPY" — and carries 557 characters of runnable shell per call.
- **One fix closes four findings**: make `_strip_gate_plumbing` reduce each probe line to the inner command, which is what its docstring already claims.

## Waste that is measurable

| | cost |
|---|---|
| `exec-intent` re-asking byte-identical questions | 104 identical repeats, 82,221 tokens |
| the classifier returning empty at `finish_reason=length` and being re-asked | 14 calls, **229,376 tokens, zero verdicts** |
| the periodic check-in restating output 140 bytes above it | 37 of 78 injections (47%) |
| the task emitted twice into one prompt | 31 of 42 (74%), median 849 B, max 18 KB |

## Silent failures outside Python and Codex

- **Go's deleted-test detector is structurally dead** — cria composes `go test` without `-v`, so there is no per-test line to count. The incident that motivated it was a Go cell. *(Recorded honestly in its test rather than papered over.)*
- **A `package.json` whose test script is `node tests/x.test.js` yields zero test probes and no warning.** Vacuous green.
- **`focus_tools` can delete the harness's shell tool** — six literal names used as a "family". Gemini CLI loses `run_shell_command`; Cline/Roo is reduced to `read_file` alone. On by default.
- **The workspace root has exactly one source** — Codex's `<cwd>` — with no override, so the whole ground-truth layer silently disables on any other harness.

## Ordering

- **A guard-probe steer returns before the gate result is recorded.** The probe runs the *same* script as the completion gate; the reader writes none of the nine fields. **14 of 41 plan-ON gate readings discarded**, and it fails *toward* completion — an unrecorded red leaves the satisfaction check unblocked.

## Tests that pass while the rule ships broken

- A guard test filtered call sites **by counting parentheses**, so 1 of 4 qualified — and the briefing writer is told "no error-class problems" about a gate whose real finding is a stranded test file.
- Two "EVERY caller" tests both miss the same fourth caller: one names three methods by hand, the other matches a literal string the caller passes as a variable.
- Two tests execute **zero assertions** — the function under test no longer exists, or is never called.
- Mutation-checked: deleting the periodic-satisfaction cadence gate leaves its whole file green.
- Rules with no class-level test: **5, 11b, 12**, and 2's language-blind form.

## Where the standard was met

Recorded because a sweep that only lists faults is not a measurement. Read end to end and found correct: the repeat web-search and web-fetch gates (refuse only while the earlier result is visible, and say why — the shape the others should copy); edit-recovery (one owner, monotonic, 125 logged escalations); the workspace-boundary owner; `content_reduce` and every spill path; the `⟦cria⟧` strip on both wire paths; validate-before-lower's regression-only shape on both halves; the MODEL lens entirely — four reasoning conventions, dialects matched broadly. Roughly twenty guard chains were cleared by name so the next pass does not re-walk them.
