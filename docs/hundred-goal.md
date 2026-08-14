# The 100% goal — run, walk, rank, fix, repeat

**The target is every cell at 100%.** Twenty-four cells: four models against six tasks, one
language each, cria driving. Not a delta, not a lead over the baseline, not "better than last
cycle" — 100% in all twenty-four. A cycle that improves nine cells and leaves fifteen short has not
finished the job, it has finished a cycle.

Read `docs/principles.md` first and keep it open. Everything below is downstream of it.

## The cycle

```
RUN  →  WALK  →  RANK  →  FIX  →  RUN  →  WALK  →  RANK  →  FIX  →  …
```

Four phases, in order, forever, until every cell reads 100%. There is no fifth phase where the work
pauses to ask whether to continue. When the fix phase lands its last commit, the next run phase
starts.

**One code state per cycle.** Nothing under `cria/` or `cria/prompts/` changes during a run phase —
prompts load from disk on every call, so an edit changes the RUNNING system and voids every cell
after it. All fixes land in the fix phase, all at once, and `cria.service` restarts before the next
run phase begins.

## Where the status lives

**`docs/audits/hundred-progress.md` is the status. Not chat, not memory, not an intention.**

It carries, always current:

- the cycle number and which of the four phases is running
- the 24-cell checklist for this cycle: run_id, score, delta against the previous cycle, and one
  plain sentence of what happened
- the findings ledger for this cycle: each finding's rank, tier, state (`open` / `fixing` /
  `landed` / `rejected`), and the commit that closed it
- a dated log line for anything an operator following along would want to know

Update it **as each cell lands** and **as each fix lands** — not in a batch at the end of a phase.
The operator reads this file to follow the work in progress; a file written at the end of a phase
tells them nothing while the phase is running.

Three other files are part of the record and are not duplicated into the progress file:

| file | what it holds | who writes it |
|---|---|---|
| `docs/audits/battery-report.md` | the score grid with per-cell deltas | `suite/run.py`, automatically |
| `docs/audits/cycle-<N>-walk.md` | the raw walk findings, one `## <run_id>` section per run | the walk agents |
| `docs/audits/context-footgun-backlog.md` | the ranked backlog across all cycles | the rank phase |

---

## Phase 1 — RUN

```
python3 suite/cycle_run.py              # all 24 cells
python3 suite/cycle_run.py --start 12   # resume after a kill
```

One cell at a time, task-major, roughly eight hours of GPU. The driver sets the arm, restarts cria,
runs the cell, and puts the flag back. It imposes **no wall clock of its own** — the suite already
owns one, 15 minutes per deliverable read from the task's `meta.toml`, and a second one on top only
kills the long cells.

**Report each cell as it lands**, in chat, in the operator's format: score, the delta, and the
one-line cause of anything that failed. Do not sit on a finished cell waiting for the next one.

If a cell fails in a way that is obviously cria's doing and obviously cheap, it still waits for the
fix phase. One code state per cycle.

A cell that dies with no row — killed, crashed, no archive — is re-run at the end of the cycle
before the walk starts. A missing row is not a zero; it is missing evidence, and the walk needs it.

## Phase 2 — WALK

Follow `docs/walk-prompt.md`. Up to **40 agents**, reading line by line, no grep, no sampling, no
digest. Rule 23b: a walk is reading every call in a run from first to last, the whole prompt cria
sent and the whole reasoning it produced.

Materialize each run first — this is the only permitted way, and it never truncates:

```
python3 suite/walk.py <session> --out /tmp/walk-c<N>/<run_id>
python3 suite/reasoner_audit.py <session> --bad
```

Allocate the 40 agents across the 24 runs by size: one agent per run under roughly 80 calls, two
for the bigger ones split head and tail, and give the extra agents to the worst-scoring cells.
Every chunk gets read, including any marked `OVERSIZED`. An agent that ran out of room says so in
its section rather than implying it finished.

What the agents are looking for, in this order:

1. **A false fact cria stated** (#5b) — a claim in cria's own voice that the world contradicts.
   These are the highest-value findings in the project and they are always cria's.
2. **An assist that misled** (#1) — an injection the model visibly followed into a worse place.
   The evidence is in the model's thinking, which is why the thinking gets read line by line too.
3. **The last cycle's fixes** — did each one behave as designed, and did any of them cause
   something new? A fix that fired correctly and a fix that never fired are different results and
   both get written down.
4. **What the model did on its own** — a genuine model defect is a real finding, recorded under
   its own heading. It is not an excuse: the goal is still 100%, and the question becomes what in
   the context would have let that model catch its own mistake.

Each agent writes its findings into `docs/audits/cycle-<N>-walk.md` under `## <run_id>`, with a
`cria fault: yes | none` line per finding and the call number and quoted bytes that prove it.
**Assume cria caused it until proven otherwise** (#16).

## Phase 3 — RANK

One ranked list, most problematic and most effective to fix at the top. "Most problematic" and
"most effective to fix" are two axes and they usually agree; where they disagree, say so and rank
by what unblocks the most cells.

Rank on: how many cells it cost, whether it broke working code, whether it is a false fact, how
many models and languages it reached, and how cheap the real fix is. A finding seen once in one
language, on one model, ranks below one seen four times across three.

Fold the ranked list into `docs/audits/context-footgun-backlog.md` — the standing backlog, not a
new file each cycle. New entries carry a `(c<N>)` tag. Entries already there get re-ranked against
the new evidence: a finding that keeps appearing rises, and one that has not been seen for two
cycles gets a line saying so. Fixed entries move to `## Fixed` with the commit sha.

Then split it into tiers, same as before: **Tier 1** broke working code or killed runs, **Tier 2**
lost checks, **Tier 3** wasted time, **Tier 4** one-offs recorded but not scheduled.

## Phase 4 — FIX

Take the tiers in order and put every item through the same process:

1. **State the A → B → C chain in plain words.** `A` leads to `B` which causes `C` to break.
2. **Can it be fixed at A?** If yes, fix it at A. If no, say why not, then say what the fix at B
   is. Never fix at B while A is reachable.
3. **Check it against `docs/principles.md`** by number. An assist that is merely additive is not
   thereby allowed (#2's corollary). Bounding a prompt cria composed is not truncation (#5's
   counter-nuance). A rule you are tuning against real sentences should have been a question (#9's
   corollary).
4. **Check it is not reverting a previous intent.** Read the surrounding code, its docstring, its
   test docstring and the git history of the lines you are about to change. If the change undoes a
   deliberate earlier decision, **surface it to the operator and stop on that item** — this has
   happened repeatedly and it is worse than leaving the bug.
5. **Measure prevalence before building anything that fires on a pattern** (#15). Count it in the
   real captures under `~/.cria/calls`. A finding below the bar is recorded and not built.
6. **A test that fails before and passes after**, named for the behavior, with the incident in its
   docstring. `python3 -m pytest` green.
7. **Commit and push per item.** Then restart `cria.service`.
8. Mark it `landed` in the progress file with its sha, and move it to `## Fixed` in the backlog.

The safe direction is REMOVE (#1). A cycle whose fix phase deletes an assist that has been shown to
mislead is a better cycle than one that adds three.

Items reaching the end of the phase unfixed stay `open` in the backlog and get re-ranked next
cycle. Do not carry a silent backlog: anything deliberately deferred says so, with the reason.

---

## Rules that do not bend

- **`docs/audits/hundred-progress.md` is the status.** Whatever it says is what has happened.
- **One code state per cycle.** No `cria/` edits while a run phase is in flight.
- **Never edit `suite/tasks/*/prompt.txt`.** Propose the wording to the operator and wait. If a
  prompt does change, bump `PROMPT_REV` in `suite/battery_run.py` and say what changed and why.
- **A verifier change invalidates every row scored against it.** Mark them
  `{"superseded": "<what changed and why>"}` and re-run them.
- **Never make a task easier to pass.** The failure mode to avoid is a verifier tuned until the
  models look good. If a task is genuinely too hard for every model, that is a finding.
- **Never special-case cria for a task.** A task exposing a cria bug is the campaign working.
- **Never delete run evidence.** Annotate rows; keep the captures.
- **Never end a session to a human** (#14). No off-ramps, no "should I continue", no ceiling.
- **Plain language in chat.** The verdict and the cause. Detail goes in the docs.

## Carried in — the fix phase of cycle 1 starts here

These are already found and already diagnosed. They do not need re-discovering; they need doing.

| # | finding | where | why it matters |
|---|---|---|---|
| — | cria's spilled fetch keeps the URL's file extension, inside the workspace | `cria/webfetch.py:267` `_spill_name` | a fetched `…decimal.go` landed in `./tmp/read-only/`, `go build ./...` compiled cria's own 90 KB copy, and all five Go checks died. Principle #7 twice over: cria wrote into the workspace, and the workspace read it back |
| T1-2 | the steer author writes free prose, and every rule about it is also prose | `cria/loop.py::_steer_or_none` | deferred once at 0.1% measured prevalence; the fix means rewriting the most-measured parser in the repo, so it needs its own pass |
| T3-16 | cria's story of what happened is not what cria's own record says | 5 sites | #12 — surface every metric from the authoritative event |
| T3-17 | word-matching decides when to interrupt | the fire trigger | needs prevalence work before a replacement is built |
| T3-18 | a refusal that leaves no way forward | — | #13 — fail open only toward "keep working" |
| T3-22 | calls the model made that never happened | — | #5b |

Full chains for each are in `docs/audits/context-footgun-backlog.md`.
