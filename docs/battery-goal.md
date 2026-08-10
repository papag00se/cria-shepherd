# Battery campaign — what do the assists actually buy, across five kinds of work?

Everything cria knows about itself was learned on `ada-handles`. Five other tasks exist
(`docs/task-battery.md`) and have barely been run. And no number anywhere says what cria's assists
are WORTH, because there has never been a control.

**The question:** for four models across six tasks, what does the same model score with cria
driving versus with cria only plumbing?

## The two arms

| arm | `[engagement] drive` | what runs |
|---|---|---|
| `BASE` | `false` | plain proxy — protocol translation, window fitting, tool-menu curation, per-model sampling and reasoning, template repair, dialect recovery |
| `CRIA` | `true` | all of the above **plus** the planner, steers, gates, critics and completion judging |

`BASE` is not "cria removed". Codex speaks the Responses API and llama.cpp does not, so unplugging
cria produces a pair that cannot exchange one message — that measures the protocol gap, not the
model. `BASE` removes the ASSISTS and keeps the PLUMBING, which is the only control that answers
the question. Dialect recovery stays in `BASE` for the same reason: without it qwen35's XML tool
calls parse to zero and the run measures cria's parser instead of the model.

## The matrix

Four models — `gemma4`, `qwen35`, `ternary-bonsai`, `nemotron-elastic`. qwythos, qwopus and ornith
are Qwen3.5 derivatives and qwen35 stands for all of them.

Six tasks, deliberately NOT `ada-handles` (its findings are already banked) and deliberately not the
seven `handles-*` ports, which are one problem in seven languages — a portability question, not a
variety one:

`shipping-rates-py` · `orders-api-py` · `feed-pipeline-py` · `missing-tests-py` ·
`sqlite-inventory` · `rust-toml-cli`

4 × 6 × 2 arms = **48 runs**. One at a time; roughly sixteen hours of GPU.

**Order: the whole BASE arm first, then the whole CRIA arm.** Not pair-by-pair. Two reasons. The
baseline is the thing we have never had, so it is worth having complete and on its own terms before
any comparison exists to be tempted by. And a phase runs on ONE code state end to end — pair-by-pair
invites a fix landing between the two halves of a pair, which voids it.

## The one source of truth

```
python3 suite/battery_status.py
```

Run it FIRST and after every action. It reads `suite/results/results.jsonl` — never a conversation,
never a memory. Whatever it prints under `NEXT:` is the next action. If a chat message and the tool
disagree, the tool is right. Exit codes: 0 complete, 1 work remains, 2 a run is in flight.

Campaign runs carry the note prefix `BATTERY1`, so no other campaign's rows are counted and none of
these are counted by theirs.

## The loop

1. `python3 suite/battery_status.py`
2. **A run in flight** → wait. Never start a second. Never edit `cria/` or `cria/prompts/` while one
   runs: prompts load from disk on every call, so an edit changes the RUNNING system.
3. **NEXT: RUN …** → run exactly the printed command. It sets the arm's `drive` flag and restarts
   `cria.service` itself; do not hand-edit `~/.cria/cria.toml`.
4. **NEXT: WALK …** → a `CRIA`-arm run that scored below its `BASE` twin is the campaign's whole
   point and gets walked before anything else runs. A walk is READING every call in order — not a
   grep, not a sample, not a digest. Materialize it with
   `python3 suite/walk.py <session> --out <dir>` and read every chunk, paging any marked
   `OVERSIZED`. Then run `python3 suite/reasoner_audit.py <session> --bad` and, for every bad
   injection, answer the two questions that matter: **what did that model SEE, and what did it
   THINK?** A false fact cria emitted is a prompt-composition bug until proven otherwise.
   Write it into `docs/audits/battery-walk.md` under `## <run_id>` with a `cria fault: yes|none`
   line.
   - `cria fault: yes` → fix per `docs/principles.md`: upstream cause, no fallbacks, no
     task-specific special cases, measure prevalence first, a test that fails before and passes
     after. `python3 -m pytest` green. Commit AND push. Restart `cria.service`. Then mark the
     affected rows `{"superseded": "<which fix and why>"}` so they measure code that no longer
     exists.
   - `cria fault: none` → the row stands as evidence about the model.
5. After EVERY finished run the grid refreshes itself (`suite/run.py` calls it). Read
   `docs/audits/battery-report.md` and add one plain-language line if anything was notable.
6. Repeat until the status tool exits 0, then write the closing summary: for each task, what the
   assists were worth; for any task where `CRIA` lost to `BASE`, the one-line cause from its walk.

## What the table has to show

The existing model grid answers "which model is best". This one answers a different question and
needs a different shape — **per task, both arms, side by side**, so the delta is readable without
arithmetic:

```
task                model             BASE   CRIA   Δ    calls B→C   min B→C
shipping-rates-py   gemma4             2/4    4/4   +2     31→ 44     4→  6
```

Plus a per-model roll-up of total delta across the six tasks. A negative Δ is the most valuable
cell in the table: it is cria actively making a model worse, and it is what the walks exist to
explain.

## Rules that do not bend

- The status tool decides what happens next. Never narration, never memory.
- One run per code state. After any cria change lands, restart `cria.service` before the next run.
- The BASE arm completes before the CRIA arm begins. The status tool will not offer a CRIA run
  while a BASE run is outstanding.
- A pair must compare the same code state. `BASE` runs on a plain proxy, so most cria fixes cannot
  touch it — but a fix to the PLUMBING (translation, floor, menu, dialect recovery) does, and then
  the affected BASE rows are superseded and re-run before their CRIA twins are read against them.
- Never delete run evidence; annotate rows instead.
- Commit and push per unit of work.
- Plain-language reporting in chat: the verdict and the cause, not an activity log.
