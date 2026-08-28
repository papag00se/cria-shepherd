# GATE — shipping-rates-rb_nemotron-elastic_codex_poff_1787884907 at 45 minutes

**How many of these 5 deliverables are COMPLETE?** Write the integer alone into `shipping-rates-rb_nemotron-elastic_codex_poff_1787884907.045min.verdict` in this directory. The run continues while you decide; it is stopped only if your answer is below 3.

Judge whether the work is DONE, not whether a check passes. A deliverable that works but trips a check on something incidental is complete. A deliverable that is written but cannot run is not.

## The deliverables this task names
1. threshold bug fixed
2. express zone
3. own tests for express
4. README rate table
5. country code -> zone via a maintained gem

## The task, as the coder received it
Make these five changes to the shipping module:

1. Fix the failing repository tests. Do not change assertions in tests that came with the repo. Tests you add may be changed freely.
2. Add an `express` service costing `14.99` base plus `2.50` per kilogram. It must follow the same free-shipping and oversize rules as the existing zones. Add tests for it.
3. Add a README rate table listing every zone with its base rate and per-kilogram rate.
4. Add `Shipping.zone_for(code)` for two-letter country codes:
   - `GB` returns `domestic`
   - EU members returns `eu`
   - all others returns `international`
5. Make `Shipping.shipping_cost` accept either a zone name or country code.

Do not hardcode EU membership. Add a third-party Ruby gem that determines whether a country is in the EU, add it to the project dependencies, and use it for the lookup.

## What the repo's own verifier observes right now — EVIDENCE, not the verdict
- [NOT met] suite_green_tests_intact: 7 runs, 7 assertions, 1 failures, 0 errors
- [NOT met] hidden_contract: 10 runs, 4 assertions, 1 failures, 6 errors
- [NOT met] express_zone: prices ^
	from -e:1:in `<main>' (want 14.99 24.99); model wrote its own tests: False
- [NOT met] readme_rate_table: zones named ['domestic'], 0/8 rate values present
- [NOT met] country_zone_mapping: zones from -e:1:in `<main>'; third-party requires: none

## Everything the coder has changed since the seed
```diff

```
