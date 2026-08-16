# The 100% goal — run, walk, rank, fix, repeat

**Every cell at 100%.** Twenty-four cells: four models against six tasks, one language each, cria driving. Not a delta, not a lead over the baseline, not "better than last cycle" — 100% in all twenty-four. A cycle that improves nine cells and leaves fifteen short has finished a cycle, not the job.

Read `docs/principles.md` first and keep it open. Everything below is downstream of it.

## The cycle

```
RUN  →  WALK  →  RANK  →  FIX  →  RUN  →  WALK  →  RANK  →  FIX  →  …
```

Four phases, in order, until every cell reads 100%. There is no fifth phase where the work pauses to ask whether to continue.

**One code state per cycle.** Nothing under `cria/` or `cria/prompts/` changes during a run phase — prompts load from disk on every call, so an edit changes the RUNNING system and voids every cell after it. Fixes land in the fix phase, together, and `cria.service` restarts before the next run.

## Status lives in files, never in a message

**`docs/audits/hundred-progress.md` is the status.** Cycle number, phase, the 24-cell table with deltas, the ranked ledger, and a dated log. Update it **as each cell lands and as each fix lands** — not in a batch at the end of a phase. Someone following along reads that file.

| file | holds | written by |
|---|---|---|
| `docs/audits/battery-report.md` | the score grid | `suite/run.py`, automatically |
| `docs/audits/cycle-<N>-walk.md` | raw walk findings, one `## <run_id>` per run | the walk agents |
| `docs/audits/context-footgun-backlog.md` | the ranked backlog across all cycles | the rank phase |

---

## Phase 1 — RUN

```
python3 suite/cycle_run.py              # all 24 cells, ~8 h
python3 suite/cycle_run.py --start 12   # resume after a kill
```

One cell at a time, task-major. The driver sets the arm, restarts cria, runs the cell, restores the flag. **It imposes no wall clock of its own** — the suite already owns one, 15 minutes per deliverable from each task's `meta.toml`, and a second one on top only kills the long cells.

**Before the first cell, check the environment is clean.** Contamination has cost this campaign more than any cria bug:

```
python3 -c "import sys; sys.path.insert(0,'suite'); import run as R; print(sorted(R.user_install_listing()))"
git status --short suite/tasks
```

A leaked user-level package means a model can score points for work it did not do — four Ruby rows were inflated for weeks by one gem. A dirty `suite/tasks` means a verifier is writing into the repo. Both are blockers, not notes.

**Report each cell as it lands**, in chat: score, delta, and the one-line cause of anything that failed. Do not sit on a finished cell.

A cell that dies with no row is re-run at the end of the cycle before the walk starts. A missing row is not a zero; it is missing evidence.

## Phase 2 — WALK

Follow `docs/walk-prompt.md`. Up to **40 agents**, reading line by line. A walk is reading every call in a run from first to last — the whole prompt cria sent and the whole reasoning it produced (rule 23b). Not a grep, not a sample.

```
python3 suite/walk.py <session> --out /tmp/walk-c<N>/<run_id>
python3 suite/reasoner_audit.py <session> --bad
```

One agent per run under ~80 calls, two for the bigger ones split head and tail, extra agents to the worst-scoring cells. Every chunk gets read, including any marked `OVERSIZED`. An agent that ran out of room says so rather than implying it finished.

What they hunt, in order: **a false fact cria stated** (#5b) · **an assist the model visibly followed somewhere worse** (#1) · **last cycle's fixes** — did each behave, and did any cause something new · **what the model did on its own**, recorded under its own heading, because the target is still 100% and the question becomes what in the context would have let it catch its own mistake.

Findings go to `docs/audits/cycle-<N>-walk.md` under `## <run_id>`, each with a `cria fault: yes | none` line and the call number and quoted bytes that prove it. **Assume cria caused it until proven otherwise** (#16).

### A walk finding is a CANDIDATE, not a fact

This is the phase's hardest rule and it has been broken repeatedly, at real cost.

- A walk that says "X is the likely root of Y" has established that X **exists**, not that it caused Y. Those are different checks and confirming the first is not confirming the second.
- Before acting: **run the experiment that could refute it.** Hide the leaked gem and re-score. Delete the suspect directory and re-run the verifier. Execute the function and print what it returns.
- If the finding is wrong, **say so and stop.** A refutation is a result. Two of this project's best findings came from disproving a reported one — the Ruby task is satisfiable (and the real problem is four contaminated scores), and the Java `.class` files are inert (and the real problem is a verifier writing into the repo).

## Phase 3 — RANK

One list, most problematic and most effective to fix at the top. Rank on: how many cells it cost, whether it broke working code, whether it is a false fact, how many models and languages it reached, and how cheap the real fix is. A finding seen once in one language ranks below one seen four times across three.

Fold it into `docs/audits/context-footgun-backlog.md` — the standing backlog, not a new file each cycle. New entries carry a `(c<N>)` tag. Existing entries get re-ranked against the new evidence: one that keeps appearing rises, one unseen for two cycles gets a line saying so. Fixed entries move to `## Fixed` with the commit sha. Then tier them: **1** broke working code or killed runs, **2** lost checks, **3** wasted time, **4** recorded but not scheduled.

## Phase 4 — FIX

Take the tiers in order. Every item goes through the same six questions.

1. **Why does the code behave this way?** Find the commit (`git log -S`, `git blame`) and read its message and comments. This repo records its incidents in both; the answer is usually written down.
   **Do not skip to what to change.** "A leads to B" means look at A, not force B.
2. **Is that reason still true?** A guard built for a real incident may be obsolete, or may be the only thing preventing that incident's return.
3. **State the A → B → C chain** in plain words, and fix at A. If you cannot, say why, then give the fix at B.
4. **Check it against `docs/principles.md` by number.** Additive is not sufficient on its own (#2's corollary). cria never truncates, for any reader — only de-dup and model-made summary are allowed (#5). A rule you are tuning against real sentences should have been a question (#9's corollary).
5. **Check it is not reverting a previous intent.** Read the surrounding code, its docstring, its test docstring, and the git history of the lines you are about to change. If it undoes a deliberate earlier decision, **surface it and stop on that item.**
6. **Measure prevalence before building anything that fires on a pattern** (#15), in the real captures under `~/.cria/calls`. Below the bar → record it, do not build it.

Then: a test that fails before and passes after, named for the behaviour, with the incident in its docstring. `python3 -m pytest` green. Commit and push per item. Restart `cria.service`. Mark it `landed` with its sha and move it to `## Fixed`.

**The safe direction is REMOVE (#1).** A fix phase that deletes an assist shown to mislead beats one that adds three. Ask what can be deleted before what can be extracted.

Anything left unfixed stays `open` and gets re-ranked next cycle, with the reason.

---

## Rules that do not bend

- **`docs/audits/hundred-progress.md` is the status.**
- **One code state per cycle.** No `cria/` edits while a run is in flight.
- **Never end a turn on an intention.** Finish with work done or work actually running. Saying what you are about to do and then stopping has cost this project whole nights.
- **Verify before you assert.** A string that exists is not a cause. State how you checked.
- **Never edit `suite/tasks/*/prompt.txt`** without the operator. If wording does change, bump `PROMPT_REV` in `suite/battery_run.py` and say what changed and why.
- **A verifier change invalidates every row scored against it.** Mark them `{"superseded": "<what changed and why>"}` and re-run them.
- **Never make a task easier to pass.** The failure mode is a verifier tuned until the models look good. If a task is genuinely too hard for every model, that is a finding.
- **Scoring must not dirty the repo.** `git status --short suite/tasks` is clean after a run, or a verifier is writing where it runs.
- **Never delete run evidence.** Annotate rows; keep the captures. A question asked later needs them, and the run that would have settled the 9,000-byte bound had already been deleted.
- **Never end a session to a human** (#14). No off-ramps, no "should I continue".
- **Plain language in chat.** The verdict and the cause. Detail goes in the docs.
