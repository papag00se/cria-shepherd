# L5 post-walk fix replays — 2026-09-04

The fixes in this unit were replayed against the exact post-`d33d302` Java and Go call artifacts. Failed-run workspaces were read only.

## Reasoner replays

`/tmp/replay_postfix_real_calls.py` rebuilt the new `steer_diagnostic_action` prompt from the captured directive/check prompt and the exact author prompt that carried its task/workspace grounding, then asked the live `nemotron_elastic_12b_a2b_q4km` endpoint.

| Case | Captured source | Old | New |
|---|---|---:|---:|
| Task- and disk-grounded `discounts.json` action | Go `0021-reasoner.prompt.txt`, `0022-steer-code.prompt.txt` | `UNSUPPORTED` | `SUPPORTED` |
| Refuted Java `<scope>compile</scope>` action | Java `0041-reasoner.prompt.txt`, `0042-steer-code.prompt.txt` | empty/cut, then withheld by no-reason retry | `CONTRADICTED` |
| Checker-prescribed Go module action with incidental `go.mod` token | Go `0110-reasoner.prompt.txt`, `0111-steer-code.prompt.txt` | whole-action `SUPPORTED`, later token veto | `SUPPORTED` in one judgment |

All three expected outcomes passed. Machine-readable output: `/tmp/postfix-real-call-replay.json`.

## Deterministic replays

`/tmp/replay_structural_real_calls.py` replayed exact captured payloads and the failed-run workspace:

- Go `0203-coder-s1.response.json`: removing the versioned require now returns `mode=close`, never the false `phantom` / “This change is DONE” result.
- Go `0017-coder-s1.response.json`: all 1,488 bytes of the rejected whole-file draft survive in the explicitly labelled rejected-candidate block.
- Java `0154-coder-s1.json`: under a forced 12K window fit that dropped 53 turns, the exact original task remained present through the session-pinned task hint.
- Go failed workspace: a fresh bounded survey was accepted with `complete=false` (`9,260` bytes), rather than rejected for declared/arrived entry-count mismatch.

Machine-readable output: `/tmp/postfix-structural-replay.json`.

## Suite

```text
4832 passed, 7 skipped, 3183 subtests passed
```
