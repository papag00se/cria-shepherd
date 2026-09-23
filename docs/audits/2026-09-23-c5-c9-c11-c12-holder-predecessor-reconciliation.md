# C5/C9/C11/C12 holder-endpoint reconciliation — rejected

## Scope and method

This is a read-only reconciliation of the alleged recurring failure: a Handle
CLI uses the wrong response shape **and** never requests
`/holders/{holder}` for the holder-wide count. C5, C9, and C11 are frozen
terminal packets; C12 was deliberately stopped and is partial evidence only.
No GPU, service, task-contract, or fixture work was performed.

The decisive coder bodies, reasoning, and emitted calls were read in full
before assessing the workspaces. This matters because a final tree cannot say
whether a planner, a gate, or a prior body supplied the bad premise.

## Authoritative contract

The task requires the resolved address, holder address, and the number of
handles owned by that holder. The captured facts supplied to the coder say:

- `GET /handles/{handle}` supplies top-level `holder` and
  `resolved_addresses.ada`.
- `GET /holders/{holder}` supplies `total_handles`.

The checked-in OpenAPI fixture independently names the same fields and routes:
`tests/fixtures/api.handle.me_openapi.json`. Therefore neither a fixture change
nor a task rewrite is a valid remedy.

## Reconciliation

| cell | response-shape result | holder-count request | consequence |
| --- | --- | --- | --- |
| C5 | Correct: reads `resolved_addresses.ada` and top-level `holder`. | Correct: emits `/holders/${holder}` and reads `total_handles`. | Counterexample to the alleged recurring predecessor. Its terminal test is direct API access and incorrectly expects `holder_handle_count`, but that is a separate test defect. |
| C9 | Wrong: `resolved_addresses` is treated as an array and its length as the count. | Absent. | The only terminal cell containing both alleged implementation defects. |
| C11 | Correct resolved-address shape: `data.resolved_addresses.ada` and top-level `data.holder`. It instead invents/validates `holder_addresses` for the count. | Absent. | Counterexample to the response-shape conjunct. Its terminal test uses `child_process.execFile`, not a direct API fetch. |
| C12 | Partial script reads `handleData.resolved_addresses` rather than `.ada`, but it obtains the holder top-level and builds `https://api.handle.me/holders/${holderAddress}`. | Present. | Not terminal or comparable; nevertheless it independently falsifies the absent-holder-request conjunct. |

### C5 decisive chain

- Prompt/body: `/home/jesse/.cria/calls/20260922T184031-01a0cbeb-ed8d-79e2-bc59-4c484a4d2145/0053-coder-s1.prompt.txt`
- Reasoning and emitted write: `/home/jesse/.cria/calls/20260922T184031-01a0cbeb-ed8d-79e2-bc59-4c484a4d2145/0053-coder-s1.response.json`
- Terminal direct-API test write: `0088-coder-s2.prompt.txt` and
  `0088-coder-s2.response.json` in the same directory.
- Terminal workspace: `/home/jesse/.cria/suite/handles-cli-node_nemotron-elastic_codex_pon_1790127621/workspace`.

The model-visible `⟦ctx:facts⟧` body already names both response schemas. The
implementation response follows them: `body.resolved_addresses?.ada`,
`body.holder`, then `fetchJson(https://api.handle.me/holders/${holder})` and
`holderBody.total_handles`. No planner or gate transformation precedes that
write with an opposite schema or route.

### C9 decisive chain

- Prompt/body: `/home/jesse/.cria/calls/20260922T223047-01a0ccbe-bd02-78c3-811b-336d1073818b/0219-coder-s3.prompt.txt`
- Reasoning and emitted direct-fetch test: `0219-coder-s3.response.json` in the
  same directory.
- Terminal workspace: `/home/jesse/.cria/suite/handles-cli-node_nemotron-elastic_codex_pon_1790141421/workspace`.

The earlier C9 owner is already recorded separately: a later planner coverage
transition accepted a direct upstream API request as E2E immediately before
this test write. That transition can explain the test route, but it occurs
*after* the bad response-shape/no-holder-request implementation and cannot be
its predecessor. It is not a common owner for this reconciliation.

### C11 decisive chain

- Implementation prompt/body: `/home/jesse/.cria/calls/20260923T003055-01a0cd2c-b917-7823-9e6f-95f277c32f5f/0069-coder-s3.prompt.txt`
  and `0069-coder-s3.response.json`.
- Test prompt/body: `0095-coder-s1.prompt.txt` and
  `0095-coder-s1.response.json` in the same directory.
- Terminal workspace: `/home/jesse/.cria/suite/handles-cli-node_nemotron-elastic_codex_pon_1790148627/workspace`.

The body contains an actual fetched Handle response with top-level `holder`
and an object-valued `resolved_addresses.ada`. The implementation response
nevertheless adds a `holder_addresses` array condition and derives its length.
That is a missed grounding opportunity, but it is not a wrong
`resolved_addresses` shape. The test response uses `child_process.execFile`;
it does not make the direct upstream request alleged for C5/C9.

### C12 planner/body/gate trace

- Planner result: `/home/jesse/.cria/calls/20260923T011609-01a0cd56-2206-7a13-9bd3-8d7dd615d642/plan-20260923T081808-c96d8943.md`.
- Coder read before its later test write:
  `0035-coder-s1.prompt.txt`, `0035-coder-s1.reasoning.txt`, and
  `0035-coder-s1.response.json`.
- Last attempted test write:
  `0037-coder-s1.prompt.txt`, `0037-coder-s1.reasoning.txt`, and
  `0037-coder-s1.response.json`.
- Partial workspace:
  `/home/jesse/suite-runs/suite-handles-cli-node_nemotron-elastic_codex_pon_1790151342-3vjsvovq`.

The planner explicitly specifies the two-request flow: read
`resolved_addresses.ada` and `holder`, then call `/holders/<holder>` for
`total_handles`. The later coder body has no gate acceptance of a terminal
result: its sole attempted test write cannot create `test/lookup.test.js` and
the run was stopped. The partial `lookup.js` does build the holder route.
Thus C12 cannot strengthen the C9-only defect into a repeated terminal event,
and it supplies no planner or gate transform that reverses the route.

## Decision

No single exact cria-owned predecessor exists across the comparable relevant
runs. C5 disproves both conjuncts; C11 disproves the response-shape conjunct;
C12 (non-comparable) independently disproves the absent-holder-request
conjunct. C9 alone has the combined defect.

No candidate, capture-shaped code change, test, fixture change, task-contract
change, GPU run, or service restart follows. A Handle-field or test-verb
pattern would be a task-specific deterministic judgment and would contradict
the counterexamples. The prior C9 E2E coverage repair remains valid only for
its own later planner transition; this reconciliation invalidates any claim
that it addressed a recurring response-shape/holder-endpoint predecessor.
