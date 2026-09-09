Launch no more than 20 agents to walk the latest suite results. line-by-line, no shortcuts like grep'ing. We're looking for subtleties (or obvious footgun) in the context that could steer a weak model wrongly. We should see evidence of it in the model's thinking (also walked line-by-line). 

DO NOT LET THE SIZE AND NUMBER OF FILES PUSH YOU INTO SHORTCUTTING. EVEN WITH THOUSANDS OF LARGE FILES I AM STILL ASKING YOU TO DO IT PROPERLY!!!

We're also looking for evidence that the recent fixes are behaving as expected or causing more issues.

Suggestions from subagents are signals and evidence only. Never take them at their word. Double check yourself.

`A` leads to `B` which causes `C` to break. Don't jump to fix `B`. `A` led to `B`, so you should look at `A` to see if you can get `B` in a better state so `C` doesn't break. That is a pattern that I'd like you to keep in mind whenever looking at fixes.

Suggest fixes that comply with the following:

1. Candidate fixes should comply with @docs/principles.md 
1. Check those fixes against commit history to ensure we aren't reintroducing previous footguns. 
1. Run the fixes through adversarial reasoning. 
1. Replay the fixes against the model using real call logs to see if the fix is effective.
1. Do not duplicate similar assist/fix logic. This is similar to the A, B, C thread above. Be aware of other similar assists/fixes in cria, so you can adjust or build on them instead of duplicating assist logic - causing trips and footguns.
