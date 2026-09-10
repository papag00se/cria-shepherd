# feed-pipeline-java × Ornith 1.5 — rejected-rerun full walk

Date: 2026-09-10

Run: `feed-pipeline-java_ornith15_codex_poff_1788996499`

Capture: `20260909T162829-01a08880-60be-7342-9918-4cb287cd565d`

Terminal result: 30% useful, `milestone-stalled-45min`, 124 model calls

## Method

`suite/walk.py --full-prompts` materialized all 124 calls into 102 ordered chunks: 128,572 lines and 7,182,129 bytes. Four Codex 5.6-Sol/max walkers read disjoint ranges strictly from the first line through EOF, including every repeated prompt and every oversized continuation. They did not grep, search, sample, deduplicate repeated context, or script-summarize it.

Reports and per-chunk ledgers are preserved outside the repository at:

- `/tmp/feedwalk-1788996499/findings-1.md` and `progress-1.txt` — chunks 001–026
- `/tmp/feedwalk-1788996499/findings-2.md` and `progress-2.txt` — chunks 027–052
- `/tmp/feedwalk-1788996499/findings-3.md` and `progress-3.txt` — chunks 053–077
- `/tmp/feedwalk-1788996499/findings-4.md` and `progress-4.txt` — chunks 078–102

Every material finding below was checked independently against the original per-call prompt, response, and reasoning capture. Subagent interpretations were not taken as verdicts.

## Result in one paragraph

The coder originated the broken Java: it did not launch workers, discarded cents through `LongAdder.add((long) value)`, did not catch bad numbers, invented OpenCSV calls, and repeatedly failed to understand two ordinary Java type errors even with source and diagnostics adjacent. Cria did not create that capability failure. Cria did make it durable: self-compaction promoted the coder's unsupported source/compiler theory and source comments into authoritative-looking rollups, while the compactor was not shown the newer verbatim tail that determined current state. Fidelity validators repeatedly accepted those claims. The coder then spent the final third of the run proving phantom stale-source, classpath, alternate-version, and changing-JAR theories instead of fixing the two expressions. The proposed upstream compaction corrections improved the briefing but did not improve the coder's exact-call behavior, so no new assist or behavior change ships from this walk.

## A → B → C

### A — compaction is asked for current state without reaching the recent tail

The clearest incident is CALL 0084. The compactor system asks for the **CURRENT** code/build state. Its evidence contains an older 7,552-byte source and a check explicitly labeled nine coder commands old, while a current inventory says `Importer.java` is 7,531 bytes. The summarizable span ends before the recent verbatim tail containing:

1. the targeted edit from `CSVReader(Reader, 100)` to `CSVReader(Reader)`,
2. the successful write result,
3. the post-edit `mvn -q clean compile`, and
4. its two-error result.

That tail remains available to the coder after compaction, so this is not silent information destruction. It is a reach mismatch: the writer is asked to state the current world while the events that establish it are deliberately outside the writer's view.

The resulting briefing combines before- and after-edit sizes into a simultaneous discrepancy, calls the source self-consistent, carries the coder's unsupported different-compiled-file theory, and says the three old errors remain current. It also contradicts itself with `Nothing verified outstanding` after listing outstanding requirements.

### B — broad fidelity validation promotes hypotheses and comments to facts

CALL 0087's fidelity prompt contains the candidate, the old full source, the current existence/size inventory, and the stale check. Its own rule says inventory establishes names and sizes only, uncertain/model-reported state is not fact, and uncertainty must return `UNFAITHFUL`. It returns `FAITHFUL`.

This repeats across the run. Accepted briefings describe:

- workers-off and workers-on validation although `WORKERS_ENABLED` was never changed for those runs;
- one map per worker and a post-worker merge although the source has one global map and no executor/thread launch;
- malformed-number handling although `skippedBadNumber` is never incremented and parsing exceptions escape;
- current source/compiler disagreement although the two reported expressions exactly explain the diagnostics.

Other validator calls correctly return `NARROWS` or `UNFAITHFUL`, so the mechanism is not absent; it is unreliable when one broad verdict must judge many state, chronology, provenance, and source-behavior claims.

### C — the coder treats ordinary type errors as an environmental incident

The exact source says:

```java
String[] header = reader.readNext();
String[] cols = parseHeader(header);
private static String[] parseHeader(String header)
```

The `String[]` actual argument cannot be passed to the `String` formal parameter. The other error comes from:

```java
new BufferedReader(new StringReader(header), StandardCharsets.UTF_8)
```

where `BufferedReader(Reader, int)` receives a `Charset` as its second argument. Maven's messages and later direct-javac carets are correct.

The coder instead says the diagnostics are impossible, reverses actual/formal type direction, counts only the outer `CSVReader` call rather than the inner `BufferedReader`, and explicitly cites the rollup/files steering as evidence that source differs from what Maven sees. It progresses from stale source, to duplicate classes, to another OpenCSV version, and finally to an actively rewritten JAR. `find`, hashes, byte dumps, dependency trees, classpaths, `javap`, and a scratch counterexample disprove those theories; it does not update. CALLS 0090–0124 never fix the two expressions.

## Attribution

### Model capability failures

- The workers-on experiment never changes `WORKERS_ENABLED = false`.
- The replacement source contains no parallel worker execution.
- `(long) value` destroys decimal totals.
- malformed numeric values are not caught or counted.
- OpenCSV is used before its API is inspected.
- the coder repeatedly rewrites a whole file instead of applying localized compiler fixes.
- shell pipelines print `COMPILE_OK` or `EXIT=0` from `tail`/`head` rather than Maven/javac.
- the coder cannot follow a nearby argument/formal type or nested constructor even after direct carets.

Those failures are not evidence for a Java-specific deterministic assist.

### Cria/context failures and amplifiers

- The compactor does not reach the recent verbatim tail while being asked for current state.
- Source comments, intended designs, output labels, and coder explanations become accomplishment facts.
- Fidelity validation accepts candidates that conflict with evidence in the same prompt.
- A broad `a command has run since that could have changed the tree` caveat is cited by the coder as positive mutation evidence; after a denied compound command it appears even though that command did not execute.
- Inventory/body-derived byte counts differ by one from immediate `wc -c` results, adding false precision to a model already pursuing mutation.
- Rejected compaction leaves a large labeled mechanical digest. This preserves information, but also preserves several contradictory generated summaries and stale snapshots as attention competition.
- One forbidden `~/.m2/settings.xml` subcommand causes an entire compound call to return only a denial, so allowed jar/classpath facts are not observed. Cria must not pretend the other commands ran; any remedy would have to ground a clean retry through the harness.

The recent superseded-write wording/order experiment is not reopened here. Its exact-call replay looked favorable, but this very full-cell run regressed 35%→30%; commit `a02c573` already reverted it.

## Assists that behaved correctly

- The rumination guard broke otherwise lost generations and often elicited a dependency edit or real Maven run. One stale duplicate edit followed a guard, but stale-edit recovery refused it safely; four observed outcomes are mixed evidence, not grounds to remove the guard.
- Maven diagnostics and grounded source lines retained checker voice and were accurate.
- Dependency-cache access worked, and refusal text correctly said `~/.m2/repository` was readable and did not imply offline state.
- Current-file/read ledgers, targeted edit recovery, repeat deduplication, and labeled whole-write removal were truthful in the inspected incidents.
- Scope/fidelity validation failed closed on several bad candidates.
- Original task scope remained pinned.
- Completion remained fail-closed; the unfinished session was not handed to the human as success.

## Exact-call replays

Replay scripts and complete responses are under `/tmp/replay_compaction_*.py`, `/tmp/replay_compaction_*_results.jsonl`, and `/tmp/replay-coder-rollup-outs/`.

### Give the compactor the omitted recent tail

CALL 0084 was replayed six times per arm. Adding the exact successful edit, write result, post-edit compile/result, and refreshed ledgers removed the old three-error chronology and named the current two errors. However, all six tail-grounded briefings still promoted source comments to false working behavior: parallel per-worker maps, merged workers, and implemented skip handling.

### Add explicit accomplishment provenance

The writer prompt was strengthened without a keyword heuristic: comments, intended design, and coder explanations are claims; only a real run can establish working behavior. With the recent tail included, six of six outputs stopped claiming verified workers/behavior and said no behavior was verified working. But the deterministic output still contradicted itself about one versus two compile blockers and misattributed one error. The existing fidelity judge falsely accepted this grounded-but-internally-inconsistent candidate in six of six reasoning-off replays. Enabling reasoning with a 2,048-token budget produced no verdict in twelve of twelve attempts; every call exhausted its output in reasoning.

### Replay the resulting rollup to the coder

The strengthened, tail-grounded briefing replaced the rollup in exact CALL 0090 for eight replays. Result: **0/8 corrective edits**. Four reread `Importer.java`; five launched more shell/classpath/source probes (one did both). Every replay regenerated the impossible-error/stale-source theory from the visible Java and diagnostics even though the rollup no longer asserted that cause.

This invalidates the plausible compaction-only fix as an outcome intervention. It improves truthfulness but does not change this coder's next action, and shipping it as the cell fix would repeat the rejected-notice mistake: a better narrow replay with no demonstrated task benefit.

## Decision

No behavior change ships from this walk.

The evidence supports two future investigation directions, not implemented assists:

1. **Compaction reach/provenance.** A briefing writer asked for current state should see the recent tail or abstain from current claims, and should never call unexecuted source intent working behavior. This is a correctness invariant independent of whether Ornith can finish this Java task. A future change needs a fails-before test, adversarial chronology cases, validation against `4689beb`, `8f9d51a`, and `724339e`, and a replay demonstrating that downstream behavior does not regress.
2. **Focused diagnostic judgment after evidenced repetition.** After the same exact diagnostic recurs without a relevant edit, one narrow reasoner question about actual expression, actual type, formal type, and owning call may be more useful than another broad redirect. This must remain tool-voiced, additive, task/language/model/harness agnostic, fail open toward continued work, and must first be measured beyond this one pathological session.

Do not add a Java error parser, stale/cache keyword veto, mutation-verb list, one-error cadence, generic recovery pressure, or cria-authored code/action. The walk provides severity for one session, not prevalence for a new heuristic.
