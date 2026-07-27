# Anomaly sweep — budgets that are too short (2026-07-27)

## Why this ran

Run 0727-114502 accepted a plan whose first two steps were `pip install ada_handle_resolver` (a
library that does not exist) and "create a virtualenv" — the environment-setup category
`plan_noise_steps.txt` exists to delete. The coder then spent 122 calls trying to build that
virtualenv, drifting outside the workspace until the dirguard refused it, and wrote **zero files**.

The judge that should have deleted those steps did not get it wrong. It got it right and was cut off:

```
finish_reason      : length
completion_tokens  : 2000        <- the cap, exactly
content            : 0 chars
reasoning          : 8,865 chars
```

...ending mid-sentence, after it had already concluded *"we should remove any steps that are just
environment setup. Thus steps to remove: 1 (installation)."*

A reasoning model spends the budget THINKING before it writes a word, so a small cap does not buy a
short answer — it buys no answer. And an empty answer is indistinguishable from "nothing to report",
so the judgement was skipped silently and cria acted as if it had never asked.

## Method

Five parallel agents, one kind of budget each: model output caps, content/byte caps, iteration and
retry counts, timeouts, and list/top-N caps. Findings re-verified against source before being listed
as Tier 1.

## The one sentence this sweep produced

**A bound that binds silently is worse than a bound that is too small, because nobody learns it
bound.** Four of the five dimensions independently reported the same shape: the budget runs out, the
caller reads the absence as "nothing to report" or "satisfied", and the record shows nothing.

---

## Tier 1 — verified by hand, fixed

### T1.1 — the classifier: the last 1024-token cap of a generation ✅
`classify.py` capped its verdict at **1024** on a role with `reasoning = "on"`. The 2026-07-17
truncation audit raised this whole cohort (1024/1536/2048) to 8192 everywhere else; the classifier was
missed. Worse, `classify()` cached the result unconditionally — so one truncated verdict became a
**fallback memoized under the task key for the life of the process**, misrouting every later turn of
that task. Both fixed: the budget is the shared `JUDGE_MAX_TOKENS`, and a `fallback:` result is never
cached.

### T1.2 — the completion critic ends the task and says nothing ✅
`MAX_COMPLETION_CHECKS = 4`, and at the bound `_reopen_if_unsatisfied` returned `None` **before** its
own emit. The caller reads `None` as *satisfied* and sets `Phase.DONE`. So a run that gave up while
the critic was still saying "not done" was indistinguishable, in the record, from one that genuinely
finished. The bound stays (an unfinishable task must still exit); `loop.done_unverified` now says
which of the two happened.

### T1.3 — the shape ledger truncated at the first array field ✅
`_FETCH_SHAPE_RE` read the response-shape block with a non-greedy `(.*?)\]`. A field summary marks an
array as `k[]`, so the first entry line ending in an array **closed the match** and every endpoint
after it was dropped. Reproduced: `/holders/{address} → total_handles` — the second call this task
needs — vanished from the durable ledger, under a prompt telling the coder *"use these EXACT names
and nesting; do not guess"*. Bracket matching cannot distinguish `holders[]` from the block
terminator, so it is now read by LINE.

### T1.4 — the ledger deleted webfetch's own cap disclosure ✅
`entries = [ln for ln in shapes.splitlines() if "→" in ln]` dropped the `…+more endpoints have shapes
not shown here` note, because that note carries an em dash rather than `→`. A capped list then read
as the complete set.

### T1.5 — a nested field cap built its disclosure and sliced it off ✅
`sub = _schema_field_summary(v, schemas, 8, …)` then `', '.join(sub[:8])`. The recursive call appends
`…+N more field(s)` as element 9; the slice threw it away — three lines above a comment reading
*"never a silent slice"*. Verified before and after by running the function.

### T1.6 — the planner's own fetch cut at 512 KiB, silently, and laundered the cut ✅
The coder-side path reads `MAX_BODY_BYTES + 1` precisely so it can DETECT and disclose a cut, and was
raised to 8 MB. The planner path was left at 512 KiB and read exactly the cap, so a spec whose
`paths` block sits past it arrived as valid-looking front matter. The truncated bytes then went
through `_record_fetch` → `_structure_of`, where broken JSON fails to parse — so the durable ledger
handed the coder **a 2xx with no routes**, indistinguishable from "this page isn't a spec". Now
matched to the sibling cap, with the cut detected and disclosed.

### T1.7 — timeouts sized for a fast box ✅
- `COMPLETION_PROBE_TIMEOUT_S = 45` wrapped **every** completion probe, including the repo's full
  test suite and cold `cargo check` / `tsc` builds. Not merely a slow gate: `completion_block_nudge`
  fails CLOSED on a timed-out hard-failure probe, so a repo whose tests take a minute is
  **permanently un-completable** — every round re-nudges with `TIMEOUT after 45s` and no edit can
  clear it. Now 240 s.
- The planner's gather `subprocess` timeout was **20 s** for arbitrary allow-listed repo commands
  (recursive `grep`/`find`, `git log -p`) — while `live_exec.py` gives the same class of command
  120 s. A timeout with no partial output also feeds the research floor as "this call taught it
  nothing", which is what makes the planner draft from memory. Now 90 s.

---

## Tier 2 — reported, not yet acted on

Recorded so they are not lost. Verify before acting.

- **A role's `max_tokens` silently clobbers every call-site budget.** `Role.apply` runs *after* each
  call site builds its dict, so one TOML line (`[roles.reasoner] max_tokens = 4096`) overwrites
  `ASK_MAX_TOKENS`, the planner's drafting budget, both critics and `summarize` at once — back below
  the value measured to produce zero content. Verified by running `Role.apply`: 8192 → 4096. No test
  catches it (the drift guard compares two module constants), and the shipped example only warns
  against setting it on the *coder*.
- **Truncation is only detected when the content is EMPTY.** None of the five internal primitives
  calls `massage.is_truncated`, so a judge cut off mid-JSON with `finish_reason=length` and non-empty
  content is parsed as a real verdict. The plain proxy path *does* surface a truncation indicator.
- **The stuck-step and thrash rescues are one-shot, and a no-op rescue is silent.** `_replan_tail`
  returns early when the re-derived tail is unchanged, before emitting — so "the rescue fired and
  achieved nothing" and "the rescue never fired" look identical, and the step then re-nudges
  indefinitely. This is the most likely mechanism behind the repeated 100+ call single-step runs.
- **Flail steers cap at 3 per step and reset only on ADVANCE** — so on the one step where the coder
  is most stuck, cria has three nudges and then goes permanently silent, with no emit on exhaustion.
  The plan-OFF sibling has no cap at all; one of the two is wrong.
- **Planner drafting retries and quality handbacks share one budget of 3.** Two handbacks leave one
  attempt; exhaustion discards the entire gather transcript and drops the turn to the unguarded proxy
  path.
- **`_MAX_PROPS_ATTEMPTS = 3` × 5 s permanently commits the process to an 8192 window** if llama.cpp
  is still loading (a 30-120 s operation) — every later request is then trimmed against a quarter or
  a sixteenth of the real window.
- **`MAX_PROBE_REISSUES = 2` fails open** and the emit reads `passed=True` with `gate_ran=False`, so
  a scan of the log shows a pass.
- **Edit-recovery escalation counts occurrences in the conversation**, so a compaction resets the
  clock on exactly the long stuck file escalation exists for. `editrecovery.py` has no logging at all.
- **`GATE_EVERY_CODER_TURNS = 15` resets its counter before checking** whether a gate could be built,
  so a session that can never build one gets zero periodic gates and logs nothing.
- **`webfetch.py` has no logger at all** — a 30 s fetch timeout is invisible in the record.
- **The composed gate script has no aggregate deadline**: 8-10 sections × the per-probe budget, and if
  the harness kills it mid-way the trailing sections carry no `EXIT:` sentinel and are reported as
  "no usable result".

---

## What the sweep found healthy

Worth recording, because it is most of the surface: nearly every content cap already carries an
in-band disclosure (`(chars A–B of TOTAL)`, `…+N more`, `[N characters elided]`, head+tail with a
byte-exact middle note). `probeparse` and `focustrim` deleted their clips outright on purpose.
`proberun` guarantees the syntax floor and test probes a slot regardless of ranking. The *semantics*
of timeout handling are careful throughout — partial stdout preserved, findings salvaged, 124
distinguished from 125/126/127. The failures found here are concentrated in the **values** and in
**whether expiry is recorded**, not in the design.
