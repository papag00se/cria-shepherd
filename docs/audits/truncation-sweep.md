# Truncation sweep — every place cria shortens what a model reads

Rule 5 was tightened on **2026-08-16** to name "head/tail limits, per-line caps, character budgets, **and disclosed elisions**", and to state that **disclosed truncation is still truncation**. The 2026-07-17 overhaul that removed 81 truncations predates that line by a month, and explicitly *kept* several sites on the grounds that they disclosed themselves. Nothing re-audited the code against the new wording.

Four sweeps, one per channel: shell composed for the harness, Python slicing, prompt templates and evidence assembly, and everything else. Counts are from `~/.cria/calls` (435 sessions) and `~/.cria/logs`.

**Status legend:** `FIXED` · `OPEN` · `RULING` (needs an operator decision, not an engineering one).

## The big three by volume

| site | what is cut | measured | status |
|---|---|---|---|
| `contextfloor.py:674` compaction note | whole turns dropped with **no digest at all**, only a `(+N)` counter | **6,725 turns** across 965 prompts; 219 prompts dropped ≥10 | OPEN |
| `proberun.py:921,927,985` gate head+tail band | a check's stdout/stderr around a filtered middle | **23.9 MB** cut across 5,703 renderings; worst single elision 421,414 bytes, section delivered 2,811 | OPEN |
| `proberun.py:959` diagnostics band | located diagnostics past a byte budget | 2,022 renderings; worst **12 of 308 shown** | OPEN |

`contextfloor.fit` is the one point rule 5 sanctions, *because* it is lossless-first. Lever 5 (drop inside the protected span) fired in **477 of 837** floor events, up to **220 turns in one request**, and 250 events still reported `over_budget` after every lever ran. The sanction does not describe the behaviour.

## Fixed in this pass

- **`wsview.py` bounded listing read as absent.** A tree that stopped at its budget left `complete = 1`, so `isfile()` answered **False** for a file that exists and the inventory told every reader "a file not listed here does not exist in the workspace". A gate-carried survey gets ~16 entries by construction, so this was the normal case. Now emits an `X` record and clears `complete`. — `test_a_bounded_listing_never_reads_as_absent.py`

## Open — undisclosed, which makes them 5b as well as 5

| site | what is cut | reaches |
|---|---|---|
| `proberun.py:1106` `OFFLINE_TAIL_BYTES = 600` | the whole network-off test run, twice tailed to 600 B | underpins the offline claim in **3,218 prompts** |
| `proberun.py:967` `grep -B2 -A3` | a diagnostic's own continuation lines; the marker claims the opposite | coder, gate parser, judges |
| `probeparse.py:982,938` `_CONTINUATION_MAX = 6`, `lines[i+1:i+4]` | the indented part that says *what* is wrong | coder, step critic, steer author |
| `planner_tools.py:120` `_GREP_MAX_HITS = 60` | files past the 60th hit are never opened; reads as exhaustive | planner |
| `writeproxy.py:1567` envelope strip | the harness's own `Warning: truncated output` line | coder reads a holed payload as whole |
| `contextfloor.py:289` `_DESC_CAPS` | tool descriptions to 40 chars; whole tools dropped off the menu | coder — nothing tells it |
| `apidiscovery.py:231` resources/prompts | a silent `[:MAX_ITEMS]` with no residual line | coder |
| `webfetch.py:1055` one-method-per-path | the POST shape of a path whose GET was shaped | coder |
| `server.py:364` compaction listing depth | anything deeper than two levels, never listed | coder, under "do not re-create them" |
| `writeproxy.py:1660` `_REJECTED_PAYLOAD_CHARS` | a refused write's payload deleted from the model's own history | coder |

## Open — disclosed, and still truncation under the tightened rule

`writeproxy.py:963` spill cut (46,080 B; worst **46,075 of 917,740**, 95% lost, 794 occurrences) · `focustrim.py:372` `_SPAM_KEEP` squash of *distinct* failed lookups (158 prompts; three different URLs folded as one "dead-end") · `selfcompact.py:667` replaced-fragment and refused-write stubs that point at nothing (**1,665** of 10,258 elisions) · `groundtruth.py:322` `JUDGE_FILE_BUDGET` (577 prompts; one run withheld **the deliverable and its tests** from the judge) · `webfetch.py:2042` `FIND_TOP_K = 3` (worst residual "1700 more matches") · `webfetch.py:991` endpoint/field caps · `apidiscovery.py` four caps · `loop.py:3708` step-critic summary tail · `loop.py:6943` `_READ_LEDGER_CAP` (alphabetical, so *which* files vanish is arbitrary) · `loop.py:9397` `TOUCHED_PATHS_CAP` · `loop.py:6359` `WRITES_SINCE_GATE_CAP` · `prompts/__init__.py:112` `named_list` — **one helper, ten seats**, including stranded test files the coder must fix · `probeparse.py:961` assertion message at 200 (expected-vs-got lives in the tail) · `probegate.py:492` the flagged source line at 200 · `planner_tools.py:168` grep match lines at 200.

## Correctness bugs found alongside

- **`proberun.py` miscounts what it discloses.** "N located diagnostics" counts lines matching `path:number` — every traceback frame matches. The famous "308" are pytest stack frames, not 308 diagnostics. cria states a number it did not measure (5b).
- **`content_reduce.strip_prose_text` is still on the coder's path.** The function-word deleter that cria's own docstring records turning *"could **be read from** it"* into *"could read it"*. Rare today (6 events), live.
- **`dedup.volatile_key` blanks any decimal followed by a time unit, unanchored.** Two benchmark runs printing `elapsed: 12.50 s` and `elapsed: 3.10 s` fold into one group and the earlier is deleted. Latent — no timing task has run through it — and principle 25c names "4× faster" as a task shape the suite carries.
- **`massage._recover_fused_call` keeps the first call and discards the second.** The last surviving member of the class fixed everywhere else.
- **`digest_reduce` returns code and prose unchanged**, so one 3 KB `write_file` payload consumed an entire compaction-note budget while 64 other turns got nothing.

## Rulings wanted

1. **The advisory filter** (`probegate.py:661`) drops `note:`/`warning:`/unused-name lines under "each is the checker's OWN message". Operator-sanctioned as an error-class filter; no rule-5 allowance covers it. 794 prompts.
2. **`ROLLUP_MAX_TOKENS = 2048`** was added for latency — *"at 7 tok/s it is an 18-minute worst case"* — eleven days after the overhaul raised these caps to 8192 "so a summary is never itself truncated". Principle 6 says do not shorten output for speed. Fails safe (no fold rather than half a fold), but 31% of rollups hit it.
3. **`wsview` folding** a >400-file directory to a count. Honest three-valued handling; still a reduction. Paging it across turns is the alternative.
