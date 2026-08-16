# Battery campaign — what do the assists actually buy, across five kinds of work?

Everything cria knows about itself was learned on `ada-handles`. Five other tasks exist (`docs/task-battery.md`) and have barely been run. And no number anywhere says what cria's assists are WORTH, because there has never been a control.

**The question:** for four models across six tasks, what does the same model score with cria driving versus with cria only plumbing?

## The two arms

| arm | `[engagement] drive` | what runs |
|---|---|---|
| `BASE` | `false` | plain proxy — protocol translation, window fitting, tool-menu curation, per-model sampling and reasoning, template repair, dialect recovery |
| `CRIA` | `true` | all of the above **plus** the planner, steers, gates, critics and completion judging |

`BASE` is not "cria removed". Codex speaks the Responses API and llama.cpp does not, so unplugging cria produces a pair that cannot exchange one message — that measures the protocol gap, not the model. `BASE` removes the ASSISTS and keeps the PLUMBING, which is the only control that answers the question. Dialect recovery stays in `BASE` for the same reason: without it qwen35's XML tool calls parse to zero and the run measures cria's parser instead of the model.

## The matrix

Four models — `gemma4`, `qwen35`, `ternary-bonsai`, `nemotron-elastic`. qwythos, qwopus and ornith are Qwen3.5 derivatives and qwen35 stands for all of them.

Six tasks, deliberately NOT `ada-handles` (its findings are already banked) and deliberately not the seven `handles-*` ports, which are one problem in seven languages — a portability question, not a variety one:

`shipping-rates-py` · `orders-api-py` · `feed-pipeline-py` · `missing-tests-py` · `sqlite-inventory` · `rust-toml-cli`

4 × 6 × 2 arms = **48 runs**. One at a time; roughly sixteen hours of GPU.

**Order: the whole BASE arm first, then the whole CRIA arm.** Not pair-by-pair. Two reasons. The baseline is the thing we have never had, so it is worth having complete and on its own terms before any comparison exists to be tempted by. And a phase runs on ONE code state end to end — pair-by-pair invites a fix landing between the two halves of a pair, which voids it.

## These tasks are largely unproven — that is part of the job

`ada-handles` has been walked dozens of times. These six have barely run. `docs/task-battery.md` still lists `orders-api-py` and `feed-pipeline-py` as **planned** even though both have a verifier on disk, which tells you how much attention they have had.

What is already established (checked 2026-08-10): every seeded task scores **0/4 on its untouched seed** — `shipping-rates-py`, `orders-api-py`, `feed-pipeline-py`, `missing-tests-py`. So no verifier is trivially passable and no task is already finished. `sqlite-inventory` and `rust-toml-cli` are greenfield and have no seed to score.

What is NOT established, for five of the six: **that a correct solution can actually reach 4/4.** Only `shipping-rates-py` is proven in both directions. A verifier that cannot be satisfied produces a column of zeros that looks exactly like four models failing, and would quietly waste half the campaign.

**So the baseline arm doubles as the shakedown, and a task is on trial until it is not.**

- A task whose finished BASE cells are **all zero** is a suspect verifier, not a finding. The status tool stops and says `NEXT: VALIDATE <task>` before any more runs.
- To validate: read `verify.py` and the prompt together and ask whether the prompt actually asks for what the verifier checks. Then satisfy it by hand in a scratch copy of the seed — the smallest honest solution — and score it. If a correct solution cannot reach 4/4, the task is broken.
- **Fixing a task is a first-class outcome of this campaign, not a detour.** Fix the verifier or the prompt, note what was wrong in `docs/task-battery.md`, and update its status line there.
- Any change to a task's `verify.py`, `prompt.txt` or seed **invalidates every row already scored on it**. Mark them `{"superseded": "<what changed in the task and why>"}` and re-run them. A campaign comparing runs across two different definitions of the same task measures nothing.
- Never fix a task by making it easier to pass. The failure mode to avoid is a verifier tuned until the models look good; the point is a verifier that is TRUE. If a task is genuinely too hard for every model, that is a finding — record it and move on, do not soften it.
- Never special-case cria for a task (`docs/principles.md`). If a task exposes a cria bug, that is the campaign working.

## The one source of truth

```
python3 suite/battery_status.py
```

Run it FIRST and after every action. It reads `suite/results/results.jsonl` — never a conversation, never a memory. Whatever it prints under `NEXT:` is the next action. If a chat message and the tool disagree, the tool is right. Exit codes: 0 complete, 1 work remains, 2 a run is in flight.

Campaign runs carry the note prefix `BATTERY1`, so no other campaign's rows are counted and none of these are counted by theirs.

## The loop

1. `python3 suite/battery_status.py`
2. **A run in flight** → wait. Never start a second. Never edit `cria/` or `cria/prompts/` while one runs: prompts load from disk on every call, so an edit changes the RUNNING system.
3. **NEXT: RUN …** → run exactly the printed command. It sets the arm's `drive` flag and restarts `cria.service` itself; do not hand-edit `~/.cria/cria.toml`.
4. **NEXT: WALK …** → a `CRIA`-arm run that scored below its `BASE` twin is the campaign's whole point and gets walked before anything else runs. A walk is READING every call in order — not a grep, not a sample, not a digest. Materialize it with `python3 suite/walk.py <session> --out <dir>` and read every chunk, paging any marked `OVERSIZED`. Then run `python3 suite/reasoner_audit.py <session> --bad` and, for every bad injection, answer the two questions that matter: **what did that model SEE, and what did it THINK?** A false fact cria emitted is a prompt-composition bug until proven otherwise. Write it into `docs/audits/battery-walk.md` under `## <run_id>` with a `cria fault: yes|none` line.
   - `cria fault: yes` → fix per `docs/principles.md`: upstream cause, no fallbacks, no task-specific special cases, measure prevalence first, a test that fails before and passes after. `python3 -m pytest` green. Commit AND push. Restart `cria.service`. Then mark the affected rows `{"superseded": "<which fix and why>"}` so they measure code that no longer exists.
   - `cria fault: none` → the row stands as evidence about the model.
5. After EVERY finished run the grid refreshes itself (`suite/run.py` calls it). Read `docs/audits/battery-report.md` and add one plain-language line if anything was notable.
6. Repeat until the status tool exits 0, then write the closing summary: for each task, what the assists were worth; for any task where `CRIA` lost to `BASE`, the one-line cause from its walk.

## What the table has to show

The existing model grid answers "which model is best". This one answers a different question and needs a different shape — **per task, both arms, side by side**, so the delta is readable without arithmetic:

```
task                model             BASE   CRIA   Δ    calls B→C   min B→C
shipping-rates-py   gemma4             2/4    4/4   +2     31→ 44     4→  6
```

Plus a per-model roll-up of total delta across the six tasks. A negative Δ is the most valuable cell in the table: it is cria actively making a model worse, and it is what the walks exist to explain.

## Persistence is one of the assists — read the delta accordingly

"cria never ends a session by handing back to a human" (`docs/principles.md` #14) is implemented in the LOOP, and `drive = false` never builds the loop. So in the BASE arm nothing nudges a model that stops: Codex sees a text answer, ends its turn, and the process exits — possibly after two minutes. The suite's wall clock and milestone checks apply to both arms, but they only ever KILL a run; nothing keeps one alive.

That is correct — persistence is one of the things being measured, not a thing to hold constant — but it means a raw Δ conflates two different claims:

```
BASE 1/4 in  2 min,   8 calls  →  CRIA 2/4 in 30 min, 150 calls    mostly persistence
BASE 1/4 in 25 min, 120 calls  →  CRIA 4/4 in 20 min, 110 calls    genuinely better driving
```

Same +1, opposite conclusions. **Always read the delta next to the calls and minutes columns**, and say which kind it is in the closing summary. A cell where CRIA scored higher using 15× the calls is a weaker result than one where it scored higher using fewer, and the campaign is worth little if the write-up flattens them into one number.

Two consequences worth naming in advance:
- A BASE run terminating `exited` in under a minute is recorded `crashed-early` by the suite. In this arm that is usually not a crash — it is the model stopping and nothing objecting. Check the calls count before reading it as a failure.
- If most BASE runs stop in minutes, the honest headline is "the assists are what keep a small model working at all", which is a real finding and should be stated plainly rather than buried in a Δ.

## Rules that do not bend

- The status tool decides what happens next. Never narration, never memory.
- One run per code state. After any cria change lands, restart `cria.service` before the next run.
- The BASE arm completes before the CRIA arm begins. The status tool will not offer a CRIA run while a BASE run is outstanding.
- A pair must compare the same code state. `BASE` runs on a plain proxy, so most cria fixes cannot touch it — but a fix to the PLUMBING (translation, floor, menu, dialect recovery) does, and then the affected BASE rows are superseded and re-run before their CRIA twins are read against them.
- Never delete run evidence; annotate rows instead.
- Commit and push per unit of work.
- Plain-language reporting in chat: the verdict and the cause, not an activity log.
