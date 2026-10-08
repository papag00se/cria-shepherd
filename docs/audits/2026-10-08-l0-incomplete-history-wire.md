# L0 incomplete historical tool arguments — native wire repair

Operator: repair every infrastructure failure and obtain a successful, independently judged run (including an honest0%) before proceeding to the next cell. Failed attempts remain immutable and unscored; matrix cells contain no status/provenance words.

## Authoritative incident

Original attempt `feed-pipeline-java_ornith1.5_9b_codex_poff_1791419572`, source115b699d, ended `harness-error`. Calls are retained at `~/.cria/calls/20261007T173257-01a118ed-73a7-78d1-aa0e-ee081e9b986d/`; archived workspace and original result row are preserved. The15-active-minute35%/continue judgment is a checkpoint, not a final.

Read the complete last rejected request, including every message, as lossless parts under `~/.cria/validation/l0-ornith-feed-blocker/0250-full-request-part-*.txt`, plus the native reply. It is a tool-free **Codex-owned context compaction** request, not an ordinary coder turn. Its history includes an incomplete `exec_command` argument and the harness's real argument-parse failure result.

Native `0244-proxy.response.json` reports finish_reason`length`:48935prompt+217completion=49152native context, and contains one complete call and a second incomplete call. No separate reasoning field is present. Codex accepted the complete call, rejected the incomplete one, and then attempted compaction. Native history rendering reparses historical argument JSON even without a tool menu; the unfinished string produced HTTP500 before generation. The original rejected error is captured in0250-proxy.response.json (unlike the earlier shipping error whose raw body was unavailable).

## Repair, not invented command recovery

`Upstream._prep` is the final serialization boundary. Every malformed historical argument is now representable there. At L0 it is serialized as a valid object with the sole `_unparsed` field containing **every original argument character**; tool ID/name, linked result, other calls, and all valid argument bytes remain unchanged. No missing quote/command is invented, no fresh tool is executed, no prompt directive is added, no context floor or planner is enabled. L1 retains its existing argument recovery; L0 explicitly never invokes those recovery functions. This changes malformed historical wire representation and is disclosed as a new revision boundary, not byte identity or full transparency certification.

One prior infrastructure failure prevented a second explicit repair transition. The resume path now shares the reconciliation path's exact prior-failure validation (cohort, row identity, immutable digest, source/fleet/capture evidence); it retains that prior receipt unchanged, without judging or relaunching it. A changed/missing/duplicate prior row still fails closed. Operational supervision, not a failed row, decides when a separately authorized successful replacement permits the main serial driver to continue.

The first guardian invocation exposed a separate evidence-validation mismatch before it could launch any inference: the shared capture validator required a successful choices/message reply even when validating an **unscored infrastructure failure** whose retained response is a structured native error. Failure-only validation now explicitly admits hashed structured error objects while retaining all original request/response identity, sampling, phase/count and shutdown checks. Default validation and ordinary scoreable rows still reject those replies. The error evidence is neither discarded nor relabeled successful; the original row remains unchanged. A dedicated positive regression fails before the opt-in and passes after it, with negative cases for opaque/empty errors and changed response digests.

## Proof

- Pre-fix L0 history behavior reproduced by disabling its formerly absent envelope: malformed history tests fail, and real pinned Codex0.159.3 fails during fake-native compaction; all corresponding repaired cases pass.
- Real pinned harness/fake backend: length-ended second call reaches harness as incomplete, complete first call executes, compaction receives valid lossless historical JSON, and session exits successfully without reconnect loops. No GPU/network model inference in the test.
- Native CPU-only `/apply-template` replay of the exact original request: original HTTP500, lossless representation HTTP200. Both responses, exact repaired wire and hashes are in `native-template-replay.json` and `apply-template-*.json` under the incident evidence root. No sampling or model asset changed, and no generation was requested.
- Focused suite35passed; separate massage/ladder/context suite95passed and22subtests. Full suite results are recorded in the completion receipt after validation; the historical19missing-evidence failures are not removed or fabricated.

Repair evidence does not itself establish a successful feed coding result. The authorized fresh rerun must receive its own natural final and independent usefulness judgment before any subsequent cell runs.
