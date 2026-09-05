# Truncation sweep — every place cria shortens what a model reads

Rule 5 was tightened on **2026-08-16** to name "head/tail limits, per-line caps, character budgets, **and disclosed elisions**", and to state that **disclosed truncation is still truncation**. The 2026-07-17 overhaul that removed 81 truncations predates that line by a month, and explicitly *kept* several sites on the grounds that they disclosed themselves. Nothing re-audited the code against the new wording.

Four sweeps, one per channel: shell composed for the harness, Python slicing, prompt templates and evidence assembly, and everything else. Counts are from `~/.cria/calls` (435 sessions) and `~/.cria/logs`.

**Status legend:** `FIXED` · `OPEN` · `RULING` (needs an operator decision, not an engineering one).

## The big three by volume

| site | what is cut | measured | status |
|---|---|---|---|
| `contextfloor.py:674` compaction note | whole turns dropped with **no digest at all**, only a `(+N)` counter | **6,725 turns** across 965 prompts; 219 prompts dropped ≥10 | FIXED |
| `proberun.py` former gate head+tail band | a check's stdout/stderr around a filtered middle | **23.9 MB** cut across 5,703 renderings; worst single elision 421,414 bytes, section delivered 2,811 | FIXED |
| `proberun.py` former diagnostics band | located diagnostics past a byte budget | 2,022 renderings; worst **12 of 308 shown** | FIXED |

`contextfloor.fit` is the one point rule 5 sanctions, *because* it is lossless-first. Lever 5 (drop inside the protected span) fired in **477 of 837** floor events, up to **220 turns in one request**, and 250 events still reported `over_budget` after every lever ran. The sanction does not describe the behaviour.

## Fixed

Every item below is implemented and pinned by tests. Test pins that encoded the old behaviour were reversed with the reasoning written into each.

| site | what changed |
|---|---|
| `wsview` bounded listing | a tree that hit its budget now emits a fold record and clears `complete`, so `isfile` answers **unknown** instead of **False** and the inventory stops claiming completeness |
| `contextfloor` compaction note | the reserve for remaining stubs is measured exactly, a digest may spend only what is left, and a turn that still will not fit is **named** — role and first line, or role/kind/size for one unbroken blob. `(+N could not be summarized)` is gone. Repeat folding now handles a repeating **cycle**, so an assistant/tool loop folds instead of filling the note |
| `content_reduce` prose tier | **removed**. It deleted function words and inverted a negation in a real run. Replaced in the JSON tier by lossless folding of identical adjacent elements — 1,472 tokens to 26 on the floor's own fixture |
| `proberun` offline tally | the runner's tally lines go whole; only the parse-fallback raw tail stays bounded |
| `probeparse` `_CONTINUATION_MAX` | deleted — the structural boundary already ended a diagnostic, and the count cut `symbol:`/`location:`/`note:` lines |
| `probeparse` assertion message | whole; expected-vs-got lives in the tail a 200-char head cut removed |
| `probegate` flagged source line | whole; a cut quote is a partial guess-prompt |
| `planner_tools` `_GREP_MAX_HITS` | says when it stopped, on both paths, and quotes matching lines whole |
| `named_list` + three ledgers | uncapped at ten evidence seats, `_READ_LEDGER_CAP`, `TOUCHED_PATHS_CAP`, `WRITES_SINCE_GATE_CAP` |
| `writeproxy` envelope strip | the harness's own `Warning: truncated output` is kept, and `note_harness_cuts` learned its shape — every end-cut result was previously a truncation cria never observed |
| `focustrim` squash | each folded attempt carries the first line of its own answer; the attempts are not duplicates of one another |
| `selfcompact` stubs | a **refused** write's payload and a **replaced** fragment stay verbatim — they exist nowhere else. A superseded body still stubs (rule 11) |
| `webfetch` `FIND_TOP_K` | every whole match that fits, rest routed to the saved copy; `_extract_around`'s silent per-window byte cut removed |
| `webfetch` one-method-per-path | every method's shape, not just the first |
| `apidiscovery` | tools/args/fields uncapped; MCP resources and prompts no longer sliced silently |
| `server` compaction listing | the whole workspace, in the reply the harness stores as the session's memory |
| `contextfloor` tool descriptions | cut at a sentence or word boundary and marked, never mid-word |
| `dedup.volatile_key` | the clock scrub is scoped to a runner's own tally line; a program's `elapsed: 12.50 s` keeps its number |
| `massage._recover_fused_call` | records how much it discarded |
| `ROLLUP_MAX_TOKENS` | 2048 → 8192 (rule 6: never cap output for latency) |
| completion-gate output | removed every per-probe/head/middle/tail byte cut. The harness spools the complete marker-delimited stream outside the workspace and returns 6,000-byte pages over ordinary asynchronous shell calls. cria accepts it only after byte count and SHA-256 verify; a cut, reordered, malformed or missing page is explicit `UNKNOWN`, never green |
| judge file evidence | removed `JUDGE_FILE_BUDGET` and newest-first preselection. Every readable text file supplied by the harness workspace view is quoted whole; every unavailable/binary file is named. Unknown size is data, not an integer comparison |
| step-critic summary | removed the undisclosed 8,000-character tail. Ordinary summary prose reaches the critic whole; only a detected tool-call payload is rejected as not being a summary |

## Superseded notes


- **`wsview.py` bounded listing read as absent.** A tree that stopped at its budget left `complete = 1`, so `isfile()` answered **False** for a file that exists and the inventory told every reader "a file not listed here does not exist in the workspace". A gate-carried survey gets ~16 entries by construction, so this was the normal case. Now emits an `X` record and clears `complete`. — `test_a_bounded_listing_never_reads_as_absent.py`

## Open — undisclosed, which makes them 5b as well as 5

| site | what is cut | reaches |
|---|---|---|
| `proberun.py` `OFFLINE_TAIL_BYTES = 600` | the raw network-off parse fallback (recognized tally lines travel whole) | fallback underpinning the offline claim |
| `probeparse.py:982,938` `_CONTINUATION_MAX = 6`, `lines[i+1:i+4]` | the indented part that says *what* is wrong | coder, step critic, steer author |
| `planner_tools.py:120` `_GREP_MAX_HITS = 60` | files past the 60th hit are never opened; reads as exhaustive | planner |
| `writeproxy.py:1567` envelope strip | the harness's own `Warning: truncated output` line | coder reads a holed payload as whole |
| `contextfloor.py:289` `_DESC_CAPS` | tool descriptions to 40 chars; whole tools dropped off the menu | coder — nothing tells it |
| `apidiscovery.py:231` resources/prompts | a silent `[:MAX_ITEMS]` with no residual line | coder |
| `webfetch.py:1055` one-method-per-path | the POST shape of a path whose GET was shaped | coder |
| `server.py:364` compaction listing depth | anything deeper than two levels, never listed | coder, under "do not re-create them" |
| `writeproxy.py:1660` `_REJECTED_PAYLOAD_CHARS` | a refused write's payload deleted from the model's own history | coder |

## Open — disclosed, and still truncation under the tightened rule

`writeproxy.py:963` spill cut (46,080 B; worst **46,075 of 917,740**, 95% lost, 794 occurrences) · `focustrim.py:372` `_SPAM_KEEP` squash of *distinct* failed lookups (158 prompts; three different URLs folded as one "dead-end") · `selfcompact.py:667` replaced-fragment and refused-write stubs that point at nothing (**1,665** of 10,258 elisions) · `webfetch.py:2042` `FIND_TOP_K = 3` (worst residual "1700 more matches") · `webfetch.py:991` endpoint/field caps · `apidiscovery.py` four caps · `loop.py:6943` `_READ_LEDGER_CAP` (alphabetical, so *which* files vanish is arbitrary) · `loop.py:9397` `TOUCHED_PATHS_CAP` · `loop.py:6359` `WRITES_SINCE_GATE_CAP` · `prompts/__init__.py:112` `named_list` — **one helper, ten seats**, including stranded test files the coder must fix · `probeparse.py:961` assertion message at 200 (expected-vs-got lives in the tail) · `probegate.py:492` the flagged source line at 200 · `planner_tools.py:168` grep match lines at 200.

## Correctness bugs found alongside

- **`content_reduce.strip_prose_text` is still on the coder's path.** The function-word deleter that cria's own docstring records turning *"could **be read from** it"* into *"could read it"*. Rare today (6 events), live.
- **`dedup.volatile_key` blanks any decimal followed by a time unit, unanchored.** Two benchmark runs printing `elapsed: 12.50 s` and `elapsed: 3.10 s` fold into one group and the earlier is deleted. Latent — no timing task has run through it — and principle 25c names "4× faster" as a task shape the suite carries.
- **`massage._recover_fused_call` keeps the first call and discards the second.** The last surviving member of the class fixed everywhere else.
- **`digest_reduce` returns code and prose unchanged**, so one 3 KB `write_file` payload consumed an entire compaction-note budget while 64 other turns got nothing.

## Rulings wanted

1. **The advisory filter** (`probegate.py:661`) drops `note:`/`warning:`/unused-name lines under "each is the checker's OWN message". Operator-sanctioned as an error-class filter; no rule-5 allowance covers it. 794 prompts.
2. **`ROLLUP_MAX_TOKENS = 2048`** was added for latency — *"at 7 tok/s it is an 18-minute worst case"* — eleven days after the overhaul raised these caps to 8192 "so a summary is never itself truncated". Principle 6 says do not shorten output for speed. Fails safe (no fold rather than half a fold), but 31% of rollups hit it.
3. **`wsview` folding** a >400-file directory to a count. Honest three-valued handling; still a reduction. Paging it across turns is the alternative.


---

## Open, with the reason each is not a clean call

### The gate's head+tail band — `proberun.py` — fixed 2026-09-05

The largest single site cut **23.9 MB** across 5,703 renderings, with a worst single elision of 421,414 bytes against 2,811 delivered. The resolution is asynchronous harness-mediated transport, not a larger bound. The harness writes the complete gate aggregate to a temporary file outside the workspace and returns base64 pages through the same shell-tool request/response channel. Session-scoped `GatePlan` state enforces the next offset, a stable path/total/hash, exact final byte count, and SHA-256 before the existing section parser receives anything. cria never opens the harness path. The final page removes the temporary file on the harness side.

The old diagnostic selection and its false count disappeared with the clipping implementation. If any page is cut, replayed, reordered, malformed, or unavailable, the result is `UNKNOWN`; completion remains unsatisfied and no clean-gate wording can be produced.

### The fetch spill cut — `writeproxy.py:963`

46,080 bytes; worst observed **46,075 of 917,740** (95% lost), 794 occurrences. The bound is real and external: the harness runs `bash -lc "<command>"` and Linux caps a single argument at `MAX_ARG_STRLEN` = 128 KiB, so one command genuinely cannot carry more. Raising the constant would trade a disclosed cut for `Argument list too long`.

The correct fix is paging: cria holds the whole document, so it should queue the remainder and append it on the commands it composes on later turns — the ride-along pattern `wsview` already uses for its survey. That is new machinery on a path with no live test coverage, and shipping half of it would leave a spill file that is silently incomplete, which is worse than one that says it is.

### The advisory filter — `probegate.py:661`

Drops `note:` / `warning:` / unused-name lines from the gate block, disclosed as a count, in 794 prompts. Operator-sanctioned as an error-class filter, and there is a live tension: rule 3 says inject only high-confidence actionable information, rule 5 says do not shorten. Neither reading is obviously wrong, so this is an operator call rather than an engineering one.

### Tool drops at the floor — `contextfloor.py`

When the schema still will not fit at the smallest description bound, whole tools are dropped from the end of the menu. The count reaches the floor's event and **nothing tells the model**, so a capability simply ceases to exist for it. It has never fired (`tools_dropped: 0` across the corpus). Telling the model in-band needs a channel the floor does not have — the tool cheat-sheet is composed much earlier — so the fix is a plumbing change rather than a bound change.

### `wsview` directory folding

A directory over 400 files becomes a count. Honest three-valued handling: `complete`/`folded` withdraw the completeness clause and readers get `None`, not `False`. Still a reduction of model-visible evidence. Paging the survey across turns is the alternative, and it is the same machinery the spill needs.
