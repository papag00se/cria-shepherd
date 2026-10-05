# ornith1.5_9b feed importer: recovered evidence disposition

Reviewed 2026-10-05. The original draft is preserved unchanged in `4d52df02`;
its SHA-256 and the review method are in the
[shared evidence review](recovered-evidence-review.md). The filename and stored
run ID retain their historical `ornith15` spelling; the current project identity
is **ornith1.5_9b**.

**Status:** the authentic harness log, retained ledger and existing dependency-cache
repair support a concrete cria-side access defect. Exact historical coder and
reasoner call captures and workspace snapshots are missing. This is an evidence
disposition, not a complete cria call WALK or a new usefulness assessment.

## Exact provenance

- Run: `feed-pipeline-java_ornith15_codex_poff_1788684045`.
- Missing native captures:
  `~/.cria/calls/20260906T014056-01a075e0-b65b-7732-95a8-780ba197075d/`.
- Missing final workspace:
  `~/suite-runs/suite-feed-pipeline-java_ornith15_codex_poff_1788684045-ydw_f2fy`.
- Missing archive/milestones: the exact `1788684045` prefix under `~/.cria/suite/`
  and `~/.cria/suite/_milestones/`.
- Surviving harness log:
  `/home/jesse/src/cria-shepherd/suite/results/feed-pipeline-java_ornith15_codex_poff_1788684045.log`.
  Original size: 799,828 bytes. SHA-256:
  `5b63c8da721db94d5f707c45f346f35a812324cfa76c193cab3ce030b048a61a`.
  All bytes were read privately; they match the original reconciliation tar member.
- Exact row in `suite/results/results.jsonl`, excluding its line terminator:
  SHA-256 `cc2c9b9aaeaeb06108c828706d6b7d8766798e46739ad93f88861278947ece89`.

The retained row reports 35% usefulness, 101 calls, planner off, and
`milestone-stalled-45min`. These are stored metadata, not fresh measurements.
It marks this run superseded by `1788907072` after the dependency-cache fix.
Neither the later score nor a causal improvement is revalidated here: the rerun
has not been walked against complete primary evidence.

## Surviving evidence changes the diagnosis

The complete harness transcript contains dependency-cache access refusals while
the coder was trying to inspect OpenCSV, invalid API names in the ongoing work,
and a later successful classpath-based `javap` action. The defect to investigate
is cria preventing access to the facts needed for an executable next action.
The draft's emphasis on a reasoner failing to supply an implementation from its
own knowledge does not establish the root cause.

The relevant late tool result is around harness-log lines 11519–11542. It exposes
`CSVReaderBuilder(java.io.Reader)`, `withSkipLines(int)` and `withCSVParser(...)`.
This is real library-signature evidence for the reader construction/header path.
The parser command in the same action is filtered through `grep`; the record
does **not** provide the complete `CSVParserBuilder` method inventory printed in
the draft. A filtered absence is not a full API listing. Nor does this record
establish which other CSV library supplied a remembered method name.

No subsequent harness `exec` section follows the final denied action; the log
ends with reasoning. That limits what the transcript demonstrates about a later
repair. The missing final workspace prevents a fresh compilation or a verified
claim about its terminal source bytes. The ledger's judgment describes remaining
reader-lifetime, parallelism, malformed-row and review problems; those are
historical judgments, not newly executed checks.

Private reasoner calls 0060/0091, per-call reasoning-token counts, exact denial
attempt totals and the draft's cross-library causal explanation cannot be
validated from this harness transcript. They remain unverified. Its line numbers
are transcript locations and must not be substituted for missing capture IDs.

## Existing repair and reproducible current disposition

Commit `a00ce458dca72534e5af07500b873d1f8fe56a3f`, already in the reviewed main
ancestry, changed `cria/dirguard.py` to allow reads of dependency-artifact
subtrees even at external-directory permission `none`. It preserved refusal of
credential-bearing configuration roots and external cache writes. Later cache-root
guidance names a readable artifact location while distinguishing a path refusal
from a network limitation.

The actual pre-fix `dirguard.py` was loaded privately into an isolated Python
module and compared with current production code. The same `javap` command over
the resolved OpenCSV 5.9 jar was refused by the pre-fix code and allowed by
current code. No workspace, jar or service was modified or executed. This verifies
the code repair; it does not reconstruct all historical messages or prove task
completion.

Existing regressions cover that grounding command, local extraction of a
dependency jar, other artifact caches, continued credential-root and cache-write
refusals, and a command that combines a dependency read with an external write:
`tests/test_a_dependency_jar_is_readable_ground_truth.py`.
`tests/test_a_refused_cache_root_is_not_read_as_offline.py` covers the truthful
readable-subtree guidance. These tests validate the access invariant without a
model server or fabricated capture.

## Disposition of the draft's symbol-probe proposals

| Proposal | Current source-grounded disposition |
|---|---|
| Automatically run `javap` after uncertainty phrases | Not implemented by this review. A guessed phrase classifier is not a semantic finding. First ensure the coder can perform the evidence-gathering action; the access defect already has an upstream repair. |
| Require the reasoner to run shell and prescribe a signature | Current `steer_diagnose.txt` restricts the supervisor to read-only `read_file`/`list_dir`; it cannot run shell or fetch dependencies. Harness probes are asynchronous. Exact checker evidence remains separate from authored actions, and implementation choice stays with the coder/task. |
| Block the coder until an external-symbol probe succeeds | Not justified by a missing full WALK, and no first-attempt veto was added. A reasoner with insufficient reach must abstain rather than declare a provider's complete API from workspace files. |
| Extend `_shared_symbols` / `steer_symbol_status` as the active guard | Those helpers remain in source, but the active `_vet_steer` path uses `_diagnostic_action_verdict` to judge the whole action against current checker/refusal facts. It does not use a second shared-token provider veto after that judgment. |

`steer_diagnostic_action.txt` explicitly forbids establishing an external API
from memory. Unsupported, contradicted, unrelated or undecidable optional guidance
is withheld. The existing whole-action regression is
`tests/test_the_steer_must_match_the_current_diagnostic.py`.

The remaining investigation question is whether an executable grounding action
reaches the coder early enough and whether its evidence survives context shaping.
Recover the exact full captures, structured events and workspaces to answer it.
The surviving sources warrant preserving this access-defect finding and its
already-landed repair; they do not warrant claiming the proposed automatic
symbol-probe mechanism has been measured or implemented.
