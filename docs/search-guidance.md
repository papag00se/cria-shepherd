# Search guidance boundaries

Outgoing search relevance and its `semanticquery.Query` lifecycle have been deleted by explicit operator decision. They are not disabled implementations awaiting a profile opt-in. `outgoing-search-relevance` is no longer an accepted assist configuration ID. The immutable historical Rank-4 ranking still contains it; historical runs retain their actual deployed selection.

An ordinary `web_search` passes through unchanged. There is no outgoing relevance reasoner call, recommendation parser, relevance cache, recommendation note, search-to-fetch substitution, substitution provenance registry, or substitution-specific error attribution. Dedicated relevance prompts and bindings have been removed. This is a boundary decision, not a claim of measured usefulness improvement.

Separate mechanisms remain separate:

- `overlapping-search-new-direction` asks whether an overlapping search is a new hunt. It grants at most one canonical repeat-search clearance, only when the exact judged completion and call identity are retained. A discarded positive judgment retains unspent eligibility; a historical positive with unknown spend cannot invent a grant.
- Repeat-search admission remains owned by the public research policy. Identical searches need no new-direction judgment. Disabling that owner cannot leave a competing semantic clearance owner active.
- Incoming search/spill judgment still judges returned research. Fetch results, visible research, loader refusal events and observed successes retain their authoritative owners. An HTTP 200 registry page is not a successful install/load; a real later success may supersede an earlier refusal.
- Planning remains OFF by default. Restoring `experimental-plan-gather` eligibility is not permission to enable planning. The current ablation profile excludes only `experimental-step-preparation` and `search-spill-read-judgment`.

## Incident lessons retained after removing the mechanism

Earlier relevance repairs distinguished on-target subject matter from a usable search string. A Go decimal spiral could be on-target while its recommendation was a better query. Other recommendations contained literal `web_search(...)` wrappers, instruction sentences, two ambiguous quoted candidates, or a case-only rewrite. The deleted mechanism's parser and recommendation-note behavior are not retained as compatibility features. Production tests instead pass these incident inputs through the real driver and assert an unchanged search, no relevance question and no recommendation note.

An answering registry page previously caused a judge to recommend `eu_countries` despite the authoritative loader refusal (`cannot load such file -- iso3166`). Another incident repeatedly recommended the already-404 `github.com/oklog/decimal`. A reasoner-invented `rubygems.org/gems/eu-membership` fetch replaced a search and its error was then blamed on the coder. Ordinary searches can no longer enter that substitution path. Tests preserve the fetch/refusal ledger independently and retain normal client-error behavior for fetches the coder actually requests.

Regression ownership: `tests/test_search_relevance_is_removed.py`, `tests/test_search_relevance_incidents.py`, `tests/test_semantic_query_policy.py`, `tests/test_semantic_query_production_binding.py` and `tests/test_rehunt_lifecycle.py`. Existing incoming-result, raw refusal, repeat-admission and stalled-work observation-failure tests remain active; the latter now exercises retained rehunt settlement rather than the deleted substitution credit.
