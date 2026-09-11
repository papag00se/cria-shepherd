# Structural refusal must not enter ON_TRACK recovery

## Scope

This is a narrow control-flow repair to `loop.author_steer`. It does not change a prompt,
the diagnostic-action judge, any task-specific/API logic, the wheel-spin guard, or its factual
fallback. It neither runs nor evaluates the feed-pipeline task.

## Incident and provenance

The walked `feed-pipeline-java_ornith15_codex_poff_1789115104` event sequence identified
reasoner call 0049, recovery call 0050, and diagnostic-action call 0051. The immutable source
responses remain outside this repository at
`/tmp/feedwalk-1789115104/steer-recovery-candidate/archive/`:

| response | SHA-256 |
| --- | --- |
| `actual-0049-reasoner.response.json` | `d971b1014356abc515b28a2164e316b72419ef64e649be207a02275c4d6d6e71` |
| `actual-0050-steer-recover.response.json` | `991e41417605de95d91d8198804366e0343d6a5e1da7eec9dfb5f1ca64651c84` |
| `actual-0051-steer-code.response.json` | `5d520393a6026a03e46e1cb47de23623dedfe51032950a3a214a7ae21695f8d7` |

0049 contained several structural action units. Existing `_authored_action_or_none` emitted
`loop.steer_multiple_actions` and returned `None`; both `author_steer` paths then treated that
same `None` as the older ON_TRACK/empty case and asked `_steer_from_reasoning`. The recorded
0050 directive then reached 0051's existing diagnostic verdict funnel and the coder framing seam.
This establishes a provenance loss at the recovery seam, not that the model-authored repair was
wrong in substance or that it caused later task failures.

The checked-in JSON fixtures are portable JSON test copies of those responses. The patch format
adds only a terminal LF to each source file, so their bytes intentionally do not claim to be the
immutable archive; `json.loads` sees the same response objects. The archive above is the
byte-authoritative evidence.

## History and repair

`0daf06b` introduced answer-versus-reasoning recovery for genuine bare `ON_TRACK` replies.
`553b130` introduced the structural multi-action refusal. `d33d302` kept the existing focused
diagnostic-action judgment as the semantic owner. Their interaction erased the reason a reply had
been withheld.

`_authored_action` now returns the private typed outcome:

- `ACCEPTED`: one author action, unchanged downstream funnel;
- `NO_ACTION`: existing ON_TRACK/empty provenance, still eligible for recovery;
- `STRUCTURAL_REFUSAL`: an existing multi-action shape refusal, so recovery is not asked.

Both current `author_steer` paths derive the raw author answer before this classification. Only
the last state bypasses `_steer_from_reasoning`; accepted and genuine empty/ON_TRACK outcomes
retain their existing behavior. The old string-or-`None` wrapper had no independent production
consumer and is removed rather than retained for tests.

`guard_probe_steer` still returns `authored or canned`. The control replay therefore proves no
recovered **model-authored** directive, recovery/support call, or `loop.steer_outcome` follows a
structural refusal. It deliberately retains the pre-existing factual `spin_ground_truth` fallback
when `authored=False`; removing it would be a separate guard-policy change.

## Independent review correction and deterministic replay

The first scratch packet incorrectly cited four baseline failures because one merely showed the
new helper was absent. The independent reviewer rejected that proof. The corrected packet split
the helper check from an identical baseline-compatible behavioral file; the reviewer verified the
file hash and approved only this narrowed repair.

`tests/test_steer_structural_refusal_recovery.py` replays captured response objects through both
real `author_steer` branches and the real wheel-spin guard-to-coder seam with fake transports and
no executor. Before the repair, the test must observe `reasoner`, `steer-recover`, and
`steer-code`, the recovery/outcome events, and the captured directive in the coder-facing steer.
After the repair it observes only `reasoner` plus `loop.steer_multiple_actions`, no recovered
directive, and the existing factual fallback at the outer seam.

This is a deterministic captured-response control-flow regression. It is not a fresh model call,
an exact-wire replay, a backend inference, a task-code claim, or usefulness evidence. Skipping
0050/0051 after the structural rejection is the expected result; no replacement recovery/support
inference is needed.

## Verification record

The production-named behavioral test was copied byte-for-byte (SHA-256
`1cd508668f873dc769d7bb6f925e796d1e264ff3598535f473a1739733ba6b97`) into a fresh detached
`23bf901` worktree. It failed exactly as the incident predicts:

```text
3 failed, 5 passed, 8 subtests passed in 0.24s
```

The failures are both real `author_steer` branches reaching the captured `reasoner`,
`steer-recover`, and `steer-code` phases, plus the real wheel-spin seam framing the captured
recovery directive. There is no helper-absence expectation in that test.

The integrated branch then ran:

```text
python -m pytest -q tests/test_steer_structural_refusal_recovery.py \
  tests/test_steer_action_contract.py tests/test_answer_contradicts_reasoning.py \
  tests/test_every_authored_steer_records_its_outcome.py
37 passed, 20 subtests passed in 0.31s
```

That covers the captured structural refusal on both producing paths, the real guard-to-coder
seam, genuine ON_TRACK/reasoning recovery, ordinary supported action handling, empty output,
UNDECIDABLE handling, and the typed outcome contract.

Finally, `python -m pytest --junitxml=/tmp/feedwalk-1789115104/steer-recovery-candidate/integrated-full-suite.xml`
collected 4,862 top-level items and ended with JUnit `failures="0"`, `errors="0"`,
`skipped="5"`, `time="40.921"`. Its `<testsuite tests="8068">` attribute is a
pytest-subtests execution aggregate; parsing the XML yields 4,862 physical `<testcase>` records.
The counts are intentionally not compared to earlier runs or presented as a top-level growth.
