# Test refactor — cria's own suite

Process: `~/.claude/processes/test-refactor.md`, Mode A (Test Audit). Live document; updated as each pass lands.

**Status:** pass 1 (source-text change-detectors) — **five of six batches merged. 200 source-text sites → 62. Two live defects found and fixed, one coverage gap closed. ~110 deliberate code-breaks verified.**

| | before | after |
|---|---:|---:|
| source-text assertion sites | 200 | 62 |
| `assertEqual` (output values) | 2,244 | 2,319 |
| `assertIn` | 2,303 | 2,227 |
| `assertNotIn` pointed at `src` | 23 | 8 |
| tests passing | 3,997 | 4,009 |

The shift from `assertIn` to `assertEqual` is the conversion showing up in the aggregate: "the source contains this string" became "the output equals this value".

> ### The pass has already paid for itself
>
> `test_webfetch.py::test_the_header_no_longer_promises_every_field_comes_back` asserted that the module source no longer contains `"the fields each endpoint RETURNS (extract these"`. It passed. **A third render site was still promising it** — spelled `"the fields each call RETURNS (extract these"`, with `call` where the test searched for `endpoint`.
>
> So for two weeks cria told coders, on one of its three fetch-render paths, that the listed fields *come back* — when the shape extractor marks the unguaranteed ones with `?` precisely because the spec does not say that. That is a false fact in the model's ground truth (#5b), and it is the kind that surfaces as a `KeyError` in the deliverable.
>
> The change-detector was supposed to prevent exactly this and could not: **it pinned a spelling, not a promise.** Fixed by giving all three sites one owner (`webfetch._shape_block`) and asserting the RENDERED block.

---

## Opening readings — the SHAPE, not the size

Taken before any lens. These say where to look; none of them is a finding.

| reading | value | what it says |
|---|---|---|
| test files | 260 | |
| test methods | 3,998 | |
| subtest loops | 240 | |
| **assertion-free tests** | **3** | all three assert by not raising — legitimate. Nothing here. |
| **source-text assertions** | **200 uses across 91 files** | the one real soft spot. Pass 1. |
| mock uses | 81 across 26 files | **low.** The suite tests real objects. |
| runtime | 28 s | **cost is not an argument for deleting anything.** Say so before someone reaches for it. |

**Assertion verbs**, which is the most reassuring reading of the five:

| verb | count |
|---|---|
| `assertIn` | 2,303 |
| `assertEqual` | 2,244 |
| `assertNotIn` | 835 |
| `assertTrue` | 777 |
| `assertFalse` | 425 |

And what `assertNotIn` is pointed **at** — 183 at `out` (the code's actual output), 26 at `out.lower()`, 28 at `rlog.kinds()`, 26 at `note`, and only **23 at `src`**. The suite is behaviour-heavy. The blanket suspicion that a 4,000-test suite must be mostly junk is not what the shape says.

**Subject overlap:** `loop` is imported 427 times across the suite. It is a ~9,000-line module, so this is expected rather than damning — but it means whatever redundancy exists concentrates there, and pass 2 should start with it.

---

## Pass 1 — source-text change-detectors (lens 2)

**The lens.** A test that reads the *source* of the code under test and asserts on its text. Two subspecies, and only one is a defect:

- **Structural invariant** — "every render site goes through the one owner", "no module keeps its own copy of this table". There is no input that exercises *"there are exactly N call sites"*. These are legitimate and load-bearing; deleting them is how a one-owner rule silently acquires a second owner.
- **Change-detector** — `assertNotIn("<the old expression>", src)`, written the day a bug was fixed to prove the bad line is gone. It passes forever after, whatever the behaviour does. It cannot fail for the real reason, only for a rename.

**The discriminator:** could this be written as a behaviour test with a fixture? Yes → change-detector. No, the claim is about code organisation itself → structural, keep.

### The candidate set

200 `getsource` sites, by the shape of what they assert:

| shape | count | first read |
|---|---|---|
| `assertIn(<expected code>, src)` | 121 | mostly the same defect as below, stated positively |
| `assertNotIn(<removed code>, src)` | 37 | the classic change-detector |
| `src.count(...)` / one-owner | 15 | mostly legitimate structural |
| other | 27 | |

40 `assertNotIn`-shaped sites were enumerated and read against their targets. A third category emerged that the process document did not name, and it is the most common one here:

> **A structural claim asserted through the wrong instrument.** The claim is legitimate — "this removed parameter must not come back" — but source text is a weak way to check it when the object model can answer directly. `inspect.signature(f)` beats `assertNotIn("param=", src)`: it is rename-proof, it fails for the real reason, and it cannot be fooled by the word appearing in a comment. Several tests here already work around exactly that problem by stripping comment lines out of the source before searching it, which is the tell.

### Verified findings

Each was confirmed by opening **both** the test and the code it covers.

| # | test | verdict | why |
|---|---|---|---|
| 1 | `test_a_docs_page_is_not_yaml.py::test_yaml_is_no_longer_a_possible_answer` | **REWRITE** | asserts `"YAML"` absent from `_doc_format`'s body. The file is full of real behaviour tests of that same function. Feed it a YAML document and assert the answer isn't "YAML" — catches a reintroduction by any spelling. |
| 2 | `test_planner_workspace_ground_truth.py::test_nothing_is_truncated` | **REWRITE** | asserts `"result.text[:"` absent. The test directly above already drives the real path with real results — the truncation claim can ride on the same fixture with a long body. |
| 3 | `test_planner_workspace_ground_truth.py::test_the_loop_dedupes_and_still_answers_every_id` | **DELETE** | three exact code strings asserted; the behaviour test above it (`executed`/`results` counts) already proves the dedup and the one-result-per-id protocol. Redundant *and* brittle. |
| 4 | `test_the_gate_reports_a_hard_failure.py::test_type_error_is_not_swallowed` | **REWRITE** | asserts the `except` clause's text. The defect was real (a field called as a method returned False for months). Pass an object whose attribute access raises `TypeError` and assert it propagates. |
| 5 | `test_suite_throttle_guard.py::test_the_probe_sends_a_real_user_agent` | **REWRITE** | asserts `headers={"User-Agent": PROBE_UA}` appears in the source. Patch the opener and assert the outgoing request carries the header. The sibling test right below it is already behavioural. |
| 6 | `test_webfetch.py::test_the_header_no_longer_promises_every_field_comes_back` | **REWRITE** | asserts wording inside the module source; the same file's neighbouring test asserts the *rendered* block. Assert the rendered header. |
| 7 | `test_a_judge_is_handed_the_files_not_made_to_ask.py::test_the_steer_author_does_not` | **REWRITE** | asserts `"seed_files"` absent from `author_steer`. Reachable: build a session holding a large file, call the author, assert the file's bytes are not in the prompt. That is the actual promise (210K → 89K chars) and the source test cannot see it. |
| 8 | `test_a_judge_is_handed_the_files_not_made_to_ask.py::test_the_question_is_still_the_last_thing_read` | **REWRITE** | asserts `messages.insert(1,` present. The claim — the question is the last message — is one assertion on a built prompt, and far stronger. |
| 9 | `test_a_proposed_fix_is_held_to_the_steer_bar.py::test_no_reasoner_is_spent_on_it` | **REWRITE** | asserts `"ask="` absent from `_verdict_nudge`. Pass an `ask` that raises and assert it is never called. |
| 10 | `test_harness_tool_leak.py::test_it_does_not_rewrite_the_step` | **REWRITE** | searches a 300-character window for `.replace(` / `re.sub(`. The promise is "cria never authors or edits a plan step" — assert the returned step text is byte-identical to the input, which is both stronger and immune to the window sliding. |
| 11 | `test_flail.py` × 3 | **REWRITE (instrument)** | "the removed thing stays removed" is a legitimate structural claim. But one of them strips comment lines out of the source before searching, to stop a deliberate explanatory comment failing the test — the tell that source text is the wrong instrument. Use `inspect.signature` for the parameter and the real dict keys for the trigger. |
| 12 | `test_judge_tail_fixes.py::test_no_closed_question_is_sent_with_an_empty_user_turn` | **KEEP (structural)** | a module-wide search for a call shape. The claim is "nobody bypasses the one asking primitive", which no fixture can exercise. Legitimate — the guard in the lens applies. |

### What landed

Nine files converted, each rewrite verified by breaking the code and watching the new test go red — twelve deliberate breaks in all. The rewrites are strictly stronger, and in three cases measurably so:

- **The planner dedup.** Breaking it by making the lookup always miss leaves the old source test **green** (the dedup dict is still written) and the new behaviour test red. The old "behaviour" test beside it re-implemented the dedup *inside the test* and asserted on its own copy — it could not fail for the real reason at all.
- **The hard-failure gate.** Restoring the original bug in full — calling the field as a method, with `TypeError` back in the `except` — now turns **four** tests red. Before, it turned none red: that is how it survived for months.
- **The shape header.** The old test passed while a live render site still made the promise it claimed was removed. See the box at the top.

Two things the process document should absorb from this pass:

1. **The wrong-instrument category is the most common one here.** Several claims were legitimately structural — "this parameter must not come back", "this trigger has no entry" — but were checked by searching source text, when `inspect.signature` and the real dict keys answer directly, rename-proof and comment-proof. One of them had to strip comment lines out of the file first so that a deliberate explanatory comment would not fail it. **Needing to hide part of the file from your own assertion is the tell.**
2. **A behaviour rewrite teaches you what the mechanism does; a source assertion never can.** Writing the tool-leak fixture surfaced that `"web_fetch the spec"` is *deliberately allowed* — it is an instruction to the agent — and only `"mock web_fetch"` leaks. The first fixture asserted the wrong thing and the code was right. A test that added a control for the allowed form came out of that, and the source test could not have prompted it.

### Still to do

- 28 `assertNotIn`-on-source sites.
- 121 `assertIn(<expected code>, src)` sites — the same weakness, four times as common, and the likelier defect pool.
- Pass 2: redundancy, starting with `loop` (427 imports across the suite). Confirmed by breaking code and counting what goes red, not by reading names.
- Pass 3: the inverse lens — the invariant nobody tests.


---

## The three defects this pass has found

None of them was the thing the pass set out to do. All three were found because converting a source-text assertion into a behaviour test forces you to learn what the code actually promises.

### 1. A live false fact in the model's ground truth — `webfetch`

Covered in the box at the top of this file. Three render sites, two corrected, one still promising the model that the listed API fields come back. The test that existed to prevent it searched for the sentence spelled with `endpoint`; the survivor said `call`.

### 2. The living replan handed its satisfaction judge the coder's parameter names — `loop._replan_tail`

`_replan_tail` builds one tool summary for the REPLANNER, which legitimately carries parameters: a re-derived step has to be something the coder can actually do. It then reused that summary for the `judge_satisfaction` call in the same method. The other three judge sites all pass `params=False`.

So a read-only judge was shown `justification`, `workdir`, `max_output_tokens`, `login` — the exact vocabulary from the incident `tests/test_judge_is_fenced_out_of_acting.py` documents, where a judge fabricated tool calls out of its own prompt, went silent, and cria fail-closed twelve consecutive times on a workspace already at 5/5. Live for as long as that branch has existed.

**The guard that should have caught it** searched `loop.py` for the literal `"coder_tools=_coder_tools_summary"` and silently `continue`d past any site that passed a variable instead — precisely this site's shape. *A source-text scan with a silent skip reads as "all sites checked" when it means "the sites I could see."* That sentence belongs in the process doc.

### 3. The step check's cadence can starve, and nothing covered it

Found by independently re-breaking a merged batch rather than trusting its verified-list. The suite pinned "a drive with no open step does not spend the opportunity" but not the sibling: a drive where the check was **not due**.

It is arithmetic, not a hypothesis. Over 40 drives at the live cadence, a stamp that moves only when the check RUNS fires at 12, 24 and 36. A stamp that moves on every drive fires **zero** times — the exact silence this file was written about (21 events on the box, every one at turn 12), reached by a different route.

---

## What the batches taught that the process doc did not say

1. **The wrong-instrument category is the most common finding, not the change-detector.** Many claims are legitimately structural — "this parameter must not come back", "only one place spells this" — but were checked by searching source text when the object model answers directly: `inspect.signature(f).parameters`, `dataclasses.fields(C)`, `f.__code__.co_names`, real dict keys, `ast.walk` for a specific call node. Those are rename-proof and comment-proof.

2. **Needing to hide part of the file from your own assertion is the tell.** Several tests stripped comment lines out of the source before searching it, so that a deliberate explanatory comment would not fail them. One searched a function whose *docstring narrates the removed pattern* — the test had to dodge its own evidence.

3. **A source scan that skips is worse than one that fails.** Defect 2 above. If a text scan cannot parse a site, it must fail loudly, never `continue`.

4. **Some source-text tests are inert, not merely weak.** One asserted on a function name (`dirguard._INSTALL_REMEDY_FN`) that has never existed, so its `hasattr` guard always fell through to scanning the whole module. Another assumed prompt loading strips `#` lines — only one of the two loaders does.

5. **Writing the fixture is where the learning is.** Converting the tool-leak test surfaced that `"web_fetch the spec"` is *deliberately allowed* (an instruction to the agent) and only `"mock web_fetch"` leaks. The first fixture asserted the wrong thing; the suite gained a control for the allowed form. No source-text test could have prompted that.

## Still to do

- 62 source-text sites (one batch still running).
- Pass 2 — redundancy, starting with `loop` (427 imports across the suite). Confirmed by breaking code and counting what goes red, not by reading names.
- Pass 3 — the inverse lens: the invariant nobody tests. Defect 3 above is one instance of what that pass is for.
- One lens-1 candidate already flagged by a batch and deliberately out of scope: `test_the_unchanged_findings_guard_sees_every_trigger.py` reimplements the guard's logic inline instead of calling the real `author_steer` — a circular-expectation smell.
