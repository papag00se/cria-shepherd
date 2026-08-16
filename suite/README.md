# Test / performance matrix suite

One matrix cell per `run.py` invocation: task × model × harness × planner, under a HARD 30-minute wall (no call budget — slow models surfacing as budget-kills is signal). Each run appends one JSON row to `results/results.jsonl`; `report.py` renders the matrix.

- Success is decided ONLY by the task's `verify.py` — deterministic, outside the session, runs the deliverables itself (unit tests, LIVE test with real-data evidence, CLI, README). Never the model's claim, never a judge verdict, never a green gate.
- Tasks pin their language (`meta.toml`); the battery covers shapes, not a language×task cross.
- cria must NEVER special-case a suite prompt (doctrine) — the suite doubles as cria's regression harness: run the fixed sub-matrix before/after cria changes.
- Metrics per row: wall time, terminal state (exited / budget-killed / crashed-early), verifier score + per-part detail, calls by phase, avg output tok/s (timed calls), assist events by kind (from cria's rlog), workspace path.

## Tasks

Two families. **Greenfield** tasks start from an empty directory and test research + creation. **Seeded** tasks ship existing code in `tasks/<task>/seed/` (copied in and committed before the run) and test the machinery most of cria's measured footguns live in: reading a file it did not write, editing it surgically, and reading its own gate output.

### Seeded — start from existing code

| task | language | category | how it is scored |
|---|---|---|---|
| `failing-tests-py` | Python | 3 · resolve failing tests | suite green + tests byte-identical + hidden contract |
| `bug-report-go` | Go | 2 · fix a bug from a user report | reported case fixed + hidden cases + no regression |
| `missing-tests-py` | Python | 4 · write missing unit tests | **mutation score** — seeded bugs its tests must catch |

Every seeded verifier is built to make the easy cheats worthless, and each was checked against a real cheat before being trusted:

- weakening or deleting the failing test → `tests_intact` false (hashes against the seed)
- special-casing the visible numbers → hidden cases at inputs the model never saw
- `assert True` × 20 → mutation scoring; a shallow suite scored 2/4 (29% of seeded bugs caught), a thorough one 4/4

### Greenfield

| task | language | toolchain the verifier needs |
|---|---|---|
| `ada-handles` | Python | python3 + pytest |
| `handles-go` | Go | go |
| `handles-rust` | Rust | cargo |
| `handles-node` | JavaScript | node (npm) |
| `handles-ruby` | Ruby | ruby + rspec |
| `handles-php` | PHP | php + phpunit |
| `handles-java` | Java | mvn |

The `handles-*` battery is deliberately the SAME problem in every language: the matrix varies one thing at a time, and this axis is the language. Shape variation (SQL, multi-module, needs-search) is a separate axis added as its own tasks. A missing toolchain scores the cell `toolchain: not installed` rather than a silent zero.

**Liveness is checked with `unshare -rn`** — an unprivileged network namespace with no interfaces. That is the only block that works for every language's HTTP client: Go and Ruby honour proxy environment variables, PHP's curl often does not, Java ignores them entirely. `go test` also needs `-count=1`, or it replays a cached pass without running anything and a genuinely live test scores as mocked (caught by running the verifier against a known-good solution).

Phase 0: codex × {ternary-bonsai, qwythos} × ada-handles. Planned: harness adapters (Claude Code, OpenCode, Gemini CLI, Cline), tasks (SQL/Go, multi-module/TS, needs-search/Rust, CLI/Java), N≥2 repeats on headline cells.

## Offline harness — ask before you burn a run

A run costs 30 minutes and yields one noisy number. `replay.py` re-sends REAL captured calls from `~/.cria/calls/` under a settings/wording matrix and scores with **cria's own parsers**, so a question about a prompt or a setting costs minutes instead of a run.

| script | question it answers |
|---|---|
| `replay.py` | do these settings/wordings change tool-call validity, verdict readability, literal fidelity? |
| `sampling_probe.py` | can this model copy a long literal exactly? (per model, exact-match scored) |
| `ask_shape.py` | does a wording change hold across the whole fleet? (swaps models via systemd) |

Score with cria's real parser, never a lookalike, and never act on n<12 — both mistakes produced false findings. See `docs/goals/matrix-goal.md` for the full method and what is already settled.

**Evidence preservation (operator directive 2026-07-29):** every run archives its workspace to `~/.cria/suite/<run_id>/`; the row records `archive`, `capture_dir` (the per-call evidence), and `harness_log`. Nothing there is cleaned until reviewed — the logs are the raw material for the next round of cria improvements.
