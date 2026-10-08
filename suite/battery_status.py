#!/usr/bin/env python3
"""Battery campaign status using inferred usefulness percentages.

Checkpoint progress reports and final judgments always report usefulness as a percentage. The
percentage is inferred holistically by a reasoner, never assembled by deterministic task counting.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

try:
    from .model_names import canonical_name
except ImportError:  # direct suite/battery_status.py invocation
    from model_names import canonical_name

SUITE = Path(__file__).resolve().parent
RESULTS = SUITE / "results" / "results.jsonl"
NOTE_PREFIX = "BATTERY2"
COUNTED_PREFIXES = ("FRESH-L5", NOTE_PREFIX, "LOWSCORE", "RERANK")
# Current roster: Nemotron Elastic restored 2026-09-30; eight models entered on 2026-09-27.
# Retired models remain named in reports and keep their rows in results.jsonl / historical_ladder.json.
# Keys renamed 2026-09-27 (operator): ternary-bonsai-2 -> bonsai2, ornith15 -> ornith1.5,
# qwen38-distill -> qwen3.8_9b_distill, k2-horizon -> k2_horizon_7b. results.jsonl `model`
# fields were migrated with them; run_ids, archives and systemd units keep their names.
MODELS = ("gemma4-qat", "bonsai2", "defiant-fable", "ornith1.5",
          "k2_horizon_7b", "phi4", "ling3-tiny", "qwen3.8_9b_distill", "nemotron-elastic")
# CURRENT matrix only — a model here must be swappable and have canonical sampling.
# gemma4 (stock Q4_K_M) and ternary-bonsai (Bonsai 1) left on 2026-09-18 when their weights
# and units were deleted; they stay VISIBLE in the reports through suite/historical_ladder.json,
# which is where their scores live. Retiring a model means dropping it from here, never deleting
# its history — the ONE exception is an operator-ordered purge of a failed trial (2026-09-27, see
# docs/model-history.md), where only a mean/best line survives.
# Logical display names come from the one official-name registry. Executable keys stay intact.
DISPLAY = tuple(dict.fromkeys(canonical_name(model) for model in MODELS))
REPORT_INFERENCE_REVISION = "f79cc6146470281b5909cf605b27afca1177e2d1"
TASKS = ("shipping-rates-rb", "cart-billing-go", "orders-api-py",
         "feed-pipeline-java", "handles-cli-node", "rust-toml-cli")
ARMS = ("BASE", "CRIA")


def rows(*, all_rows: bool = False) -> list[dict]:
    if not RESULTS.exists():
        return []
    out = []
    for line in RESULTS.read_text().splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if all_rows or str(row.get("note", "")).startswith(COUNTED_PREFIXES):
            out.append(row)
    return out


def cell(rs: list[dict], arm: str, model: str, task: str) -> dict | None:
    for row in reversed(rs):
        if row.get("superseded"):
            continue
        note = str(row.get("note", ""))
        if row.get("model") == model and row.get("task") == task and f" {arm} " in f" {note} ":
            return row
    return None


def level_cell(rs: list[dict], level: int, model: str, task: str) -> dict | None:
    """Standing row for one configured engagement rung; the rung is not a grade."""
    for row in reversed(rs):
        if row.get("superseded") or row.get("level") is None:
            continue
        try:
            same_level = int(row["level"]) == level
        except (TypeError, ValueError):
            continue
        if same_level and canonical_name(row.get("model", "")) == canonical_name(model) and row.get("task") == task:
            return row
    return None


def judged(row: dict | None) -> bool:
    return bool(row and isinstance(row.get("usefulness_percent"), int))


def judgment_of(row: dict | None) -> str:
    if not row:
        return "not run"
    if isinstance(row.get("usefulness_percent"), int):
        return f"{row['usefulness_percent']}% useful"
    return "awaiting judgment"


def in_flight() -> str | None:
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            argv = [part for part in Path(f"/proc/{pid}/cmdline").read_bytes().decode().split("\0")
                    if part]
        except OSError:
            continue
        if argv and argv[0].endswith(("python", "python3")) \
                and any(arg.endswith("suite/run.py") for arg in argv):
            return " ".join(argv)
    return None


def sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, cwd=SUITE.parent).stdout.strip() or "?"
    except OSError:
        return "?"


def _stamp(rs: list[dict], now: float | None = None) -> str:
    fmt = "%Y-%m-%d %H:%M"
    written = time.strftime(fmt, time.localtime(now if now is not None else time.time()))
    latest = max((row for row in rs if row.get("started")),
                 key=lambda row: row["started"], default=None)
    if latest is None:
        return f"**Last updated {written}** — no completed rows yet."
    finished = time.strftime(fmt, time.localtime(
        latest["started"] + (latest.get("wall_seconds") or 0)))
    return f"**Last updated {written}** — newest row `{latest.get('run_id', '?')}`, finished {finished}."


_HIST_PATH = SUITE / "historical_ladder.json"


def _historical() -> dict:
    """FROZEN inference-usefulness data for models whose per-cell scores no longer survive in
    results.jsonl (a field rename orphaned them). Recovered from a committed report and never
    regenerated; see suite/historical_ladder.json. Empty dict if the file is missing."""
    try:
        return json.loads(_HIST_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _badge(pct: float) -> str:
    """Quarter bands off the midpoints: green at/above 87.5, yellow 62.5, orange 37.5, red below."""
    return ("\U0001F7E2" if pct >= 87.5 else "\U0001F7E1" if pct >= 62.5
            else "\U0001F7E0" if pct >= 37.5 else "\U0001F534")


def _dot(pct) -> str:
    return f"{_badge(pct)} {round(pct)}%" if pct is not None else "\u00b7"


def report(rs: list[dict], now: float | None = None) -> str:
    """The engagement ladder: one colored-dot cell per (level, model, task), the cell an inferred
    usefulness percentage. FROZEN models render from suite/historical_ladder.json (recovered
    inference judgments the field rename orphaned); every other model reads LIVE usefulness_percent
    from results.jsonl. The ladder format persists here in the generator so a regeneration can never
    eat it again."""
    hist = _historical()
    frozen = {}
    for name, levels in hist.get("frozen", {}).items():
        frozen.setdefault(canonical_name(name), {}).update(levels)
    labels = hist.get("levels", {})
    tasks = hist.get("tasks", list(TASKS))
    tlabels = hist.get("task_labels", list(tasks))
    live = []
    for row in rs:
        m = canonical_name(row.get("model", ""))
        if m and m not in frozen and isinstance(row.get("usefulness_percent"), int) and m not in live:
            live.append(m)
    # Normalize lookup/display only. Return the original selected row with its provenance intact.
    everything = list(dict.fromkeys(list(frozen.keys()) + live))
    ordered = [m for m in DISPLAY if m in everything]
    retired = [m for m in everything if m not in DISPLAY]
    out = ["# Battery — the engagement ladder", "", _stamp(rs, now),
           f"**Report code revision `{sha()}`; inference anchor remains `{REPORT_INFERENCE_REVISION}`.**", "",
           "Each cell is an inferred usefulness percentage \U0001F7E2\u226588 \U0001F7E1\u226563 "
           "\U0001F7E0\u226538 \U0001F534 below; `\u00b7` = not judged. `[engagement] level = 0..5`, "
           "each rung implying every rung below it. Model rows use the [official project names](model-names.md). "
           "Gemma4/QAT share the single `gemma4_12b` row: frozen history remains for unreplaced cells "
           "and the latest live judgment supersedes its matching cell. Historical model keys, run IDs "
           "and executable aliases retain their original provenance.", ""]
    for lvl in range(6):
        lv = str(lvl)
        rowdata = []
        for m in ordered:
            fro = frozen.get(m, {}).get(lv)
            cells, mins, calls = [], [], []
            for t in tasks:
                r = level_cell(rs, lvl, m, t)
                cells.append(r.get("usefulness_percent")
                             if r and isinstance(r.get("usefulness_percent"), int) else None)
                if judged(r) and _measurement(r.get("wall_seconds")):
                    mins.append(r["wall_seconds"] / 60)
                if judged(r) and _measurement(r.get("calls")):
                    calls.append(r["calls"])
            if fro:
                # A frozen row is recovered history for a model whose per-cell judgments were
                # orphaned. A fresh LIVE judgment supersedes it PER CELL (an un-paused model's
                # new campaign must be visible, not shadowed by its own past); cells the
                # campaign has not re-judged keep their frozen value so history never vanishes.
                cells = [live if live is not None else old
                         for live, old in zip(cells, list(fro["pct"]) + [None] * len(tasks))]
            mn = round(sum(mins) / len(mins)) if mins else (fro.get("min") if fro else None)
            cl = round(sum(calls) / len(calls)) if calls else (fro.get("calls") if fro else None)
            if any(p is not None for p in cells):
                rowdata.append((m, cells, mn, cl))
        if not rowdata:
            continue
        allp = [p for _m, cells, _mn, _cl in rowdata for p in cells if p is not None]
        lvavg = round(sum(allp) / len(allp)) if allp else 0
        label = labels.get(lv, "")
        out.append(f"### Level {lvl}" + (f" \u2014 {label}" if label else "") + f" \u2014 {lvavg}%")
        out.append("")
        out.append("| model | " + " | ".join(tlabels) + " | total | avg min | avg calls |")
        out.append("|---|" + "---|" * len(tlabels) + "---:|---:|---:|")
        for m, cells, mn, cl in rowdata:
            present = [p for p in cells if p is not None]
            total = f"{round(sum(present) / len(present))}%" if present else "\u00b7"
            cellstr = " | ".join(_dot(p) for p in cells)
            out.append(f"| {m} | {cellstr} | {total} | "
                       f"{mn if mn is not None else '\u00b7'} | {cl if cl is not None else '\u00b7'} |")
        out.append("")
    if retired:
        out.append("Retired from the battery (history kept in suite/results/results.jsonl and "
                   "suite/historical_ladder.json): " + ", ".join(retired) + ".")
        out.append("")
    return "\n".join(out) + "\n"


def _measurement(value) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def fresh_table(manifest: dict, rs: list[dict]) -> str:
    """Render only independently judged selected logical cells, never failed originals.

    The campaign manifest owns selection, including linked replacements/dispositions.
    Metrics come only from each selected result row; missing values retain coverage gaps.
    Ambiguous selection is an error, not permission to take the latest/best attempt.
    """
    selected = {}
    used = set()
    for cell in manifest['cells']:
        key = (cell['model'], cell['task'])
        link = None
        if cell['state'] == 'done':
            run_id, cohort = cell['run_id'], manifest['campaign_id']
        elif cell['state'] == 'infrastructure-failed':
            links = [mapping[cell['run_id']] for mapping in
                     (manifest.get('successful_replacements', {}),
                      manifest.get('judged_operator_dispositions', {}))
                     if cell['run_id'] in mapping]
            if len(links) > 1:
                raise ValueError('multiple dispositions for one logical cell')
            if not links:
                continue
            link = links[0]
            run_id, cohort = link['run_id'], link['campaign_id']
        else:
            continue
        found = [r for r in rs if r.get('run_id') == run_id]
        if len(found) != 1 or key in selected or run_id in used:
            raise ValueError('missing or ambiguous selected result')
        row = found[0]
        pct = row.get('usefulness_percent')
        if (row.get('campaign_id') != cohort or (row.get('model'), row.get('task')) != key
                or not isinstance(pct, int) or isinstance(pct, bool) or not 0 <= pct <= 100
                or row.get('terminal') == 'harness-error' or row.get('superseded')):
            raise ValueError('selected cell lacks matching independently judged result')
        if link and link.get('termination') == 'operator-ended':
            if (row.get('terminal') != 'operator-ended' or row.get('natural_completion') is not False
                    or link.get('natural_completion') is not False):
                raise ValueError('operator disposition cannot claim natural completion')
        elif row.get('terminal') == 'operator-ended':
            raise ValueError('operator-ended result requires explicit disposition')
        selected[key] = row
        used.add(run_id)
    labels = ('ruby', 'go', 'python', 'java', 'node', 'rust')
    out = ['| model | ' + ' | '.join(labels) + ' | avg usefulness | avg min | avg calls |',
           '|---|' + '---|' * len(TASKS) + '---:|---:|---:|']
    coverage = []
    for model in manifest['models']:
        present = [selected[(model, t)] for t in TASKS if (model, t) in selected]
        cells = [(_dot(selected[(model, t)]['usefulness_percent'])
                  if (model, t) in selected else '') for t in TASKS]
        pct = [r['usefulness_percent'] for r in present]
        minutes = [r['wall_seconds'] / 60 for r in present if _measurement(r.get('wall_seconds'))]
        calls = [r['calls'] for r in present if _measurement(r.get('calls'))]
        means = [str(round(sum(v) / len(v))) + suffix if v else '·'
                 for v, suffix in ((pct, '%'), (minutes, ''), (calls, ''))]
        out.append('| ' + model + ' | ' + ' | '.join(cells + means) + ' |')
        if present:
            n = len(present)
            coverage.append(f'{model}: usefulness{len(pct)}/{n}, minutes{len(minutes)}/{n}, calls{len(calls)}/{n}')
    out += ['', '**Row-average coverage:** ' + ('; '.join(coverage) if coverage else 'no judged cells') + '.',
            'Means use selected independently judged logical cells once; zeros count, pending/unjudged '
            'cells and failed originals do not. Missing, non-numeric or invalid metrics are excluded, '
            'not fabricated as zero. Minutes are authoritative wall_seconds/60, including judge waits '
            '(not active-work minutes); operator-ended measurement basis remains in attempt provenance. '
            'A mean with incomplete coverage is a partial known-metric mean.', '']
    return '\n'.join(out)


def write_report(rs: list[dict], *, campaign: dict | None = None) -> Path:
    path = SUITE.parent / 'docs' / 'battery-report.md'
    existing = path.read_text() if path.exists() else ''
    fresh_start = existing.find('<!-- fresh-')
    if fresh_start >= 0:
        if campaign is None:
            raise ValueError('fresh campaign report requires explicit --campaign-id; refusing overwrite')
        marker = f"<!-- fresh-{campaign['campaign_id']}:start -->"
        if not existing.startswith(marker, fresh_start):
            raise ValueError('campaign does not match fresh report section')
        end = existing.find(f"<!-- fresh-{campaign['campaign_id']}:end -->", fresh_start)
        table = existing.find('| model |', fresh_start)
        attempts = existing.find('### Attempt evidence', table)
        if not (fresh_start < table < attempts < end):
            raise ValueError('fresh report boundaries missing; refusing overwrite')
        # Preserve the surrounding narrative, checkpoints, failures and historical ladder exactly.
        text = existing[:table] + fresh_table(campaign, rs) + '\n' + existing[attempts:]
    elif campaign is not None:
        name = campaign['campaign_id']
        text = (f'# Battery — fresh campaign and historical engagement ladder\n\n'
                f'<!-- fresh-{name}:start -->\n## Current fresh campaign\n\n'
                + fresh_table(campaign, rs) + '\n### Attempt evidence\n'
                + f'Campaign `{name}`; see its manifest and result-row provenance.\n'
                + f'<!-- fresh-{name}:end -->\n\n' + report(rs))
    else:
        text = report(rs)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def main() -> int:
    campaign = None
    if '--campaign-id' in sys.argv:
        index = sys.argv.index('--campaign-id')
        if index + 1 >= len(sys.argv):
            raise SystemExit('--campaign-id requires a manifest name')
        name = sys.argv[index + 1]
        if Path(name).name != name:
            raise SystemExit('campaign-id must be a manifest name')
        manifest = Path.home() / '.cria/suite/_campaigns' / name / 'manifest.json'
        campaign = json.loads(manifest.read_text())
    rs = rows(all_rows=campaign is not None)
    if "--write" in sys.argv:
        print(f"wrote {write_report(rs, campaign=campaign)}")
        return 0

    print("BATTERY CAMPAIGN — inferred usefulness percentages\n")
    for task in TASKS:
        for model in MODELS:
            base = cell(rs, "BASE", model, task)
            driven = cell(rs, "CRIA", model, task)
            print(f"{task:<20} {model:<19} BASE={judgment_of(base)}; CRIA={judgment_of(driven)}")

    live = in_flight()
    if live:
        print(f"\nIN FLIGHT: {live[:120]}")
        return 2

    for arm in ARMS:
        for model in MODELS:
            for task in TASKS:
                if cell(rs, arm, model, task) is None:
                    print(f"\nNEXT: RUN {arm} {model} {task}")
                    print(f"      python3 suite/battery_run.py --arm {arm} --model {model} --task {task}")
                    return 1
    print("\nNEXT: NOTHING — campaign complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
