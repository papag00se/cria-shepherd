Launch no more than 40 agents to walk the latest suite results. line-by-line, no shortcuts like grep'ing. We're looking for subtleties (or obvious footgun) in the context that could steer a weak model wrongly. We should see evidence of it in the model's thinking (also walked line-by-line). 

We're also looking for evidence that the recent fixes are behaving as expected or causing more issues.

`A` leads to `B` which causes `C` to break. Don't jump to fix `B`. `A` led to `B`, so you should look at `A` to see if you can get `B` in a better state so `C` doesn't break. That is a pattern that I'd like you to keep in mind whenever looking at fixes.

Candidate fixes should comply with @docs/principles.md  