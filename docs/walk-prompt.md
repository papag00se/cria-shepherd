Launch no more than 40 agents to walk the latest suite results. line-by-line, no shortcuts like grep'ing. We're looking for subtleties (or obvious footgun) in the context that could steer a weak model wrongly. We should see evidence of it in the model's thinking (also walked line-by-line). 

We're also looking for evidence that the recent fixes are behaving as expected or causing more issues.

`A` leads to `B` which causes `C` to break. Don't jump to fix `B`. `A` led to `B`, so you should look at `A` to see if you can get `B` in a better state so `C` doesn't break. That is a pattern that I'd like you to keep in mind whenever looking at fixes.

Suggestions from subagents are signals and evidence only. Never take them at their word. Double check yourself.

Bad fix conditions to avoid:
1. A fix that reverts the intent of a previous fix - from an hour ago to last year. Check ANYTHING related to your proposed fix to be sure you aren't ignoring or reverting the effects of a previous assist/fix.
2. Duplicating similar assist/fix logic. This is similar to the A, B, C thread above. Be aware of other similar assists/fixes in cria, so you can adjust or build on them instead of duplicating assist logic - causing trips and footguns.

Candidate fixes should comply with @docs/principles.md  