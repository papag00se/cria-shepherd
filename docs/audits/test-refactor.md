# Test refactor — cria's own suite

Process: `~/.claude/processes/test-refactor.md`, Mode A (Test Audit). Live document; updated as each pass lands.

**Status:** pass 1 (source-text change-detectors) in progress — 5 files converted, **1 live defect found**.

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

### Dispositions still to verify

The remaining ~28 `assertNotIn` sites and the 121 `assertIn(<expected code>, src)` sites are unread as of this writing. The `assertIn` family is likely the larger defect pool: it has the same weakness and is four times as common.
