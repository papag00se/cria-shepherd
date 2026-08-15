# 100% campaign — live progress

**This file is the status.** Not a chat message, not a memory, not an intention. The goal it serves
is `docs/goals/hundred-goal.md`. The score grid it summarises is `docs/audits/battery-report.md`, which
rewrites itself after every cell.

**Target: 24 of 24 cells at 100%.** Currently 9 — mean 53.8%.

---

## Cycle 2 — RUN in flight

**Phase: RUN.** Started **2026-08-15 09:02**, cell 1 of 24, task-major.
Driver `python3 suite/cycle_run.py` · log `docs/audits/cycle-run.log`.

Thirteen cria changes landed after cycle 1's run and none of them had been measured. That is what
this run measures. `cria.service` was restarted onto the current code state immediately before the
first cell; **nothing under `cria/` changes until the run phase ends.**

### Environment, verified clean 2026-08-15 (before cell 1)

- **`user_install_listing()` — no Ruby gems at all.** The `countries` / `unaccent` leak that inflated
  four Ruby rows is still gone. The listing carries only the pre-existing maven/cargo/go/npm/py
  baseline, and the tripwire is a per-run *diff* (`run.py:354` before, `run.py:455` after), so a
  standing baseline cannot inflate a score — only something installed *during* a cell can.
- **`git status --short suite/tasks` — clean.** No verifier is writing into the repo.

### Cells — cycle 2

| # | task | model | score | Δ pts | min | calls | what happened |
|---:|---|---|---:|---:|---:|---:|---|
| 1 | shipping-rates-rb | gemma4 | *running* | | | | |

### Run-phase investigations — the carried items, answered read-only

The run phase forbids touching `cria/`, so the carried items that were filed "needs a replay before
touching" got their read-only half done while cell 1 ran. Three of the seven now have answers, and
two of those answers are **refutations**.

#### 1. REFUTED — the 12 × HTTP 503 cost zero cells

The carried line said "12 × HTTP 503 hard-failed instead of retried." The count is right and the
consequence is wrong.

Every 503 in every log is in one of three bursts, each a few seconds long: 08-12 22:58:00–06,
08-14 03:46:36–42, 08-14 03:51:00–03. Read in full, each burst has the same shape — `server.stop
{"reason": "interrupt"}`, then a handful of turns from a session that was already running, then
`server.stop` again. That is the campaign driver restarting `cria.service` between cells while a
**leftover harness session from the previous cell** keeps POSTing. `connection refused` comes first
(the endpoint is down), then 503 (llama.cpp is up but still loading the model).

The check that settles it: **no scored run's `capture_dir` matches any of those three session ids**
(`019ff802`, `019ffe31`, `019ffe61`), across all 24 rows. They produced no row because they were not
cells. Cost to the campaign: zero checks, zero cells.

What is still true, and is now correctly ranked as cosmetic: `classify_failure` maps 503 to
`MODEL_UNAVAILABLE`, whose only action is walk-the-chain, and with the single-endpoint chain
`("upstream",)` that walk immediately returns `ChainExhausted`, so `upstream.chat` re-raises. A
transient "model is loading" is not retried. Worth fixing on its merits; not worth a tier.

#### 2. REFUTED — the context-window fallback is not a leak

Those same bursts show `context.window {"source": "fallback", "n_ctx": 8192}` where the real window
is 49152, and the floor then drops turns against the smaller number. That looks like a transient
error silently shrinking the window for the life of the process. It is not.
`upstream._resolve_window` sets `_window_final` **only on success**, re-probes on every call until
`_MAX_PROPS_ATTEMPTS`, and then keeps re-probing every `_PROPS_RETRY_EVERY`. The docstring names the
incident it was built for. Self-healing, bounded, no fix.

#### 3. CONFIRMED and quantified — the completion judge is absent exactly where it is needed

This is the real one, and it merges two carried items that turn out to be one root.

`_periodic_satisfaction` is the only completion judgement that does **not** need the coder to claim
done. It fires on a drive counter: `satisfaction_check_start = 80`, `every = 20` (this box's
`cria.toml`; the code default is 100/25).

Counted from the authoritative phase counts on all 24 cycle-1 rows:

| | cells |
|---|---:|
| reached the drive-80 threshold | **5 of 24** |
| never reached it | **19 of 24** |
| scored 0–50% | 11 |
| …of those, reached the threshold | **3** |

And the judgement census, counted from the events rather than inferred — `loop.satisfaction_check`,
`loop.done_critic`, `loop.done`, `loop.done_unverified`, `loop.satisfaction_confirm`,
`loop.satisfaction_failclosed`, `loop.done_confirm`, per session:

**Seven cells got no completion judgement of any kind.** Their scores: 0, 0, 0, 0, 0, 20%, 50%.
Every single cell that got no judgement is a cell that failed. Every cell that scored 100% got one.
*(The carried note said eight cells; seven is what the events say.)*

The reason the threshold is 80 is written down. `27512a9` built the check for a session that
**finished the work and could not stop** — "176+ calls on a done task" — and for that purpose a late
first check is correct; you do not ask "is it done?" at drive 5. `d4308bc` made the cadence tunable
because "different models spiral at different rates."

So the reason is still true *for the problem it was built for*, and it is the wrong shape for the
problem the campaign found. A → B → C, in plain words:

- **A** — the trigger is a drive counter, a proxy for "this session has gone on a long time."
- **B** — a run that is going badly is usually a *short* run (killed at a 15-minute milestone floor),
  so it never reaches the counter.
- **C** — cria forms no opinion at all about whether the task is done, on precisely the runs where
  that opinion is the thing missing.

**Not fixed in this cycle, deliberately.** Two reasons. One code state per cycle. And the experiment
that would justify a change has to run against the model, which is busy running cells — replaying
`judge_satisfaction` now would contend for the same GPU and corrupt the timings the cycle is
measuring. The fix phase runs it: replay the 19 short cells' captured evidence at drives 20/40/60 and
count how often the judge would have said *satisfied* on a red run. If that number is not ~zero, the
threshold is load-bearing as a false-completion guard (#13) and must not move.

#### 4. CONFIRMED — the failover chain-walk never shipped

`failover.run`, `Attempt`, `NextInChain`, `ChainExhausted` and `_walk` have **zero production call
sites**; `grep` finds `fo.run` only in `tests/test_failover.py`. The one live use is
`upstream.py:438`, calling `decide_action` with a one-element chain to get retry-once-on-timeout.
The module docstring advertises "a small buffered `run` executor that drives them," which is true of
the file and not of the running system.

Corroborating: **`route.retry_same`, `route.failover` and `upstream.retry` have never been emitted —
zero occurrences in every log on disk.** So even the retry-once-on-timeout that *is* wired has never
actually fired in production.

#### 5. CONFIRMED, but the carried note named the wrong function

The carried line read "`loop.py:3279` lets a regex decide alone; `8bdeee2` wired only the
satisfaction site." Half right, and the half that is wrong changes what gets fixed.

`verdict_from_reasoning` — the function at that line number today — **is** wired at both sites.
`loop.py:3413` builds `recover` from `self._ctx.reasoner_role` and hands it to both calls at 3417 and
3418, exactly as `8bdeee2`'s message claims; the satisfaction site does the same at 464–469. Nothing
to fix there.

The real asymmetry is its neighbour, five lines down:

| site | call |
|---|---|
| satisfaction, `loop.py:1546` | `_claims_impossible_action(obj, rlog, "satisfaction", fab_ask)` |
| step critic, `loop.py:3284` | `_claims_impossible_action(obj, rlog, "critic")` |

The `ask` argument is missing at the critic. `_claims_impossible_action`'s own docstring sets the
contract — "TRIGGER, THEN JUDGE… **With no reasoner the trigger decides alone**, exactly as before" —
so the degraded mode is deliberate, and reserved for having no reasoner. At the critic site a
reasoner is available and simply is not passed, so the mode meant for a missing reasoner runs with
one present. When `_JUDGE_ACTION_CLAIM` hits, the regex discards the verdict on its own; the
docstring names the false hits it cannot separate ("I ran the tests" vs "I ran through the
checklist"), and the cost of each is a good verdict thrown away and a retry burned.

**Prevalence: zero.** `loop.verdict_fabricated_action` has never been emitted — not once, at either
phase, in every log on disk. Denominator stated honestly: the logs only reach back to 2026-08-12,
four days, but that window contains cycle 1's entire 24-cell run, and the critic path was busy in it
(57 `loop.step_done`, 10 `loop.step_incomplete`).

So: a real inconsistency, a one-argument fix, and **tier 4 by impact** — recorded, not scheduled
above anything that actually cost a check (#15).

### Environment, verified clean 2026-08-14

- **The leaked gems are gone.** `countries-8.1.0` / `unaccent-0.4.0` uninstalled. They had inflated
  four Ruby rows since 2026-08-10; re-scored with the directory hidden those runs were 1/5, 1/5, 1/5.
  The untouched seed now scores an honest 0/5.
- **The Java seed's tracked build output is gone**, and so is the reason it existed — `verify.py`
  built its speed baseline inside the git tree. It builds a copy now, and `suite/tasks/.gitignore`
  stops the same class of artefact returning from any seed.
- Check both before every run phase: `user_install_listing()` and `git status --short suite/tasks`.

### Carried into cycle 2's fix phase

| finding | state |
|---|---|
| the periodic satisfaction check fires at drive 80 and almost no run gets there — 14 firings across 24 cells, 3 cells | open, needs a replay before touching |
| 8 cells got no completion judgement of any kind; their scores were 20/0/0/50/0/0/0/0 | open, same investigation |
| 12 × HTTP 503 hard-failed instead of retried — the ported table says "switch models", wrong for a single endpoint | open, operator ruling |
| `loop.py:3279` lets a regex decide alone; `8bdeee2` wired only the satisfaction site | open |
| `failover.py` — the chain-walk engine never shipped; the docs claim it did | open |
| six verdict-word readers with divergent strip sets | open, latent — zero occurrences measured |
| `_verdict` / `_satisfaction_verdict` are the same 60-line algorithm twice | open |

---

## Cycle 1

**Phase: WALK** — the run phase finished 2026-08-14 02:45, all 24 cells scored.

**Cycle 1 result: mean 53.8%, up from 51.2%. Nine cells at 100%, up from five.**

Read that as it is. Four cells gained a lot (+100, +75, +50, +50), four lost a lot (−80, −80, −60,
−25×3), and eleven did not move at all. The gains came from two task-prompt corrections and the
losses from cria; the eleven flat cells include five that never compiled and were never going to on
this code state.

*(An earlier running count in this file said twelve at 100%. It was a hand-incremented number and it
was wrong; nine is what the results file says.)* Java column complete: 0 / 40 / 0 / 0. Walks of the finished cells run
alongside it; no fix lands until the run phase ends.

Driver: `python3 suite/cycle_run.py --start <n>` · log `docs/audits/cycle-run.log`

### Cells

| # | task | model | score | Δ pts | min | calls | what happened |
|---:|---|---|---:|---:|---:|---:|---|
| 1 | shipping-rates-rb | gemma4 | 20% | −80 | 17 | 68 | chose a dead gem. `eu_countries` 0.0.2 (2014) opens with `require "iso3166"`, an entry point gone from modern `countries`, so `require 'eu_countries'` raises LoadError and the four checks that load the library all die on it. The fifth only reads the README. **The gate did not fail here** — five gates fired and every one got the real LoadError back; both completion gates refused the model's `task_complete`. The run was killed by a 167 KB briefing prompt the server rejected twelve times |
| 2 | shipping-rates-rb | qwen35 | **100%** | +40 | 8 | 92 | |
| 3 | shipping-rates-rb | ternary-bonsai | 80% | 0 | 16 | 52 | |
| 4 | shipping-rates-rb | nemotron-elastic | 0% | 0 | 16 | 57 | |
| 5 | cart-billing-go | gemma4 | **100%** | +40 | 7 | 36 | |
| 6 | cart-billing-go | qwen35 | **100%** | +20 | 10 | 80 | |
| 7 | cart-billing-go | ternary-bonsai | **100%** | +100 | 16 | 54 | |
| 8 | cart-billing-go | nemotron-elastic | 0% | −20 | 16 | 51 | cria's own spilled fetch, saved as `…decimal.go` inside the workspace, was compiled by `go build ./...` — all five checks died on it |
| 9 | orders-api-py | gemma4 | **100%** | 0 | 21 | 71 | |
| 10 | orders-api-py | qwen35 | 50% | −25 | 29 | 131 | model defect, reproduced: its `init()` runs `CREATE TABLE IF NOT EXISTS` (a no-op on the pre-migration database the checker supplies) then `UPDATE orders SET status=…` on a column that was never added — service exits 1, two checks die with it |
| 11 | orders-api-py | ternary-bonsai | 50% | −25 | 47 | 92 | killed at 45 min for sitting below the floor. Scored 2 at the 15-, 30- and 45-minute marks and never moved. The route answers 200 but the body carries neither the items nor the total, and eleven of its own tests fail. The stuck detector fired three times and changed nothing — walk running |
| 12 | orders-api-py | nemotron-elastic | 50% | −25 | 46 | 175 | same signature as cell 11: score frozen at 2 across all three milestones, killed at the 45-minute floor. `GET /customers/alice/orders` did not answer at all (status 0) and three of its own tests fail. Five oversize refusals in the same 8,935–10,103 byte band |
| 13 | feed-pipeline-java | gemma4 | 0% | −80 | 16 | 54 | its rewrite of `Importer.java` dropped the seed's first line, `package pipeline;`. The file still compiles — javac puts it in the default package — so nothing complained, and the checker's `import pipeline.Importer` then found nothing. All five checks died on one missing line; killed at the 15-minute floor. Walk running |
| 14 | feed-pipeline-java | qwen35 | 40% | −60 | 46 | 371 | fast and wrong. It hit **29.9× against a 4.0× bar** and lost the point anyway because the totals no longer match the seed's. The quoted-comma row is mis-parsed despite declaring `opencsv`, and no REVIEW.md was written in 371 calls — the cheapest point on the board. Five more oversize refusals in the same band. Walk running in three parts |
| 15 | feed-pipeline-java | ternary-bonsai | 0% | 0 | 16 | 46 | never compiled. `mvn compile` failed and stayed failed; killed at the 15-minute floor with one gate fired. Flat against last cycle, which was also 0% |
| 16 | feed-pipeline-java | nemotron-elastic | 0% | 0 | 16 | 66 | never compiled either. One near-miss: it *did* write REVIEW.md — 419 words — but with zero located findings, and the prompt asks for a file name and line number on every issue. Flat against last cycle |
| 17 | handles-cli-node | gemma4 | 75% | **+75** | 4 | 26 | biggest gain of the cycle, and the fastest cell yet — 26 calls, three and a half minutes. The p4 prompt fix landed: the CLI now prints address, holder and count, which is exactly what the checker asked for and the old wording did not. Only `tests_incl_live` failed — its tests pass with the network blocked, so they are mocked, not live |
| 18 | handles-cli-node | qwen35 | **100%** | +50 | 24 | 202 | all four green, including the live test — `npm test` passes with the network and fails without it, which is exactly the property the check is asking for |
| 19 | handles-cli-node | ternary-bonsai | **100%** | +50 | 9 | 32 | all four green in 32 calls, live test included. One rumination abort, one gate, nothing else needed |
| 20 | handles-cli-node | nemotron-elastic | 25% | 0 | 8 | 41 | half a migration: it took `request` out of `package.json` and left the `require` in the source, so the program cannot start — `node lookup.js goose` exits 1. It then **stopped on its own** at 41 calls with three checks failing, which is the part that is cria's. Walk running |
| 21 | rust-toml-cli | gemma4 | **100%** | 0 | 14 | 73 | all four green — clean build, 3/3 lookups, the error contract, tests and README. Held its perfect score from last cycle |
| 22 | rust-toml-cli | qwen35 | **100%** | 0 | 19 | 153 | all four green, held from last cycle. Heavily assisted — 5 periodic gates, 4 wheel-spin steers, 3 litter sweeps, one dictated steer dropped — and still landed |
| 23 | rust-toml-cli | ternary-bonsai | 0% | 0 | 16 | 42 | never built — `E0308`, two type errors, killed at the 15-minute floor. **Two gates ran and not one `⟦ctx:checks⟧` block reached the model**, on a run whose whole problem was a compile error. Three oversize refusals at 10,102–10,104 bytes sit where those results should be. Sixth cell showing that bug |
| 24 | rust-toml-cli | nemotron-elastic | 0% | 0 | 16 | 57 | never built either — four errors, `E0277`/`E0599`. Five rumination aborts. Flat |

Δ is percentage points against the previous run of the same cell, whatever prompt revision it was
earned against. Run ids are on the rows in `suite/results/results.jsonl`.

### The assists, measured against the plain proxy

Better in 7 cells, worse in 3, level in 14. **Net +145 points.** The three own-goals are the fix
phase's priority, above any cell that is merely low:

| cell | BASE | CRIA | Δ | cause, from the walk |
|---|---:|---:|---:|---|
| feed-pipeline-java × gemma4 | 80% | 0% | **−80** | a wheel-spin steer fired on a build that had just gone green; the rewrite it prompted dropped `package pipeline;` |
| shipping-rates-rb × nemotron | 60% | 0% | **−60** | 57 calls, two writes, both the same Gemfile. 26 calls hunting a gem already installed, 13 re-running a check cria said it could not parse, 12 on cria's own judges |
| shipping-rates-rb × gemma4 | 40% | 20% | **−20** | the dead-gem chain |

Caveat stated rather than buried: the BASE rows were earned earlier on an older code state, so this
is two code states, not a controlled A/B. A −60 and a −80 are not noise, and every cause here is
read from the captures rather than inferred from the delta.

### Verdict on the fixes landed BEFORE this cycle

Two different questions get confused here, so both are answered separately.

**Question 1 — were the fixes we landed worth it?** Three clear keepers, three that need correcting,
three that should be examined for removal. Nothing to revert.

| fix | verdict | what the walks saw |
|---|---|---|
| reasoning logged on unfinished streams | **KEEP — for observability, not for score** | counted across the walk sections: 6 clear "helped", 4 "did not fire", 6 ambiguous. And every "helped" means it made the WALK possible, not that it moved a run. It is the reason a dozen findings in this document exist. One gap: a killed run still loses its last reasoning |
| rumination rate change | **KEEP — on the readings, not the counts** | abort RATE went **down on 5 cells and up on 4**, including `rust-toml-cli × nemotron` 0/76 → 5/57. The case for keeping it is that where a walk actually read the aborts they were right 5/5 (Rust) and 4/4 (Ruby) — a reading, not a tally |
| the p4 task-prompt corrections | **KEEP — but it is a repair, not an advance** | the +75/+50/+50 are real deltas against the previous run, and misleading as causation. `handles-cli-node` scored 4/4 and 3/4 under earlier wording; the **p3** revision crashed it to 0/2/2/1; p4 restored it to 3/4/4/1. gemma4 is still below the 4/4 it held before p3 |
| derived probe output cap | **CORRECT IT** | this is rank 1. The intent was right and the arithmetic was wrong: 8,500 per command against a 9,000 bound applied to all the commands at once |
| search inlining | **CORRECT IT** | titles inline was right; the note still ends "the file named above" with no file named above — third cell |
| PATH oracle | **CORRECT IT** | right idea, `bash -lc` should be `-lic`; misses every version manager |
| cheap `mvn compile` probe | **CORRECT IT** | helped early in one cell, reported green over a no-op in two others |
| cached-check age note | **EXAMINE FOR REMOVAL** | counted across the walk sections rather than quoted from one: "never fired" ×5, "fired in form, dated nothing" ×3, "fired, did nothing" ×2, "fired on an empty section" ×1. **Zero positive results anywhere** |
| verdict tool | **EXAMINE** | fired in a minority of chances; once ended a run cleanly, once malformed its own arguments |
| completion-judge report framing | **EXAMINE** | mostly nothing; stopped the model damaging working code once, hurt once |

**Question 2 — are the standing assists worth having?** That is what the control walk asked, and it is
about the machinery that predates this cycle, not the fixes above. Its answer: of every injection in
two winning runs, only the **gate** demonstrably changed the outcome, and only when its report was the
only copy of the finding. The rest confirmed or cost calls. That is an argument for **pruning**, which
principle 1 already says is the safe direction — not for reverting this cycle's work.

### Fix-phase state, cycle 1

Landed and live: the shared gate budget · `-lic` so cria can see `node` · spill files always `.txt` ·
Maven/MSVC diagnostics parse · the live-execution probe honours the project's declared command · the
search note names its file · a killed run keeps its last reasoning · the assists ledger stops
dropping events · **the inbound exec bound deleted** · the XML parameter boundary · four verifiers
made case-forgiving · **cria now observes whether the harness truncates instead of assuming it**.

Built and removed: an exec-output spill (a fourth duplicate of machinery that already existed twice)
and a steer-rename guard (fixed nothing — see below). Two of thirteen were waste.

### REVERTED — the `data/review.md` guard fixed nothing

Built and removed the same day. The walk ranked it "the likely root of `review_written` failing" and
I took that at face value without checking the consequence.

Checked afterwards, in the archived workspace and every prompt of the run:

- no `REVIEW.md`
- no `data/review.md`
- **zero write calls with "review" in the path, across all 371 calls**

The coder never wrote a review file anywhere, so the path cria named made no difference to the
score. A guard against a rename that never happened.

**The real reason that check failed:** in 371 calls and 46 minutes the coder never spent one call on
a deliverable worth 20 points that needed sixty words and no build. cria noticed four times and said
nothing (below), and the one time it did mention the file it was inside a steer about threading.

Same mistake as the 9,000-byte story: repeating a walk's attribution without testing whether the
thing it blamed actually caused the outcome. The walks find real bytes; their causal claims are
candidates.

### SURFACED — c1-13 is a deliberate decision, not a bug

The walk found four completion verdicts that each named the missing deliverable ("Create REVIEW.md")
and said none reached the coder. Verified: zero coder prompts in that run carried a completion nudge,
no "Proposed fix" line, no mention of REVIEW.md in any steer.

The cause is one line, and it is on purpose — `loop.py::_periodic_satisfaction`:

```python
if not satisfied:
    return None   # do NOT steer — the reason is judgment, not ground truth. Log only.
```

The periodic satisfaction check may only END a session, never steer it. The asymmetry with the
done-claim path (which DOES steer with the critic's reason) is the point: a done-claim is an anomaly
the coder created, a timer is not, and steering off a timer is noise on a clock — #3 and #11.

**Not changed.** Reversing it would be exactly the class of revert the operator has asked me to
surface instead of doing. What it costs is on the record now: a judge computed the exact unmet
deliverable four times in one run and the coder never heard any of it, on a task where that
deliverable was the cheapest point on the board — sixty words and two line numbers, no build needed.

The question for the operator is whether a NOT-satisfied verdict that names a **specific missing
deliverable** is still "judgment" in the sense that rule meant, or whether that is ground truth of a
kind the timer objection does not cover.

### Findings ledger — cycle 1

Seeded from work already done; the walk phase appends to it.

| rank | tier | finding | state | closed by |
|---:|---|---|---|---|
| 1 | 1 | **cria discards its own gate output and then reports the checks GREEN.** Verified cold: 8 discards over the bound, then 19× "the repo's own checks reported no error-class problems" and 8× "the repo's automated checks pass" — while pytest was red and the route returned nothing. A fail-open on missing ground truth (#13), stated as fact (#5b). Same bound as the two below | open | |
| 2 | 1 | **`mvn -q compile` prints 9,390 bytes and the bound is 9,000** — so every Maven run in a whole session was discarded, 15 of them. The model saw its 18 compile errors once, by accident, when it happened to use bare `javac`. The fix is to REDUCE oversized results through `content_reduce`, which already owns lossless head+tail, instead of discarding them | open | |
| 2c | 1 | **`task_complete` is folded into the previous write's content**, so `validate-before-lower` refused a `pom.xml` write 12 times for malformed XML at the line where cria's own junk starts. 14 calls lost | open | |
| 2d | 2 | **the assists ledger undercounts and I quoted it.** 6 steers and 30 gate-carrying prompts recorded as 0 steers and 2 gates. Every "cria intervened N times" from `assists` is a floor, not a count (#12) | open | |
| 3 | 1 | **The same number closes two more doors.** It refuses cria's own joined gate output, and it refuses the coder reading its own source. `Importer.java` at 9,889 bytes was unreadable by every route from call 0068 to the kill; the model said "389 lines, which is not that large" and ended up web-searching a `file://` URL to see its own code. Found independently by three readers who could not see each other's ranges | open | |
| 2 | 1 | **cria named the wrong file for a deliverable** — steer 0109 says "create `data/review.md`"; the task and `verify.py:190` want `REVIEW.md`. One check lost to a filename, and the steer author is forbidden from choosing files at all | open | |
| 3 | 1 | **cria cannot see `node`, so JavaScript had no syntax floor and no execution all cycle.** `toolpath` probes with `bash -lc`; nvm installs into `.bashrc`, which a non-interactive shell never sources. Verified cold: `-lc` finds nothing, `-lic` finds it. My own Tier 1 fix, half-built — the same hole hits rbenv, pyenv, nodenv, sdkman, asdf | open | |
| 4 | 1 | **cria's gate is not read-only.** Its only route to ground truth is the project's own test runner, and these tests POST over real HTTP — the workspace database ended with 53 orders in it. The failing count the model was chasing climbed 3 → 22 because cria kept moving it. Verified cold | open | |
| 5 | 1 | **the live-execution probe refuses to run the thing.** It fires and then declines with `X is not an entry point on disk` — in 6 of 24 cells. `pytest` is a program not a file; `pipeline.Importer` is a class path; `lookup.js` was 611 bytes and present. `exec-intent` asks the project how it runs, gets a true answer, and a file-existence test on the wrong token throws it away | open | |
| 5b | 2 | **a killed run loses its last reasoning.** `rust-toml-cli × ternary` call 0043 has a prompt and a body and no `.reasoning.txt` — the suite's kill terminates the process before the `finally` runs. The operator asked for all streamed reasoning logged whether it finishes or not; the fix covered stream errors and exceptions, not process death. Write it incrementally as it streams | open | |
| 5c | 1 | **(superseded framing) no probe ever starts the thing and asks it something.** Three cells now point at this from different directions: the migration branch the Python task is about was never executed by anything cria ran, the Java entry point was never invoked, and the Node CLI was never started. cria's probes are syntax linters plus the coder's own tests | open | |
| 6 | 1 | **a purposeful reasoner call with no output path.** The search supervisor returned `on_target: false` and a better query; `_add_note` wrote it to the `⟦cria⟧` display channel, which is stripped before the model. "off-target" appears zero times in the whole run — cria paid for the judgement and threw it away | open | |
| 7 | 1 | **cria refuses its own gate's output.** A per-probe cap of 8,500 and a per-result bound of 9,000, with a gate that joins several probes into one result — so an ordinary 231-line pytest run is discarded whole and the coder is told to re-run a command cria wrote. 21 refusals across 7 of the 24 cells; one of them was the coder's own failing test suite | open | |
| 8 | 1 | the Ruby task cannot be passed honestly: the prompt demands a third-party gem, the verifier only sees ruby's default load path, and cria correctly refuses any install that reaches it. The passes came from a gem left on the box on 2026-08-08 (`docs/audits/cycle-1-walk.md`, cross-run section) | open | |
| 9 | 1 | cria's install refusal prescribes the command to run, and on this box that command is the losing one — off the load path, and 900 files into the workspace | open | |
| 10 | 1 | the briefing prompt shipped at 167 KB against a 48 K window and the server refused it 12 times; 46% of it was the gem tree cria told the coder to create. `vendor` is deliberately excluded from the build-artifact skip set — **a documented earlier decision, do not revert without surfacing** | open | |
| 11 | 1 | the Java seed ships tracked `.class` files at exactly the path the checker imports from, so a workspace can look correct while the source is not. Task fault | open | |
| 12 | 2 | the gate's litter sweep deletes untracked build output — correct as "clean up my own probe", wrong as "leave the workspace as I found it", and it removes the one artifact that shows where the build put things | open | |
| 13 | 2 | the search note ends "in the file named above" and, on the inline path, nothing above names a file. Self-inflicted by the search-inlining change (#5b) | open | |
| 2b | 1 | spilled fetch keeps the URL's extension inside the workspace (`cria/webfetch.py:267`) — **ablation proves it**: verifier says FAIL with `tmp/` present, `ok` after `rm -rf tmp`. Cheapest fix in the ledger | open — first in the fix phase | |
| — | 1 | steer author's free-prose contract (`_steer_or_none`) | open — deferred at 0.1% prevalence, needs its own pass | |
| — | 3 | cria's story of what happened ≠ cria's own record (5 sites) | open | |
| — | 3 | word-matching decides when to interrupt | open — needs prevalence first | |
| — | 3 | a refusal that leaves no way forward | open | |
| — | 3 | calls the model made that never happened | open | |

Ranks are assigned in the rank phase, once the walk has said how many cells each one cost.

### Watching, not yet concluded

- **A dropped declaration is silent in some languages and impossible in others.** Cell 13 lost
  `package pipeline;` in a rewrite and scored 0%. Measured across every Java and Go workspace on
  disk: 1 of 17 files, one run. Go never loses it because Go refuses to compile a file without one;
  Java accepts the default package without a murmur. So the exposure is real but narrow, the cost
  when it lands is the whole cell, and the bar to ADD a guard is high (#1). The rank phase decides.

- **The rumination rate change.** Aborts on the cells that have run under it are mostly down —
  `orders-api-py × nemotron` 15/200 → 7/175, `cart-billing-go × nemotron` 6/124 → 2/51,
  `orders-api-py × qwen35` 4/260 → 1/131 — and up on one, `shipping-rates-rb × nemotron` 3/77 → 4/57.
  That is roughly what it was built to do. The four `feed-pipeline-java` cells are the real test and
  they have not run yet this cycle; the 11-aborts-in-35-calls figure on that task predates the change
  and says nothing about it.
- **Aborts cluster on one model, but they are not what sinks it.** nemotron-elastic this cycle:
  0% / 0% / 50% / 0% / 25%, with aborts of 4 / 2 / 7 / 1 / 0. Its best cell had seven aborts and its
  25% cell had none, so the guard is not the driver. What the five have in common is that four were
  killed at a milestone floor. That is the question worth reading, and it is now being read.

### The 9,000-byte bound: its justification does not reproduce

Asked for an example of something cria returned that the harness cut. **I could not produce one, and
I looked properly.**

What the bound claims (`content_reduce.INLINE_RESULT_MAX_BYTES`): Codex truncates every tool result
in its history at 10,000 bytes, so anything cria hands back above that is silently middle-cut in
every later prompt.

What is verifiable today:

| claim | check | result |
|---|---|---|
| the harness really has that policy | read the Rust | **TRUE** — `TruncationPolicyConfig::bytes(10_000)`, `models-manager/src/model_info.rs:83`, the production fallback profile for local models |
| the marker appears in cria's prompts | grep 50 sessions, both forms (`…N chars truncated…`, `…N tokens truncated…`) | **zero** |
| large results get cut on cria's path | find the largest tool result cria actually sent upstream | **160,447 bytes, uncut** — sixteen times the supposed limit |
| the cited evidence run | look for `1785893473` | **gone** — deleted in the housekeeping of 2026-08-13 |

So the policy exists in the harness's source and is **not observably operating on the path cria
uses**. A 160 KB tool result reached the model through cria intact.

Against that, the bound's measured cost this cycle: 24% of all command results discarded (1,179
sampled, p75 = 8,424), the gate blinded in 7 of 24 cells, a model unable to read its own 389-line
source file by any route, and the chain that cost `cart-billing-go × nemotron-elastic` every check.

**What would change this conclusion:** if the harness applies the policy only when rendering its own
history to its own model — a path cria never sees, because cria captures what cria sends. That is
plausible and it is exactly what needs testing before the number moves. Until then the bound is
guarding a mechanism nobody can currently demonstrate, at a cost everybody can.

**Operator's call.** Discovering the limit from the harness rather than hardcoding it is the only
version that satisfies principle 18 either way.

### Environment notes — established, deliberately NOT changed mid-cycle

- **A foreign server owns port 8081 on this box, and it answered the Python task's requests.**
  Confirmed live: `uvicorn` pid 479454, `app.compaction_main:app --host 127.0.0.1 --port 8081`, from
  `/home/jesse/src/coding-agent-router`, started 2026-08-13 23:21 — during the campaign. In
  `orders-api-py × nemotron-elastic` the model tried four times to start its own service (calls 0123,
  0148, 0166, 0172) and never bound once; every 404 it then chased came from that server. The final
  score is still honest, because `verify.py` starts the service on a port it chooses itself — but the
  model could not test its own work for the whole run.
  **This is the operator's process and the operator's call. Not touched.**
  Backlog entry 30 recorded this exact collision in an earlier campaign and filed it `nothing-to-fix,
  1 occurrence`. That judgement was wrong and the entry is re-opened.

- **Java is NOT blocked by its environment — checked directly.** The seed compiles clean out of the
  box, offline (`mvn -o compile`) and online. A third-party CSV dependency added to the `pom.xml`
  resolves and downloads (commons-csv 1.10.0, plus six versions already in `~/.m2` from earlier
  runs). So the task's mandatory "use a third-party Java CSV library" is satisfiable, and the three
  `mvn compile failed` cells are the models' own broken code plus the cria faults the walks found —
  not a wall like Ruby's. The cached `.m2` artifacts are contamination of the same shape as the Ruby
  gem but benign: the `pom.xml` must still declare the dependency and that declaration is what the
  checker reads.

- **`bundle` is not on this box's PATH.** Debian ships the binaries as `bundle3.2` / `bundler3.2`
  and nothing provides the unversioned name, so `bundle install` and `bundle exec` both answer
  "command not found" — for every model, on every Ruby run. The models fall back to `gem install`,
  which ignores the Gemfile's resolution and installs the newest transitive dependencies, which is
  how a 2014 gem ends up paired with a 2024 one that no longer exports what it requires.
- **It is a hazard, not a blocker.** `shipping-rates-rb`'s verifier runs bare `ruby -Ilib`, so the
  intended solution never needed bundler: `gem install countries` puts the gem on the default load
  path and `require "countries"` just works. Three runs prove it — every Ruby run that chose
  `countries` scored 60–100%, and both runs that chose `eu_countries` collapsed.
- **So the environment stays as it is.** Installing the binstub mid-campaign would change what is
  being measured and invalidate every Ruby row. What the walk has to answer instead is what cria
  told the model when `bundle` failed, and why nothing caught a library that could not load.

### Log

- **2026-08-14 02:45 → 07:33** — nothing. The run phase closed and the walk phase did not start.
  The per-cell watcher had been the heartbeat all night; when the last cell landed it fired for the
  last time, and the turn that closed the run phase ended on "continuing now" without launching
  anything. Five hours idle, found only because the operator asked. Rule added to the goal doc:
  never end a turn on an intention — have work in flight or say there is none.

- **2026-08-13** — cycle 1 run phase resumed at cell 9 after a driver-imposed `timeout 3000` killed
  `orders-api-py × gemma4` at 52 minutes of its own 60-minute wall. The cap is gone; the suite owns
  the only wall clock. The rerun finished in 21 minutes at 100%.
- **2026-08-13** — the campaign driver moved out of a session scratchpad into `suite/cycle_run.py`
  so a lost terminal cannot lose the loop.
- **2026-08-13** — the goal docs moved to `docs/goals/` and the port-fidelity audit to
  `docs/audits/`; every reference in `docs/` and `suite/` was repointed. Three comments under
  `cria/` still name the old path (`cria/loop.py:1757`, `cria/loop.py:3952`,
  `cria/probediscovery.py:854`). They are inert text and they wait for the fix phase — one code
  state per cycle applies to a comment as much as to a line that runs.
