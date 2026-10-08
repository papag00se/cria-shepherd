# Battery report etiquette

`docs/battery-report.md` is a standing scorecard, not a supervision log.

- Exactly six tables, ordered L0–L5. Keep the original descriptive level titles and append each table's rounded average usefulness. No extra “latest run” commentary.
- Apart from the document title, descriptive level titles, tables and legend, no narrative, timestamps, revision notes, campaign sections, checkpoint prose or attempt ledgers.
- Each model row has the six task scores, average usefulness, average wall minutes, average model calls and average tokens per second. Historical `total` means average usefulness, not a sum.
- Publish only independent final judgments of the exact terminal archive. A checkpoint is never a final score. Natural exit is not proof of completion.
- Keep the latest judged value per logical cell, not its best value. Pending work retains its prior standing until independently judged. Preserve failed originals unscored; select an authorized linked replacement/disposition once only.
- Compute title and row usefulness averages from the actual task percentages, including judged zeros, excluding blanks/unjudged/failed attempts. Do not average rounded row means to obtain a table mean.
- Use authoritative result-row metrics. Minutes include judge waits, unlike active-time checkpoint pace. Unknown, boolean, non-finite or negative measurements are not zero. Means with incomplete measurement coverage are partial known-metric means.
- `avg tok/s` is the arithmetic mean of known per-task `avg_tok_s`, shown to one decimal. Each saved run rate is timed generated output tokens divided by timed generation seconds across all captured phases (coder and internal roles), not wall-time throughput or coder-only speed. Missing historical timing stays `·`; include measured zeros, exclude invalid measurements and disclose known-task coverage separately. Do not reconstruct timing from rounded rates or invent rates for frozen-only history.
- Coverage, runtime limitations, termination basis and provenance belong in `docs/battery-report-evidence.md`, the campaign's external `SUPERVISION.md`, and validation bundles—not in the scorecard.

## Publication

Use `python suite/battery_status.py --campaign-id NAME --write` with the manifest for the level being updated. The writer validates manifest-selected results, overlays judged cells onto that level's standing table, retains pending standings and every other level, recomputes averages, and records coverage separately in the evidence document. Ordinary publication refreshes the target level's token rates only; a deliberate column migration adds the field to all levels without altering their existing scores/metrics. For mixed historical/new rows, metrics use matching authoritative standing rows where available; never reconstruct per-cell metrics from old rounded means.

Bare `--write` refuses overwrite. A legacy narrative-rich report also refuses overwrite: preserve it in the evidence document before explicitly migrating to the six-table shape. Do not discard historical evidence to make a formatting test pass. Inspect the diff before committing; stage only the scorecard, evidence, and intended result records. Documentation-only publication must not restart an active inference cell.

The legacy `report()` function is a historical-data preview, not the standing-report writer. `fresh_table()` is a campaign-only preview with coverage; neither preview may be pasted wholesale into the scorecard. Regression coverage is in `tests/test_battery_report_etiquette.py` and `tests/test_fresh_campaign_report_averages.py`.

## Restored L5 campaign

The same serial restored eight-model driver supports `--level 5`; planner remains OFF. It preserves fleet assets/native contexts, source role sampling, Codex 0.159.3, the sandbox, cell-local install homes, output policy and compaction policy. Only canonical numeric role sampling is applied in a cell-scoped config; the exact original config is restored afterward. New operator edits cause a refusal to overwrite, with both originals and active config preserved externally. Provenance binds all four configured numeric role settings to the fleet and verifies coder sampling from captured requests. Internal judge calls retain cria's existing purposeful per-call overrides; this is not a claim that every judge wire body equals its role's default.

The driver waits for an independent final judgment before launching the next cell. Every 15 active minutes it freezes a checkpoint; protect the first 30 active minutes, exclude judge waits, and judge substantive requirement pace against the task/seed/current/prior frozen sources. No task-code assistance, GPU overlap, blind retries, planner opt-in, or assist/prompt changes during the campaign. Infrastructure failure stops the campaign for preserved evidence and a tested repair; coding defects alone do not authorize reruns. Scheduled supervision must obey newer operator instructions.
