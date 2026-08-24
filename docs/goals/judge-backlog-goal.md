# Goal — judge every unjudged battery cell

## The one truth

```
python3 suite/usefulness.py pending --arm CRIA --since 1787500000
```

That command is the completion status. Not a checklist, not a message, not a plan. The goal is DONE when it prints nothing, and not before. Run it at the start of every turn and after every recorded verdict.

Do not track progress in your own output. Do not say what you are about to do. Judge a cell, record it, run `pending`, repeat.

## Why this exists

A 24-cell run finished 2026-08-24 05:04 and none of it was judged. The agent reported strict verifier scores for hours, compared them against a judged baseline, and drew a conclusion from two different measures. The judging step was skipped 24 times because its trigger — a cell finishing — was used for reporting instead.

## The loop

For each run_id from `pending`:

1. `python3 suite/usefulness.py emit <run_id>` — the rubric and the evidence packet.
2. Open the workspace and READ. Do not judge from the packet alone. At minimum: any README that is a deliverable, any test file that is a deliverable, and the source that is supposed to use a required library. A `met` check proves only its own minimum.
3. Write the verdict JSON: `usefulness`, a two-sentence `reason`, and one entry per deliverable using the verifier's exact deliverable names.
4. `python3 suite/usefulness.py record <run_id> < verdict.json`
5. Append one row to `docs/audits/judged-progress.md` (below).
6. Run `pending` again.

## The rubric is fixed

`suite/prompts/usefulness_judge.txt`. Read it before the first cell and do not reinterpret it per cell. Two rules do not bend: code that does not build cannot exceed 39, and a supplied test that was deleted or weakened is not progress. Every score below 100 names the observed deficiency that caused it.

## The progress file

`docs/audits/judged-progress.md`, rewritten after EVERY cell so it can be read mid-run. One row per cell:

| # | task | model | strict | useful | the one-line why |

Plus a header line: `N of 24 judged — last updated <time>`.

This file is for the operator to follow along. It is not the completion status; `pending` is.

## Rules

- One cell at a time. Record before starting the next.
- Never stop to ask a question. Never offer options. Never propose a plan.
- Never say "judging the rest now" — just judge the next one.
- No summary until `pending` is empty. If context runs short, keep going; the worklist survives.
- Do not fix cria, do not commit code, do not touch `suite/tasks/*/prompt.txt`. Judging only.
- A cell with no workspace on disk is still judged, from the packet — a missing workspace is evidence, not an excuse.

## Done

`pending --arm CRIA --since 1787500000` prints nothing. Then, and only then:

1. Refresh the grid: `python3 suite/battery_status.py --write`
2. Report the judged grid and the assists-off vs assists-on comparison with BOTH sides judged.
