Launch no more than 10 agents to walk the latest suite results. line-by-line, no shortcuts like grep'ing. We're looking for subtleties (or obvious footgun) in the context that could steer a weak model wrongly. We should see evidence of it in the model's thinking (also walked line-by-line). 

DO NOT LET THE SIZE AND NUMBER OF FILES PUSH YOU INTO SHORTCUTTING. EVEN WITH THOUSANDS OF LARGE FILES I AM STILL ASKING YOU TO DO IT PROPERLY!!!

We're also looking for evidence that the recent fixes are behaving as expected or causing more issues.

A faithful walk never lets walked material compact before its findings are recorded. Compaction is summarization, and summarization is the shortcut this walk forbids, applied silently to the exact material under inspection: a reader handed too large a slice fills its window, compacts mid-walk, and the "walk" quietly becomes a summarized skim while still reporting as complete. So partition the capture into segments small enough that a reader finishes one with no compaction event, give each segment its own fresh reader (never continue a reader onto a second segment — a continued reader is what compacts), have each reader write a durable finding file (context -> action -> consequence, citing exact call/chunk), and assign the next unstarted segment only after verifying the prior finding file cites real artifacts. Progress is the finding files on disk, never a reader's memory. `suite/walk.py <session> --out <dir> --segment-bytes 250000 --label <cell>` does this batching for you — it materializes the run losslessly, cuts self-contained segments under the measured compaction ceiling, and writes `assignments.json` + `WALK-PLAN.md`. The 250000-byte budget suits a large-context (>=~200k-token) reader; the ceiling belongs to the READER model, so for a smaller reader pass `--reader-context-tokens <window>` instead (e.g. a 48000-token reader gets a ~50 kB budget) or it will be handed segments bigger than its whole window. With more segments than your agent cap, dispatch in waves of fresh readers and verify each wave's finding files before the next.

Suggestions from subagents are signals and evidence only. Never take them at their word. Double check yourself.

`A` leads to `B` which causes `C` to break. Don't jump to fix `B`. `A` led to `B`, so you should look at `A` to see if you can get `B` in a better state so `C` doesn't break. That is a pattern that I'd like you to keep in mind whenever looking at fixes.

Suggest fixes that comply with the following:

1. Candidate fixes should comply with @docs/principles.md 
1. Check those fixes against commit history to ensure we aren't reintroducing previous footguns. 
1. Run the fixes through adversarial reasoning. 
1. Replay the fixes against the model using real call logs to see if the fix is effective.
1. Do not duplicate similar assist/fix logic. This is similar to the A, B, C thread above. Be aware of other similar assists/fixes in cria, so you can adjust or build on them instead of duplicating assist logic - causing trips and footguns.
