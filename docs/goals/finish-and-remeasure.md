# Finish what the walk opened, then re-measure everything

> **RETIRED — operator, 2026-08-19.** Steps 1–3 completed (two plumbing items landed, one refuted; both cells run; both walked). **Steps 4 and 5 are dropped as goals.** The 24-cell pass launched under step 5 is still running to completion and its cells are still being reported one at a time — but finishing it is no longer a goal condition, and nothing is owed at the end of it.
>
> What replaced this document: the BASE/CRIA comparison in [`../audits/base-vs-cria-footgun-patterns.md`](../audits/base-vs-cria-footgun-patterns.md), and the queued changes it produced — remove the repetition steer, take the research step out of the plan items, and re-cut the milestone wall. Everything below is kept for its reasoning, not as instructions.


**The job, in order, and none of it is optional:**

1. Close the three open plumbing items — each needs a specific piece of evidence, named below.
2. Run the two cells that never ran: `shipping-rates-rb × ternary-bonsai` and `shipping-rates-rb × gemma4`.
3. Walk them, line by line.
4. Fix what the walk finds, and re-run, until **both cells read 100%**.
5. Then run the full 24-cell suite and report it against the last one.

Read [`docs/principles.md`](../principles.md) first and keep it open. Everything below is downstream of it. The cycle discipline in [`hundred-goal.md`](hundred-goal.md) — RUN → WALK → RANK → FIX — governs steps 2–5; this document says what is different about *this* pass.

---

## Status lives in a file

**[`docs/audits/finish-and-remeasure-progress.md`](../audits/finish-and-remeasure-progress.md) is the status.** Not a chat message, not this file. Update it as each item lands and as each cell finishes — not batched at the end. Someone following along reads that file and nothing else.

Each entry carries: what it is, what evidence would settle it, what was actually done, and `open` / `landed <sha>` / `refuted`.

---

## Step 1 — the three open items, and the evidence each needs

None of these may be fixed on the strength of a count. **Three sweep findings collapsed in this session and all three were counts used as evidence** (rule 23b: a count is not a reading, a match is not a meaning). Each item below names the reading that would settle it.

### 1a. The periodic step check shares a counter with the gate

`_periodic_step_check` fires on `sess.coder_turns % STEP_CHECK_EVERY` (12). `guard_periodic_gate` sets `coder_turns = 0` when it fires at 15. Two mechanisms, one counter, one of which resets it — the same fragility fixed in `satisfaction_check_due` (`fda715b`..).

**The filed evidence was invalid** and is corrected in the sweep report: "1,147 gate checks against 14 step checks" compares a both-paths counter against a planner-ON-only one, across 405 planner-off runs and 62 planner-on.

**What would settle it:** walk one planner-ON run. Read whether `coder_turns` passes through 12 on a cycle where the check could have fired and didn't. If it does, fix it the same way — measure from when the check last RAN, and do not let a blocked or reset turn consume the opportunity. If it doesn't, write `refuted` and move on.

### 1b. Ecosystem discovery is manifest-only, in every language

`discover()` on `orders-api-py`'s real seed returns **nothing** — and that cell scores 90–100%. So cria's gate has never run a test on the highest-scoring Python cell. PHP is the same, and `handles-php` is live.

This is a coverage gap, not a false fact: with the vacuous-green fix landed, `gate_ran_tests` now correctly reports that no tests ran, so the judge is told about the blindness rather than a fiction.

**What would settle it:** a walked run where the gate's silence is what let a wrong answer through. Adding discovery is an ADDITION (#1 sets a high bar, #15 wants prevalence first), and zero of the recorded gate events found no probes. **Do not build it on the shape alone.**

### 1c. The gate re-runs the suite in the live workspace

The gate executes the repo's own tests on top of whatever the coder just ran, so any suite with side effects is doubled. A copy-based attempt produced 7 GB of copied trees and was reverted — `working_dir` is not always the workspace.

**What would settle it:** a design that does not copy the world. The surviving note is "run the offline leg FIRST". Do not re-attempt the copy without a bound on what gets copied.

---

## Step 2 — the two cells

```
sudo -n systemctl restart cria.service          # two fixes are committed and not yet live
python3 suite/run.py --task shipping-rates-rb --model ternary-bonsai --planner off --milestone-minutes 15 --note "<NOTE>"
python3 suite/run.py --task shipping-rates-rb --model gemma4         --planner off --milestone-minutes 15 --note "<NOTE>"
```

**Restart `cria.service` before the first cell.** Code changes need it; prompt files reload per call.

**`/usr/bin/bundle` now exists** (`ruby-bundler`, installed 2026-08-17). Both ruby cells are therefore on a changed *environment* as well as changed code. Say so when reporting them; do not attribute movement to the fixes alone.

**Killing a run kills a tree, and `setsid` was not enough.** `kill` on the parent left `python3 -m cria` and two `codex exec` processes driving the GPU at 340 W, twice in one session. After any stop, verify:

```
pgrep -af "suite/run.py|python3 -m cria|codex exec"     # must be empty
ss -tnp | grep 18084 | grep -v llama-server            # must be empty
nvidia-smi --query-gpu=utilization.gpu,power.draw --format=csv,noheader
```

---

## Step 3 — walk them

Follow [`docs/walk-prompt.md`](../walk-prompt.md). Every call, first to last, including the model's reasoning. Findings to `docs/audits/finish-and-remeasure-walk.md`, one `## <run_id>` per run, each with `cria fault: yes | none` and the call number and quoted bytes.

**These two cells have known history — read it before walking, and check whether each defect recurred:**

| what happened | fix that should have closed it |
|---|---|
| the write validator refused a complete five-change implementation with `:36: s` | `c7a3c3e` — the whole diagnostic |
| cria reported "the SAME action 3×" for a command issued once, then ordered a hardcode the task forbids | `c3fe858` — the measured count |
| the install note named `vendor/bundle/gems/`, which bundler never creates | landed earlier; verify on disk |
| a 743-second dead stream, 78% of a run | `34a9162` — the wire deadline |
| the coder could not retype `./tmp/read-only/` | `845900b` — `./tmp/reference` |

A fix that did not behave is a finding. So is a fix that caused something new.

---

## Step 4 — DROPPED (operator, 2026-08-19)

**This step is no longer part of the goal.** It is kept here rather than deleted so the reasoning survives.

It asked for `shipping-rates-rb` to read 100% twice at one commit. Across the pass that followed it read 0/5, 1/5, 1/5 and 1/5 under four different models, and the causes were isolated by hand: a `require "bundler/setup"` the model guarded into a no-op, and `eu_countries`, a gem whose first line requires a name nothing on this box provides — chosen independently in three separate runs. Neither is cria's.

The BASE/CRIA comparison run alongside it produced better work than chasing one cell to 100% would have: it found that cria is a **wash** across 28 paired cells (median 75% both arms), that the assists proposed for deletion fire just as often in the runs that reach 100%, and that the real defect is assists which never let go — a research step that never clears averages 24% against 55% for one that does.

What follows from the walk continues under its own steam. Step 5 is unaffected.

## Step 4 (original text, superseded)

Six questions per item, from `hundred-goal.md` Phase 4. Then a test that fails before and passes after, named for the behaviour, with the incident in its docstring. `python3 -m pytest` green. Commit and push per item. Restart `cria.service`. Re-run the cell.

**Repeat until both cells are 100%.** Not "improved", not "better than the baseline" — 100%.

**And know what a single run can prove.** Measured across every repeat in `results.jsonl`: the same cell, same arm, **same commit**, run twice moves a median of **25 points**. A check is worth 20–25. So one check flipping between runs is noise, and a cell that reads 100% once has not been shown to hold. **Confirm a 100% with a second run at the same commit before calling it done.**

---

## Step 5 — the full suite

```
python3 suite/cycle_run.py
```

24 cells, ~8 h. Check the environment is clean first (`hundred-goal.md` Phase 1). Report each cell as it lands. Refresh the grid with `python3 suite/battery_status.py --write` after every run.

Compare against the previous pass **through the noise floor**: `battery_status.py` marks a delta smaller than one check as `~+20` and never bolds it. A `~` is not movement. Only a gap bigger than one check, or the same gap repeated, is a result.

---

## Rules that do not bend

- **A count is not a reading (#23b).** Three findings collapsed in this session and every one was a count. Before acting on any number, read one counted example end to end.
- **A finding from an agent is a CANDIDATE.** Reproduce it yourself, in the source or by running it, before it becomes a fix. Say how you checked.
- **The safe direction is REMOVE (#1).** Deleting an assist shown to mislead beats adding three. Six of the seven fixes this session were deletions or completions.
- **Assume cria caused it (#16)** — read what the model received, read what it reasoned, compare with disk, run the real tool.
- **Never end a turn on an intention.** Finish with work done or work actually running.
- **Never edit `suite/tasks/*/prompt.txt`** without the operator, and never make a task easier to pass.
- **Never delete run evidence.** Annotate rows; keep the captures.
- **Never end a session to a human (#14).** No off-ramps, no "should I continue".
- **Plain language in chat** — the verdict and the cause, scoped by RUN not by day. Detail goes in the docs.
