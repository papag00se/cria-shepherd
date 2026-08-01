# Test / performance matrix suite

One matrix cell per `run.py` invocation: task × model × harness × planner, under a HARD
30-minute wall (no call budget — slow models surfacing as budget-kills is signal). Each run
appends one JSON row to `results/results.jsonl`; `report.py` renders the matrix.

- Success is decided ONLY by the task's `verify.py` — deterministic, outside the session,
  runs the deliverables itself (unit tests, LIVE test with real-data evidence, CLI, README).
  Never the model's claim, never a judge verdict, never a green gate.
- Tasks pin their language (`meta.toml`); the battery covers shapes, not a language×task cross.
- cria must NEVER special-case a suite prompt (doctrine) — the suite doubles as cria's
  regression harness: run the fixed sub-matrix before/after cria changes.
- Metrics per row: wall time, terminal state (exited / budget-killed / crashed-early),
  verifier score + per-part detail, calls by phase, avg output tok/s (timed calls),
  assist events by kind (from cria's rlog), workspace path.

Phase 0: codex × {ternary-bonsai, qwythos} × ada-handles.
Planned: harness adapters (Claude Code, OpenCode, Gemini CLI, Cline), tasks (SQL/Go,
multi-module/TS, needs-search/Rust, CLI/Java), N≥2 repeats on headline cells.

## Offline harness — ask before you burn a run

A run costs 30 minutes and yields one noisy number. `replay.py` re-sends REAL captured calls from
`~/.cria/calls/` under a settings/wording matrix and scores with **cria's own parsers**, so a
question about a prompt or a setting costs minutes instead of a run.

| script | question it answers |
|---|---|
| `replay.py` | do these settings/wordings change tool-call validity, verdict readability, literal fidelity? |
| `sampling_probe.py` | can this model copy a long literal exactly? (per model, exact-match scored) |
| `ask_shape.py` | does a wording change hold across the whole fleet? (swaps models via systemd) |

Score with cria's real parser, never a lookalike, and never act on n<12 — both mistakes produced
false findings. See `docs/matrix-goal.md` for the full method and what is already settled.

**Evidence preservation (operator directive 2026-07-29):** every run archives its workspace to `~/.cria/suite/<run_id>/`; the row records `archive`, `capture_dir` (the per-call evidence), and `harness_log`. Nothing there is cleaned until reviewed — the logs are the raw material for the next round of cria improvements.
