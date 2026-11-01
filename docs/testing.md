# Testing

`nice -n 19 python -m pytest -q tests` runs the whole suite (about 5,000 collected cases; a couple of minutes on the development box). Run ONE pytest process at a time (never `-n`): the suite shares the machine with model servers, and the test scratch is a per-session directory that `conftest.py` removes at exit, so do not override it. Use focused files while working and the whole suite before a commit. It is small on purpose: a test earns its place only by being able to fail for a real reason. The standard is the global test-refactor process (`~/.agents/processes/test-refactor.md`): minimum test machinery, maximum protection.

## Layout

Tests live in `tests/<domain>/test_<domain>_<subject>.py`. Domain directories and what they own:

- `loop_guards`, `loop_orientation`, `loop_planner`, `loop_rest`, `loop_main`: the coder loop (runaway-reasoning guards, reorientation, planning-off policy and the plan-off driver, steering, the `Loop` contract).
- `gates_completion`: completion gates, check evidence, gate transport.
- `context_wire_a`, `context_wire_b`: the final-wire fit and floor, Chat/Responses translation, text-call recovery.
- `compaction_handoff`: self-compaction, the measured compaction predicate, briefing lenses, survey truth.
- `read_multipart`: reads, multipart paging, transport receipts, the image workflow.
- `write_edit`: write and edit lowering, sequencing, shrink protection, assist contracts.
- `shell_safety`: the shell backstops (bounded backstops, not a parser or sandbox).
- `research_discovery`: fetch/search, discovery and language checks.
- `server_config`: HTTP handlers, config, sessions, retention.
- `suite_tooling`: the evaluation suite's own safety and provenance rules.
- `misc_runtime`: system1 runtime, usage reporting, native-protocol and transport pieces.
- `structure`: the legitimately structural invariants (import graph, bound lints, prompt hygiene, wire keys, the generated assist inventory, walk docs).

File and helper names are prefixed with their domain and must be globally unique (the structure suite checks it).

## Rules for a test here

- **Extend before adding.** Find the test that owns the behavior and extend or parameterize it. A separate test needs a distinct contract, failure mode or integration risk.
- **Inputs from incidents.** A regression is a row in a table with the incident named in the docstring ("ornith1.5_9b / Java run 1: ..."), not a new function.
- **No tautologies, no source-text change-detectors.** Reading source or prompt text is allowed only in `tests/structure/`, where the claim is about code organization itself.
- **Fakes only at external boundaries** (model server, network, clock, GPU, harness). Use real PTY/bash/HTTP where execution or wiring is the contract.
- **A test must be seen to fail.** For a new assertion, break the code in a scratch copy (never in the shared checkout) and watch it fail for the expected reason.
- **Every fix still needs a fails-before / passes-after test** (repo AGENTS.md). Put it in the owning domain, as a row where a table exists.

## The pre-reset suite

On 2026-10-31 the suite was rewritten at about 10% of its size (from 855 files / 157K lines / 9.2K definitions / ~13.8K collected cases to about 15K lines), then widened with scenario tests aimed at the lines the cut had lost (see below). The old files are preserved unchanged in git as the tag `tests-before-reset-20261031` (pushed to origin); they are no longer in the working tree. Use them as a guide to corner cases we struggled with: `git grep -n <subject> tests-before-reset-20261031 -- tests` before changing it, `git show tests-before-reset-20261031:tests/<file>.py` to read one, and copy the incident into a new table row rather than the test.

Assist declarations in `cria/*.py` list regression tests in `regressions=` and `SourceOwner(...)`. Where a new test covers the assist those entries point at it; where none does they point at the preserved file as `tests-before-reset-20261031:tests/<file>.py`. The assist-inventory builder resolves such a reference through `git show`, so a mistyped one fails loudly, and the report marks it *(archived)*. An archived entry is an assist whose regression is not protected by the live suite: write the new row when you next touch that assist, and repoint the entry.

## What the reset measured

**Size at reset** (tracked `.py` under `tests/`, `def test_`): 183 files, about 20.1K lines (12.8% of the old 157K), 909 definitions (9.9% of 9,188), 2,248 executed cases (old: ~13.8K collected), about 85 seconds (old: about 11.5 minutes). **Size now** (2026-11-01, after the scenario and coverage waves): 327 files, about 36.6K lines, about 1,670 definitions, 5,163 collected cases (`pytest tests --collect-only -q`). The number drifts every wave; re-measure rather than trust a figure here.

**Coverage** (coverage.py in a scratch virtualenv, `--branch --source=cria`; the project itself stays stdlib-only):

- old suite: 94.4% lines / 88.5% branches (with 94 stale failing tests whose lines still ran);
- first rewrite (about 10%): 80.2% / 68.1%;
- after the scenario pass: 87.0% / 77.3%;
- after the wave-9/10 coverage passes (2026-11-01, about 3,720 tests at the time): **93.4% lines / 86.9% branches**.
- On 2026-11-01 the ~3,000 tests added by waves 9-16 (coverage, mutation and audit tests and per-fix tables, 43,347 test lines) were deleted again: the suite is back to about 3,480 tests / 26,800 lines. The coverage figures above were measured on the larger suite; the suite is meant to stay small, so do not add tests unless asked.

How to re-measure: install `coverage` in a throwaway venv, copy the working tree to a scratch directory under `/var/tmp` (some tests need a git repo and a writable tmp, and two retention tests only pass in the real checkout), run `coverage run --branch --source=cria -m pytest tests`, then `coverage json`, then delete the copy. It runs the whole suite: do it rarely.

The remaining gap is concentrated in `loop.py`, the planner family (retired: planning is off by policy), `groundedaction`, `returnedpolicies`, and a few fixture-hungry corners. `system1` now has real-ONNX and runtime tests under `tests/misc_runtime`. Several modules keep their real logic as shell and Python programs inside strings that run in subprocesses; coverage cannot see those, so they are exercised by real PTY/bash execution instead.

**Protection was checked three ways.** Mutation: each rewriter broke the code in a scratch copy and recorded how many representative defects the new tests caught (roughly 1,200 tried; survivors were strengthened or judged equivalent). History replay: 65 recent real bug fixes were reversed one at a time; of the 28 misses compared with the old suite, the old suite had caught 25 (real losses) and 7 were never tested; every loss was restored except two (a planner-only log field and a pure refactor). Coverage: the lines the old suite reached and the new one did not were mapped per module and recovered with whole-flow scenario tests (a test may drive a real multi-step flow as long as it asserts real outcomes and was seen to fail under mutation).

`planner_tools` (planner off by policy) was deliberately skipped; `preamblepolicy` (inert since `9fd01656`) was deleted. Real source defects found while rewriting are recorded as `xfail(strict=True)` tests; a strict xfail goes red when the defect is fixed, which is the cue to delete the marker. Regressions in the old suite that the new one does not cover live only in the tag: search it (`git grep`, above) before changing the assist.

## Hostile-command tables never execute

Guard and evasion tests (`dirguard`, `shellinput`, cleanup analysis) pass the command **string** to the function under test (for example `dirguard.kill_refusal(command)`); they never run it through a shell, stub it on `PATH` or "dry run" it. `kill`, `exec`, `trap`, `cd` and `eval` are shell builtins that no `PATH` stub can neutralise, and `bash -c 'kill -9 -1'` once killed the whole user session. A new row in such a table must be a string and an expected refusal, nothing else.
