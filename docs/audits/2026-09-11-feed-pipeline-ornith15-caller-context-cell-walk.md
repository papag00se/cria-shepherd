# Feed-pipeline Ornith 1.5 caller-context cell — full-prompt walk

## Scope and method

This records the causal-closure review of the frozen L5 cell
`feed-pipeline-java_ornith15_codex_poff_1789141408`, launched at `87d620e` with
unchanged task, model, harness, planner, and sampling. Its archive and capture
were first copied read-only to `/tmp/ornith-feed-causal-closure/`.

`python3 suite/walk.py /tmp/ornith-feed-causal-closure/capture --full-prompts --out
/tmp/ornith-feed-causal-closure/full-walk` materialized 92 calls in 79 chunks.
The sequential EOF ledger is retained outside the workspace at
`/tmp/ornith-feed-causal-closure/20260911T084338-full-prompt-walk-ledger.md`.
It names every `chunk01.txt` through `chunk79.txt`, including every oversized
chunk, with its final physical line and byte offset; all are marked read through
actual EOF. No prompt prefix was removed.

The final independent usefulness record was made against a separate private copy
of that frozen archive. `mvn -q -o compile` fails with five `Importer.java`
errors, including nonexistent `sku`, a `String` passed to `LongAdder.add`, two
incompatible entry types, and nonexistent `LongAdder.summarize()`. The final
source still uses `line.split(",", -1)` even though `pom.xml` declares OpenCSV
5.9, and `REVIEW.md` is absent. The recorded independent judgment is 10%; it is
not a causal claim about `87d620e`.

## Disposition

No shared cria-owner defect is demonstrated by this cell. The shipped owner at
`87d620e` only suppresses an otherwise byte-identical immediate compactor retry
after the wire owner has already parsed a context rejection; it neither supplies
coder content nor changes a coder request that differs at the wire.

The latest causal end state is model-authored failure, not an observed cria
injection chain. In original capture `0091-coder-s1.reasoning.txt`, after the
rumination guard reports a 16,389-token second-guessing stream, the coder itself
proposes a whole replacement and repeatedly re-derives an invalid Java design.
The matched `0092-coder-s1-focus1.response.json` then asks to re-read baseline
data rather than repair the visible compiler failures. The final source contains
that design's direct defects. This is a capability/rumination outcome, but the
capture does not show the guard wording causing it.

The only nearby candidate context artifact was checked against the original
capture rather than inferred from the walk: `0089-self-compact.response.json`
accurately reports the then-current compiler errors and explicitly says no work
is verified; `0090-compaction-validate-retrospective.response.json` returns
`PLAN`, so that candidate was rejected rather than promoted as a briefing.
Therefore it cannot establish an A→B→C path to the later coder behavior.

No repair, replay, service restart, or fresh cell follows from this review. A
fresh unchanged cell is not warranted for this disposition: the one current cell
shows no new shared-owner defect, and the existing `87d620e` transport repair
already has its qualified control-flow coverage. Any future cell must be
supervisor-authorized and run only after an independently demonstrated owner
change.
