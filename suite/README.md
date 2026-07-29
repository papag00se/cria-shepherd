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
