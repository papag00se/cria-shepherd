# Ornith L0 — retained-history search

**No evidence-backed L0 usefulness cells were recovered. The README leaves them unknown.**

## Sources checked

- Working `suite/results/results.jsonl` and every distinct retained version reachable through all local Git refs, using `best_l5.versions()`.
- All four retained versions of `suite/historical_ladder.json`.
- All 344 distinct retained versions of `docs/audits/battery-report.md`, including the working copy; checked explicit Level 0 sections for Ornith rows.
- `docs/model-history.md`, the historical ladder report and battery-history prose to distinguish model versions and old scoring schemes.

The only retained Ornith 1.0 identity is `ornith`. Its six ledger runs are for the older `ada-handles` task, with no explicit engagement level and no final inferred-usefulness percentage. They are not the six-language L0 battery. The retained Ornith 1.5 battery runs are explicit L5, not L0. The frozen inference ladder contains no Ornith L0 row. Older pass/check counts must not be converted into usefulness percentages, and the retired BASE arm was not reliably assists-off.

## An unsupported working-report row

One **uncommitted working-report** row names `ornith1.5_9b` at L0 and lists `50, 45, 82, 72, 89, 94`. It has no matching L0 ledger records, frozen inference record, historical committed report row or referenced run IDs. Its displayed row total is `60%`, while the six cells average `72%`; the report's overall L0 total is also stale. It cannot currently establish a baseline, so those numbers were **not imported** into the README.

Observed report SHA-256: `cdd099f27e5247b4f3d9900fe918f261e75edff85facad5e8dd55e5cbc51551c`.

The configured origin branch was fetched and remains at the same commit as the active checkout (`bc0f12f00239779718dc8a940de125304e12e9d5`), providing no additional committed history. The working report was left untouched. The search is bounded to files and refs retained on this machine, not a claim that an L0 run never happened elsewhere. If the original records or an independently reviewed frozen inference judgment are recovered, preserve their actual model version, task and engagement level in the cell provenance. Do not silently relabel Ornith 1.0 as Ornith 1.5.

## Display policy

Phi-4 is temporarily omitted from both README grids at the owner's request. Its original records and baseline values remain retained. Header averages use only the displayed roster, so a changed average is not evidence of changed delivered work.
