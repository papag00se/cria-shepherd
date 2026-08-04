# Regression campaign — do the passing models still pass?

2026-08-03 changed a lot of cria in one day: the spill whole-read handover, the repeat-collapse
note, the replan noise-judge drop gate, the cria-voice scrub, both field caps, the model-authored
reading step with its retry, the periodic reading check, and the plan-off routing change that
drives a 2-item plan through the real multi-item driver. Six of the seven passing models passed
**planner-off**, which is exactly the path those last changes rewired. Nothing about those passes
is known to survive today until it is re-run.

**The question:** each previously-passing model, 3 scored runs on current `main`. Does it still
pass?

**Out of rotation, by operator call:** `fabliq` (parked) and `zaya1` (blocked on tooling). They
stay in the ladder table; do NOT run them, do NOT remove them from `LADDER`.

## The one source of truth

```
python3 suite/regression_status.py
```

Run it FIRST, and after every action. It reads `suite/results/results.jsonl` and the walk file —
never a conversation. Whatever it prints under `NEXT:` is the next action; if a chat message and
the tool disagree, the tool is right. Its exit codes: 0 complete, 1 work remains, 2 a run is in
flight.

Campaign runs are identified by their note prefix `REGRESSION1` (the NEXT line prints the full
command, including the note). The ladder's own tooling filters on `LADDER`, so neither tool counts
the other's runs.

## The loop

1. `python3 suite/regression_status.py`
2. **A run in flight** → wait for it. Never start a second run. Never edit `cria/` or
   `cria/prompts/` while one runs — prompts load from disk on every call, so an edit changes the
   RUNNING system.
3. **NEXT: WALK …** → walk that run before anything else runs. A walk is READING every call of the
   capture in order — `NNNN-*.prompt.txt` paired with `NNNN-*.reasoning.txt` — not a grep, not a
   sample, not a count. Write it into `docs/audits/ladder-walk.md` under `## <run_id>` with a
   `cria fault: yes|none` line.
   - `cria fault: yes` → fix it per `docs/principles.md`: upstream cause, no fallbacks, no
     task-specific special cases, measure prevalence first, a test that fails before and passes
     after. `python3 -m pytest` stays green. Commit AND push. Restart `cria.service` and say what
     went live. Then mark that model's FAILED campaign rows
     `{"superseded": "<which fix and why>"}` in `results.jsonl` so its three runs measure the code
     that now exists.
   - `cria fault: none` → the row stands as evidence about the model. Move on.
4. **NEXT: RUN …** → run exactly the printed command. One run at a time; keep the GPU busy —
   the moment a run ends, do the bookkeeping and act on the next `NEXT:`.
5. After EVERY finished run, update `docs/audits/regression-report.md`: the row (model, run,
   score, run_id, git sha, terminal) and one plain-language line if anything was notable. The
   report is for the operator to follow along; the status tool stays the truth.
6. Repeat until `regression_status.py` exits 0. Then write the report's final summary: which
   models are stable 3/3, which are not, and — for any that are not — the one-line cause from
   each walk.

## Rules that do not bend

- The status tool decides what happens next, never narration and never memory.
- Walk before run, always. A scored failure already holds its evidence; a new run buries it.
- One run per code state: after any cria change lands, restart `cria.service` before the next run.
- Preserve all run evidence (`~/.cria/calls`, `~/.cria/suite`, `suite/results/*.log`) — annotate
  rows (`aborted`/`superseded`), never delete them.
- Commit and push per unit of work.
- Plain-language reporting in chat: verdicts and causes, not activity logs.
