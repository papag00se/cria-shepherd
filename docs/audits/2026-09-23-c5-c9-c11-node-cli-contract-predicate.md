# C5/C9/C11 Node CLI contract predicate — rejected

## Question

This is a frozen, read-only assessment of the proposed common predicate:

> Each terminal Node CLI implementation derives the Handle response shape and
> holder count incorrectly **and** its purported live end-to-end test calls the
> Handle API directly instead of spawning the CLI.

The predicate is false. It cannot justify a cria assist or a suite task/fixture
change.

## Ground truth supplied to every coder

The task itself requires a CLI to print the resolved address, holder address,
and number of handles owned by that holder; it specifically requires a real
request that verifies the tool end to end:

- `suite/tasks/handles-cli-node/prompt.txt`

The frozen model-visible facts in C5 name the authoritative objects exactly:
`GET /handles/{handle}` returns `holder` and
`resolved_addresses.ada`; `GET /holders/{address}` returns `total_handles`.
They are in the complete prompt capture:

- `/home/jesse/.cria/calls/20260922T184031-01a0cbeb-ed8d-79e2-bc59-4c484a4d2145/0053-coder-s1.prompt.txt`
- `/home/jesse/.cria/calls/20260922T184031-01a0cbeb-ed8d-79e2-bc59-4c484a4d2145/0088-coder-s2.prompt.txt`

The checked-in captured OpenAPI fixture independently has the same contract:
`/handles/{handle}` references `Handle`, whose `resolved_addresses` is an
object with `ada`; `/holders/{address}` references `Holder`, whose
`total_handles` is the holder-wide count:

- `tests/fixtures/api.handle.me_openapi.json`

Thus the task contract and fixture already provide deterministic facts. There
is no missing shape, endpoint, or E2E definition for a fixture correction to
supply.

## Frozen terminal evidence

| Cell | Terminal implementation | Terminal test | Result |
| --- | --- | --- | --- |
| C5 (`1790127621`) | `workspace/lookup.js` reads `body.resolved_addresses?.ada`, takes `body.holder`, then calls `/holders/${holder}` and reads `holderBody.total_handles`. | `workspace/test/real.test.js` fetches only `/handles/example` and asserts invented `body.holder_handle_count`. | The E2E half is absent/direct, but the implementation's response-shape and holder-endpoint derivation are correct. |
| C9 (`1790141421`) | `workspace/lookup.js` treats `resolved_addresses` as an array and sets the count to `resolved_addresses.length`; it does not call `/holders/{holder}`. | `workspace/test/integration-test.js` directly calls `global.fetch(URL)` for `/handles/goose`. | Both proposed defects occur in this one archive. |
| C11 (`1790148627`) | `workspace/lookup.js` correctly reads `data.resolved_addresses.ada` and `data.holder`, but rejects the response unless `holder_addresses` is an array and reports its length rather than calling `/holders/{holder}`. | `workspace/tests/lookup.test.js` uses `child_process.execFile('node', args, ...)`; its body makes no direct API call. | Holder-count derivation is wrong, but the direct-API-test conjunct is false. The spawn arguments are themselves invalid (`['node', 'lookup.js', ...]`), so the test is not runnable E2E; that does not turn it into a direct API test. |

The terminal workspaces are preserved at:

- `/home/jesse/.cria/suite/handles-cli-node_nemotron-elastic_codex_pon_1790127621/workspace`
- `/home/jesse/.cria/suite/handles-cli-node_nemotron-elastic_codex_pon_1790141421/workspace`
- `/home/jesse/.cria/suite/handles-cli-node_nemotron-elastic_codex_pon_1790148627/workspace`

## Full capture provenance

The terminal actions and their reasoning were read from these complete frozen
coder prompt/response pairs. The response captures contain the corresponding
full reasoning and emitted tool call.

- C5 implementation: `0053-coder-s1.prompt.txt`, `0053-coder-s1.response.json`
- C5 terminal test edit: `0088-coder-s2.prompt.txt`, `0088-coder-s2.response.json`
- C9 direct test write: `0219-coder-s3.prompt.txt`, `0219-coder-s3.response.json`
- C11 implementation write: `0069-coder-s3.prompt.txt`, `0069-coder-s3.response.json`
- C11 terminal test write: `0095-coder-s1.prompt.txt`, `0095-coder-s1.response.json`

All are under their matching capture directories in `/home/jesse/.cria/calls/`:

- `20260922T184031-01a0cbeb-ed8d-79e2-bc59-4c484a4d2145`
- `20260922T223047-01a0ccbe-bd02-78c3-811b-336d1073818b`
- `20260923T003055-01a0cd2c-b917-7823-9e6f-95f277c32f5f`

C5's response `0053` explicitly emits the correct holder-endpoint flow after
the model-visible schema described it. C5's response `0088` explicitly edits
the direct API test to expect the non-contract `holder_handle_count`. C9's
response `0219` emits the direct `global.fetch(URL)` test. C11's response
`0069` emits the `holder_addresses` validation/length derivation despite the
prompt's fetched response showing no such field, while response `0095` emits
`child_process.execFile` rather than a direct fetch.

## Decision

No assist is added: a language/task-specific detector for Handle field names
or test verbs would violate the deterministic-facts/reasoner boundary and
would not match C5 or C11. No suite contract or fixture is changed: the frozen
prompt and OpenAPI facts were already sufficient. A reasoner could judge a
future, independently observed mismatch from freshly gathered authoritative
schema and actual test execution, but this rejected cross-cell predicate
supplies no architecture-fitting trigger or remedy.
