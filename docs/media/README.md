# README media

The front page uses project artwork, a four-cell assist illustration, an architecture diagram, a tool-repair replay and two battery grids. This directory contains their sources and rendering tools.

## Files

| Files | Purpose |
|---|---|
| `cria-logo.png`, `hero.svg`, `hero.png` | Project artwork. The logo comes from `jesselanderson.com/frontend/public/images/studio/cria-logo.png`. |
| `execution-boundary.svg`, `execution-boundary.png` | Harness, proxy and model-server architecture. |
| `field_guide.py`, `assists-overview.svg`, `assists-overview.png`, `assist-*.svg`, `assist-*.png` | A single 2×2 overview composed from four original vector scenes, with readable cell titles. Individual scenes remain available as source artifacts. PNGs use a stripped 256-color palette. |
| `tool-repair-demo.py`, `tool-repair-run.txt`, `tool-repair.gif` | Fixed-input replay through production tool-recovery code, its recorded output and animation. |
| `battery_media.py`, `battery-l0.*`, `battery-l5.*` | Grid renderer and generated SVG/PNG images. |
| `battery-data.json` | Display roster, scores, original standing snapshots and export metadata. |
| `battery-report-snapshot.md` | Unmodified standing report from `suite.battery_status`. |
| `best_l5.py`, `battery-l5-best.json` | Historical L5 selection code and cell-level provenance. |
| `snapshot-battery.py` | Standing-report exporter, with column and total validation. |
| `battery-comparison.md` | Generated text tables and measurement definitions. |
| `ornith-l0-search.md` | Record of the retained-history baseline search. |
| `render.py` | Rendering entry point. |

## Rendering

Use Python 3.11+, `rsvg-convert` and ImageMagick's `magick` command. Run from the repository root:

```bash
python docs/media/render.py                  # all media
python docs/media/render.py --assists-only   # assist illustrations only
python docs/media/render.py --battery-only   # grids and text tables only
```

Rendering reads stored scores; it does not run models or refresh measurements. The assist-only command leaves battery artifacts unchanged.

Grid titles identify engagement: **L0 · Wire translation** and **L5 · Full engagement**. Visible labels are limited to the metric, models, tasks, averages and legend. Selection methods, dates and source records stay in the data and technical documentation rather than in image footnotes. The front-page README uses short descriptions without research notes or provenance-link lists.

The assist overview uses original local vectors and seeded texture. Each cell contains a mechanism title and its scene, without duplicated captions. The illustrations are not coding-session captures. Implementation details are in `../heuristic-assists.md`.

## Tool-call replay

The example passes XML through `cria.massage.recover_reasoning_tool_calls` and checks argument conversion with `coerce_args`. It does not invoke a model or execute the recovered command.

```bash
PYTHONPATH=. python docs/media/tool-repair-demo.py
```

The animation reveals sections of the recorded stdout. Playback timing is editorial. To refresh the recording:

```bash
{
  printf 'Command: PYTHONPATH=. python docs/media/tool-repair-demo.py\n'
  printf 'Source commit: '; git rev-parse HEAD
  printf 'Recorded UTC: '; date -u +%FT%TZ
  python --version
  printf '\n'
  PYTHONPATH=. python docs/media/tool-repair-demo.py
} > docs/media/tool-repair-run.txt
python docs/media/render.py
```

## Battery data

The metric is holistically inferred usefulness. Mechanical grades, pass counts and checkpoint scores are not usefulness judgments.

L0 retains the standing snapshot. L5 selects the highest retained final judgment for each model/task, after keeping the latest available judgment for each original run. The search covers working ledger bytes and distinct ledger/frozen-summary versions reachable through retained Git refs. Accepted fields are `usefulness_percent`, its documented predecessor `usefulness`, and explicit frozen inferred-usefulness cells.

Each selected cell records its source file, revision, checksum and run ID where available. Frozen summaries retain their source record when an original run ID is unavailable. Input hashes and `source_inputs_dirty` identify uncommitted source data; a Git revision alone cannot reproduce those inputs.

Averages weight observed cells equally, include zeros and exclude missing entries. `standing_l0` and `standing_l5` preserve the original report values. `roster_model_order` retains the full display roster; `excluded_models` currently hides `phi4`. Clear that exclusion and refresh L5 to restore its display row. No Ornith L0 usefulness cells were recovered for the six-task battery.

Model identities come from `suite/model_names.py`. Defiant-Fable is merged into `qwen3.8_9b_distill`; Gemma4/QAT share `gemma4_12b`. Original run IDs remain unchanged. Distinct releases, including Ornith 1.0 and Bonsai 1, are not merged into current rows.

These are historical selections across different revisions, variants and settings, including planner experiments. Cell maxima do not measure typical performance or controlled assist uplift. Some full captures are unavailable, and the displayed judgments have not all been re-audited. Export timestamps describe the export, not every underlying run.

Refresh L5 while retaining the L0 baseline:

```bash
python docs/media/best_l5.py --source-root /path/to/cria-shepherd
python docs/media/render.py --battery-only
```

To replace the standing baseline, run `snapshot-battery.py --source-root /path/to/cria-shepherd` first. That command resets the display snapshot, so reapply any roster exclusions before selecting L5. The snapshot exporter alone produces standing values, not historical maxima.

The source revision for this draft is `bc0f12f00239779718dc8a940de125304e12e9d5`, which includes default-off planning. Integrate the README with the matching code revision before publishing.

## Tests

```bash
python -m pytest -q tests/test_readme_media.py tests/test_best_l5_media.py \
  tests/test_official_model_names.py tests/test_recovered_arg_types.py \
  tests/test_completion_gate_backstop.py tests/test_planning_is_opt_in.py
```

Tests cover repository-local image paths, report parsing, missing and zero values, averaging, historical selection, identity merging, display labels, deterministic illustrations and rasterization. They also verify that assist-only rendering does not modify battery artifacts.
