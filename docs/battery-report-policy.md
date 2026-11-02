# Battery report

`docs/battery-report.md` is a standing scorecard written by `python suite/battery_status.py --write`.

## Labels

A cell is named by **official model / language**, matching the scorecard columns, never by task type: `gemma4_12b / Go`, not `Gemma/cart`. The shared mapping is `suite/report_labels.py::TASK_LANGUAGES`; use `cell_label(model, task)` when generating labels. Languages are Ruby, Go, Python, Java, Node and Rust. Internal task/run IDs stay as they are in commands and archive paths.

## Layout

- The document title, then one `Updated: YYYY-MM-DD HH:MM TZ` line (when the tables were last refreshed), then exactly six tables ordered L0–L5, then a legend.
- Each table keeps its descriptive level title with the table's rounded average usefulness appended.
- All six tables share L5's model ranking: highest average usefulness first. Rank from the exact mean of the known L5 task percentages (zeros count; blanks do not). Equal means sort by ascending official model identity; models with no judged L5 score follow the scored ones in that same order. Each publication recomputes this order and moves rows in all six tables together.
- Each model row has the six task scores, average usefulness (`avg pct`), average wall minutes, average model calls and average tokens per second. The legend defines usefulness as: “Usefulness: share of requested work delivered as useful code.”

## Numbers

- A cell shows its latest judged usefulness. Cells without a judgment keep their previous value.
- Averages come from the actual task percentages: judged zeros count, blanks and unjudged cells do not. A table's average is the mean of its task percentages, not of rounded row means.
- Metrics come from result rows. Minutes include judge waits; unknown or invalid measurements are not zero, and a mean over partial coverage is a mean of the known values.
- `avg tok/s` is the mean of known per-task `avg_tok_s`, shown to one decimal. Each run's rate is timed generated output tokens divided by timed generation seconds across all captured phases. Missing timing shows `·`.
