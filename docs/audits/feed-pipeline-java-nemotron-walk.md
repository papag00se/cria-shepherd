# Walk — `feed-pipeline-java × nemotron-elastic`, run `1787247514`

**Score 1/5. 75 calls, 30 minutes, ended on the wall clock.** Captures: `~/.cria/calls/20260820T103857-01a02041-2b68-7673-9fbe-8cd35911109e`. Code state at run time: `05f7525`.

Walked call by call, 12 agents plus direct verification. Every claim below was re-checked by hand against the captures, the workspace, or by running the code; agent findings that did not survive that check are recorded as refuted.

## The failure in one line

`Importer.java` imported `com.opencsv.CSVRecord`. That class does not exist — `CSVRecord` is Apache Commons CSV. One bad import line, 65+ compile errors, four of five checks failing on the broken build. The fifth, `REVIEW.md`, passed.

**The model invented it.** First appearance is call 0011, in the coder's own private reasoning, before cria had said anything about a library. The seed `pom.xml` declares no dependencies and the task prompt names no library. The other two imports it chose — `CSVParser`, `CSVParserBuilder` — are real OpenCSV classes. It was one class away from compiling for the whole run.

## What cria did with it

cria never caused the mistake. It failed to end it, and in two places it hardened it.

| when | what cria said | true? | reached the coder? |
|---|---|---|---|
| 0023 | "Add OpenCSV dependency to pom.xml now … `opencsv:5.9.3`" | no — declared since 10:40, and 5.9.3 does not exist | **no** — `_invented_version` refused it |
| 0027 | "Add the import for … CSVRecord … use `csvParser.parseRecord(line, record)`" | no | **no** — judged `DICTATES`, then dropped |
| 0030 | workspace listing + "modify Importer.java to use OpenCSV" | vague, ungrounded | yes |
| 0047 | *(nothing — 35 KB of reasoning, `content: null`)* | — | no |
| 0055 | "the code still references `CSVRecord` … **without importing the class**" | **no** — the import is line 5 | **yes**, and permanently |
| 0066 | "add imports for com.opencsv.CSVParser and com.opencsv.CSVRecord" | **no** | **yes** |

The guards caught the two steers with a bad *shape* (an invented version, dictated code) and let through the two with a bad *fact*. Both of those went out through the re-orientation channel, which runs none of the steer guard chain.

## Root causes, in the order that matters

### 1. Maven's own log tag hid every Java diagnostic from cria — `cc84738`

`_MAVEN_LOC` is anchored at `^`. Maven prints every diagnostic through its logger:

```
[ERROR] /w/src/main/java/pipeline/Importer.java:[5,19] cannot find symbol
```

so the path never sits at column 0 and the pattern never matched. Reproduced directly: `parse_generic` returned **0 findings** on real `mvn` output, 3 after the fix.

The comment above that pattern already records this bug as fixed — "Seen in every Java cell of cycle 1; that column scored 0 / 40 / 0 / 0". The fix was written and tested against bare `javac` output and was inert on every real Java run since. The test standing beside it, `test_maven_prints_no_location_so_none_is_invented`, is true of the input it uses (a surefire *test* summary, which genuinely has no location) and was read as a fact about all Maven output.

**What it cost, in order:** no findings → `gate_error_text` fell through to "a specific line could not be parsed from the output" and quoted the last `[ERROR]` line, which is Maven's help URL → the steer author was handed `http://cwiki.apache.org/…/MojoFailureException` as "GROUND TRUTH FROM THE REPO'S CHECKS" while `cannot find symbol / symbol: class CSVRecord / location: package com.opencsv` sat in the same prompt. This appeared **5 times** across the run.

And an empty finding-set makes `_prescribes_what_the_checks_reject` return on its first line. That guard's entire job is refusing a steer that tells the coder to USE the symbol the checks reject — exactly steer 0066. It was inert because the findings it reads were empty.

### 2. The compaction briefing looked up the session under a key nothing writes — `8f7bc32`

`_harden_compaction_reply` resolved the session with `session_key({}, messages)` — an empty headers dict, so it could only ever produce the `task:` text-hash form. The loop's store is written under the caller's key, `sid:<prompt_cache_key>` under Codex. **The lookup missed on every compaction of every session.**

`_last_checks_note` exists to bolt the last gate verdict onto the briefing verbatim — "deterministic check truth the model-authored briefing kept omitting", in its own docstring. **Zero `LATEST CHECK RESULTS` blocks appear in this run's 75 prompts.** The workspace inventory, which needs no store lookup, appears in six. That asymmetry is the bug's signature.

Left to describe the build from memory, the compactor at 0055 wrote seven "what is broken" bullets. Five are false, checked line by line against the file the coder had just written:

- "still references `CSVRecord` … **without importing the class**" — line 5 is that import
- "does not import `com.opencsv.CSVParser`" — line 3
- "`skipReasons` is declared as a plain `HashMap`" — it is a `ConcurrentHashMap`
- "`totals.put(sku, totals.getOrDefault(...))` … is not a valid `Map.put` signature" — that line is not in the file, and it is valid Java
- "The `main` method's call to `mvn test` is failing" — `main` does not invoke Maven

The real cause was inverted into a fixable-sounding one. cria then carried that block as `⟦ctx:continuation⟧` on **every prompt from 0056 to 0075**, and the re-orientation seat at 0056 — whose prompt forbids it to second-guess the summary — turned it into a numbered work order. Item 1 was impossible; item 2 was already done.

**Measured effect.** Calls 0057-0065 are nine consecutive orientation reads with 42-617 bytes of thinking each, opening with `find . -name "*.java"` — byte-identical to call 0002, the first action of the session. `cannot find symbol` appears in the prompt 17 times at 0054 and **zero times** across 0057-0065. The last write of the run is call 0053; the final 21 calls changed nothing on disk.

### 3. The rewriter was never given the directive — `cc84738`

`_steer_ask` named its second parameter `_user` and discarded it. Harmless for the closed-question guards, which render their payload into the system prompt; silently fatal for `_restate_without_code`, which passes the directive as `user` against a template with no placeholder for it. At 0029 the rewriter received the bare instructions plus "Answer the question above.", reasoned *"the original directive does not contain any file paths or line numbers"* **about the system prompt itself**, and returned `NO_DIRECTIVE`.

**Every steer that ever reached the rewriter was dropped, always, for a reason unrelated to its content.** Born broken in `9343a88`, one commit before this run. The unit test one file over could not see it: its fake `ask` honours `user`.

### 4. One file under two names was two files — `d99f82e`

The coder wrote `Importer.java` seven times by absolute path and once, at 0043, as `src/main/java/pipeline/Importer.java`. `_drop_superseded_writes` keys on the path string, so the two runs of writes never superseded each other — the largest payload in the session went unfolded, and the note named the same file twice in one sentence, which reads as two files that both changed (#5b). Folded by component-wise suffix now; an ambiguous suffix does not fold, because the cost of folding wrongly is deleting a file's only copy.

Two sibling defects in the same function, found in the same walk and fixed alongside: a **refused** write counted as the newest version (the note asserted "what is on disk is what you last wrote" about a `pom.xml` write cria had itself rejected), and the note's file list was rendered from every write *target* rather than from the calls actually dropped — "1 earlier write(s) … removed: REVIEW.md, pom.xml, Importer.java".

## What the guards got right

Worth recording, because the safe direction is remove and three of these are the reason this run was not worse.

- **`_invented_version` earned its keep.** It refused 0023 over `5.9.3`. The local repo holds 5.7, 5.8, 5.9, 5.10, 5.12.0 — no 5.9.3, and no three-segment 5.9.x at all. Substituting the real `5.9` into the same directive passes every guard, so this was a narrow escape, not a robust one.
- **The degenerate-run backstop was right 8 times out of 9.** The ninth (0012) fired on the raw-length arm while composing a Java file, and the note it produced named phrases — "wait", "let me reconsider" — the model never emitted. Density was 0.67 per 1k against a threshold of 10.
- **The write guard caught two envelope leaks.** At 0008 and 0051 the model emitted two tool calls and the parser folded the second into the first's `pom.xml` content. Both were refused as malformed XML. Both would have landed silently in a `.java` or `.md` file.
- **The completion gate held.** `task_complete` at 0015 was rejected with the real compile errors, correctly, on a build that had never run.

## Open, not fixed

- ~~**The compaction summary is still never checked against the gate result cria holds.**~~ **CLOSED by `a1ec3a8`** — and not the way this line proposed. Vetoing the briefing's prose would have been a fix at the point of damage; the cause is that cria asked a model to DERIVE a fact it already held. The compactor is now given the last gate verdict as input, with an instruction not to work the build state out by reading. `8f7bc32` remains the other half: the verdict is also appended to the output, so the fact survives a writer that omits it.
- **`loop.satisfaction_blocked: 47` overstates itself.** The event fires above the due check, so 18 of the 47 were drives where nothing was due. The blocking itself was correct here — the build was red from the first gate to the last, and the check exists for a session that has finished and cannot stop. But the gap-naming arm is unreachable on a red gate by construction, and a missing deliverable needs no build to detect.
- **`harness.truncated_a_result: 19` is 3 real cuts counted 19 times** — the whole history is re-scanned every turn.
- **`context.focus_trim` and the `coder-s1-focusN` calls are unrelated mechanisms.** The `focusN` retry after a rumination abort **removes nothing**: 0041 and 0042 are byte-identical, and 0040→0041 is a pure addition. It is a resample, not a re-framing. At 0073→0074 that cost the run its only correct diagnosis — 0073 had the `Map.merge` arity bug right and 0074 reversed it.
- **`_strip_invented_code` is dead in production**, kept alive by tests only.
- **Nobody ever looked the library up.** `opencsv-5.9.jar` sat in `~/.m2` all run and contains zero classes matching `Record`. The coder had `web_search`, `web_fetch` and `exec_command` and used none of them; cria's system prompt says "RESEARCH & INVESTIGATE FIRST" and it was inert. The reasoner could not check either — its `read_file` is workspace-bounded, so it has no way to verify a third-party symbol. A `cannot find symbol` on a third-party class, with the jar in the local cache, is the highest-value unexploited signal in this run.
