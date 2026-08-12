# The assisted arm, read line by line

Forty readers over all 24 assisted runs — 2,178 model calls, 8,404 captured files. Method: find
every wrong turn in the model's own thinking first, then go back and find what in the context
caused it. Symptom first, cause second. Where nothing in the context accounts for a wrong turn,
the reader had to say so rather than invent one.

Raw evidence: `2026-08-12-assisted-arm-walk.json` (every verified wrong turn, with both quotes).

## Verification

The readers reported 617 wrong turns. Every quote was then checked against the capture files by
script, not by another agent: does the reasoning quote actually appear in that run's reasoning, and
does the context quote actually appear in a prompt?

| | count |
|---|---:|
| wrong turns reported | 617 |
| **both quotes found verbatim on disk** | **460** |
| at least one quote unverifiable | 157 |

The 157 are not counted anywhere below. They cluster in the nemotron and long-qwen slices, which is
consistent with paraphrase under a heavy reading load rather than a mapping error.

Of the 460 verified:

| where the wrong turn came from | count |
|---|---:|
| **cria** — its steers, its judges, its shaping of tool results, its compaction | **256** |
| nothing found in the context — the model went wrong on its own | 187 |
| the task prompt, the harness, or the seed code | 17 |

What the 256 cria-caused wrong turns actually cost:

| | count |
|---|---:|
| wasted calls | 190 |
| lost a check | 36 |
| no cost | 20 |
| broke working code | 6 |
| stopped a run early | 4 |

## The correction: "cria drives every model to the same pace" was wrong

The campaign report said every model converged on ~23 minutes per task regardless of what it needed
unaided, and read that as cria setting the pace. That was **my instrument, not cria**.

`suite/run.py:326` sets `wall = milestone_minutes × deliverable_count`. Deaths therefore land on a
grid — 15.8, 16.2, 30.8, 46.2, 60.9 minutes — and the per-model means match because they share the
grid. nemotron sat at 15.8–16.2 in five of its six runs: that is *failed the first floor test five
times*, not *converged on a pace*. The battery report has been corrected.

### What is true, measured directly from the captures

**14 of 24 assisted runs had the coder declare the task complete. The baseline arm has zero
declarations** — those runs end when the model stops. Seven of the fourteen were kept running:

| run | declared at | ran to | extra calls | base → cria |
|---|---:|---:|---:|---|
| nemotron / node | 7 | 76 | +69 | 0% → 0% |
| nemotron / python | 159 | 226 | +67 | 25% → **75%** |
| qwen35 / rust | 29 | 89 | +60 | 100% → 100% |
| qwen35 / ruby | 97 | 141 | +44 | 80% → 60% |
| nemotron / java | 29 | 71 | +42 | 0% → 0% |
| gemma4 / ruby | 131 | 162 | +31 | 40% → **100%** |
| nemotron / rust | 50 | 60 | +10 | 0% → 0% |
| gemma4 / java | 93 | 100 | +7 | 80% → 40% |

**330 calls after the model said it was done — and this does not support "make cria stop".** The two
biggest wins in the whole campaign were earned after the declaration: gemma4's Ruby went 40% → 100%
with 31 post-declaration calls, nemotron's Python 25% → 75% with 67. Four runs burned the calls for
nothing, two lost ground. Refusing the declaration is right roughly as often as it is wrong.

The `milestones` array in `results.jsonl` scores the workspace every N minutes and the walk did not
use it. At that resolution the picture splits three ways: plateaus (gemma4/java 40% at 15 min and
40% at 42), reached-then-lost (**qwen35/java hit 40% at 30 minutes — exactly its unassisted final —
then 0% at 45**), and real late gains (gemma4/ruby 60% at minute 45, 100% at 59).

qwen35/java is the cleanest instance in the corpus of cria reaching the baseline result and then
going past it and breaking it.

## The mechanisms, by how often they fired

Merged from the verified findings. Occurrence counts are across all four models unless noted.

### Fixed already

- **A coloured build log read as binary (26).** `looks_binary` counted the terminal escape byte as a
  control character. `mvn compile -q` emits 645 bytes whose only control character is `0x1b`, 22 of
  them at 3.4% density — clearing both thresholds. Every Maven error became "binary data cannot be
  read as text": 212 of qwen35's 275 Java prompts, 86 of gemma4's 112. Fixed in `fdd14ea`.
  **It fires in the baseline arm too** (gemma4 13/30, qwen35 47/69), so it is a bug, not an
  explanation of the Java delta.

### The expensive tail — 46 of the 256 cost a check, broke working code, or ended a run

- **The steer states a cause, and the cause is wrong (24).** cria's supervisor writes a confident
  diagnosis and injects it as an order. The coder had usually already seen evidence pointing
  elsewhere and drops it, because an injected instruction outranks its own eyes. In all 24 the
  coder's own reading beat the supervisor's guess.
- **The steer's paraphrase quietly replaces the task (15).** The supervisor restates the job — which
  library, which output, which flag — and the coder treats the paraphrase as the spec. Nine lost
  checks, the most of any single mechanism: a decimal library removed, an EU list hand-rolled, a
  printed address dropped, an invented flag, a seeded test broken.
- **The compaction hand-off note guesses at state, and cria labels it your own finding (28).** When
  cria squeezes the conversation it asks the same weak model to write the note, and the note must
  fill a "what is broken / what remains" slot with no file on screen. It fills it from memory and
  gets it wrong; cria then pins it to every later prompt as prior work. Three checks lost.
- **Stale check results replayed as current (25).** cria re-attaches the last check output under
  "unchanged since you were last shown them — you have not cleared them yet", and instructs the
  reader to rank it above everything else. When the coder has already fixed the thing, that is a
  false statement of fact outranking live evidence, and the reader doubts reality instead.
- **cria orders work already done, or already proven impossible (22).** The supervisor's view is
  built from the coder's recent thinking, not from disk. Pure waste in every run it appeared in.
- **The file's real current text is never in front of the reader (21).** Contents clipped mid-word
  with no marker, writes answered with only `Wrote foo.rb`, edits shown with contents elided. A
  finished file reads as abandoned mid-token; a judge reported the same phantom truncation four
  times in one run.

### What the model did on its own — 187 wrong turns with no cause found

- **The answer was in its own prompt and it said the opposite (55).** The largest single kind.
- **Invents a fact about a library and never checks it (31).** Versions never released, methods that
  do not exist. Web search was in the menu on every one of these turns and used on none.

**This ratio is not yet trustworthy, and the reason matters:** the readers read 2,178 assisted calls
and zero baseline calls. "The model does this anyway" was asserted, never measured. Two clusters
filed as untraced — 19 "cria's own steer invents the specifics" and 16 "cria's own judge passes work
its own evidence disproves" — say in their own text that the cause is cria's.

## What to do next, in order

1. **Read a control.** Six baseline runs, one per language, counting only the untraced kinds. Until
   that exists, "no cause found" and "the model" are the same sentence.
2. **Per-call score curve** on the pairs with a nonzero delta: replay each write onto a fresh seed
   and score after every one. Peak score, and the minute it was reached, against the baseline twin's
   final. That single column answers whether the extra work was worse work or just cut off.
3. **Rate-check every mechanism claimed as expensive against the baseline arm.** The binary-content
   marker already failed that test. Any mechanism firing at the same rate in both arms is a cost to
   fix, not an explanation of the delta.
4. Only then fix the steer mechanisms. They are the biggest cria-caused group, but the fix for
   "the steer states a wrong cause" is to remove the diagnosis from the steer — an assist deletion,
   and the bar for that is evidence it does not also carry the wins.
