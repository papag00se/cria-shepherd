# Anomaly sweep — "cria speaking over the source" (2026-07-26)

## Seed anomaly

A pytest **collection error** — two test files sharing a basename plus a stale `__pycache__` —
printed its own diagnostic *and the fix*:

```
import file mismatch: … HINT: remove __pycache__ / .pyc files and/or use a unique basename
```

cria told the coder:

```
$ python3 -m pytest -q — tests/test_resolve_handles.py: test failed
```

The model then edited test *logic* for ~700 calls inside a file that could not be collected, so no
edit it made could ever turn the gate green. Fixed in `96becb0`; a second instance (a broken
`conftest.py` reported as the stack frame instead of `ModuleNotFoundError`) fixed in `04d18ed`.

The operator's question — *"why only that kind of error? those canned phrases seem dangerous too"* —
triggered this sweep.

## The class

cria sits between a coding harness and a small local model. It runs the repo's real checkers, fetches
real documents, and re-presents both. **Every point where cria's own words replace, mask, or outlive
what a real source actually said is the same defect**, and it is invisible from the model's side —
which is why these survive.

Two things are *not* the same and must not be conflated:

- **Selection** — choosing which real lines to show (e.g. dropping `imported but unused`, which is not
  an error). Load-bearing and measured; keep it.
- **Substitution** — cria authoring text where the source's own words belong. Never justified.

## Dimensions swept

1. Substituted words — canned stand-ins that replace a tool's message
2. Dropped content — real bytes silently discarded before the model reads them
3. Paraphrase-as-fact — model-facing claims about state cria inferred rather than observed
4. Envelope leakage — cria's own plumbing text consumed as if it were source content
5. Internal contradictions — one part of cria promising what another does not deliver

Five agents, one pass, in parallel. Findings deduped across dimensions and credited to the most
specific finder. Items marked **[verified]** were reproduced or read in the code by the synthesizer;
the rest are agent findings not yet independently confirmed.

---

## Tier 1 — bug-class now, small, fix-on-sight  ✅ ALL DONE (`fb36d60`, `3c3dd7b`)

- [x] **`raw=true` still discards the model's `find=` — `1f7adf3` never reaches the live path.**
      `writeproxy.py:435-436` nulls `find` before `fetch_nav`, and it is the only caller from the
      model path. The fix and its test both drive `fetch_nav` directly, so the test passes while the
      real boundary is untouched; nulling `find` also forces the spill branch, reproducing the exact
      "saved 96,199 chars, go grep it" reply the fix set out to kill. **[verified]**
- [x] **A pytest collection error vanishes when any other test failure localized.**
      `probeparse.py:335-336` returns before `_pytest_collect_errors` is consulted, so one ordinary
      failure hides an entire uncollectable file. This is the shape run 11 actually had — `96becb0`
      would not have rescued it. **[verified — reproduced]**
- [x] **The guard hiding cria's gate output from the work log is dead code.**
      `loop.py:1878` tests for the literal `"PROBE_EXIT"`; the emitted sentinel is `"EXIT:"`
      (`proberun.py:111`) and the section prefix is `___CRIA_GATE_` (`probegate.py:45`). The string it
      checks appears only in test fixtures. Raw pytest/lint dumps land in the work log as the coder's
      own actions, feeding the step critic, the re-derivation, the satisfaction judge and the
      completion briefing. **[verified]**
- [x] **The coder can overwrite the ledger's ground truth with prose.**
      `_extract_fetches` (`loop.py:2827-2845`) reads every message role, so a coder sentence quoting
      `HTTP 400 · <url>` replaces the real `HTTP 200`. The `898ef78` split then files that URL under
      "THESE URLS DID NOT WORK — do not write code against them" with its real endpoints still
      attached. This re-enables the documented runG failure (coder insisted on a 400, steer parroted
      it, 40 turns lost) through the door the ledger exists to close. **[verified — reproduced]**
- [x] **A Brave API error body is rendered to the model as "no results".**
      `writeproxy.py:522` pipes `curl -sL` (no `-f`, no status check) into `json.load`; a 401/422/429
      error object parses fine, `.get("web")` is None, and the spill file gets the literal
      `no results`. The model concludes the web has nothing and starts guessing. The planner's
      in-process path (`planner_tools.py:255`) surfaces the real `HTTP Error 429` — the two paths have
      diverged.
- [x] **The py_compile syntax floor takes the echoed source line as the diagnostic.**
      `probeparse.py:502-503` tests `"Error" in t`, so for `raise ValueError("x"` the source line wins
      and `SyntaxError: '(' was never closed` two lines below is discarded. This is the tier-0 check
      for every Python workspace.
- [x] **The repeat-*fetch* refusal is status-blind.** `webfetch_guards.txt:8` / `webfetch.py:536-537`
      says "this is the SAME result you got before, still above; use it" — computed from assistant
      `tool_calls` only, never reading the returned status. A URL that 404'd is refused with "use it."
      The untouched twin of `898ef78`.
- [x] **The cap-truncation guard tells the model a file exists that cria refused to write.**
      `truncation_guard.txt:2` says "re-reading the file will show it ending abruptly", but the remedy
      is injected before anything is lowered and the partial write is dropped on exhaustion. Nothing
      is ever written. The self-cut sibling (`truncation_guard_selfcut.txt`) states this truthfully.
- [x] **"The repo's automated checks pass" is asserted when no check ran.**
      `done_incomplete.txt:1`, emitted at `loop.py:1683-1688` on the no-shell path whose own comment
      reads "No shell tool → the objective gate can't run."
- [x] **rustc `note:` sub-spans become a phantom "compile error" at the wrong line.**
      `probeparse.py:206` — a `note:`/`help:` line matches no header, so its `-->` falls to
      `DEFAULT_RUSTC_MESSAGE`, laundering an advisory into an unfiltered error-class finding.
- [x] **The repeat-search refusal can point at a file that was never written.**
      `webfetch_guards.txt:6` names a target derived from the query string; only the synthetic Brave
      path spills (`writeproxy.py:526`), so a harness-native search is refused with a pointer to a
      nonexistent file. (Partly self-inflicted: `81d9b4d` added the pointer.)

## Tier 2 — structural, scoped  ✅ ALL DONE (`f0e2a1d`, `9a4c7b2`)

- **`is_advisory` is applied per raw line** (`probegate.py:175`), severing multi-part diagnostics
  (`note:` continuations) and letting an all-warning non-zero build (`-Werror`, `deny(warnings)`,
  tsc `noUnusedLocals`) render as "no error-class problems" — a false green.
- **A refused tool call is invisible to the coder** (`loop.py:3306-3310`, `3339-3346`): reported only
  via `_add_note`, which is stripped before the model. `440ce83` fixed this for the self-cut *write*
  path only; generalize it to every refusal.
- **Lossy `content_reduce` output is swapped in unlabelled** (`contextfloor.py:344-346`), read by the
  model as verbatim tool output.
- **Floor lever 5 pops whole turns silently** (`contextfloor.py:395-423`), unlike `_drop_oldest`,
  which synthesizes a `⟦ctx:compacted⟧` note.
- **Planner exec timeout discards all partial output** (`planner_tools.py:104-105`), contradicting the
  never-clip comment three lines above.
- **`_salvage_array_steps` silently shrinks a plan** (`planner.py:164-167`) — a 7-step plan becomes a
  valid-looking 3-step plan with no counter or log.
- **Gate sections that never came back vanish** (`probegate.py:337-338`): `results` becomes a subset of
  `selected` and nothing reports the gap, so a truncated gate reads clean.
- **A timed-out check reads as "no signal" and its partial output is deleted**
  (`probegate.py:147-149`, `199-202`, `295-299`), contradicting `completion_block_nudge`, which fails
  closed on the same bytes.
- **Satisfaction evidence hoists any message containing a marker** (`loop.py:1891-1894`), so a coder
  parroting `⟦ctx:rollup⟧` gets its own claim promoted to authoritative history.
- **Marker forgery grants a dirguard exemption** (`writeproxy.py:559`): a model-authored command
  containing `___CRIA_GATE_` skips the refusal check.
- **The search-read denial note is written back into the message stream** (`loop.py:1043-1046`) and
  later read as coder tool output by the critic and the briefing.
- **Undisclosed webfetch caps** (`webfetch.py:348`, `:352`, `:380`, `:327`, `:431`) — field/endpoint
  lists truncated with no "+N more".
- **`trim_error_squash` mislabels what it removed**: the note says the attempts "returned errors
  (non-zero exit)", but `focustrim.py:116-118` exempts non-zero exits and classifies on a bare
  `\bnot found\b` substring, so an exit-0 result can be deleted and reported as an error.

## Tier 3 — bigger  ✅ ALL DONE (this pass, at the operator's instruction to fix all three tiers)

- **`coder_system.txt` hardcodes tool names it cannot guarantee** (`:5,18-20,30`) while also saying
  "never invent tool names"; when the harness ships its own write tool the synthetic ones don't exist.
  Same for `read_file with start_line/end_line` in `verify.txt:11` and `reasoner_coder_tools.txt:1`.
- **`task_complete` is described as whole-task but consumed as step-done** (`tool_descs.txt:10` vs
  `step_framing.txt:1` and `loop.py:2270-2292`) — unsatisfiable at step 2 of 7.
- **Package installs are forbidden by the planner and taught to the coder** (`plan.txt:10`,
  `plan_noise_steps.txt:7` vs `pep668_remedy.txt:1`, `cheatsheet.txt:21,26`).
- **Tests: automatic or the coder's job?** `plan.txt:10` vs `briefing_checks.txt:7` and
  `satisfaction.txt:5`.
- **The briefing envelope is marker-free and therefore forgeable** (`loop.py:103-106`, `1784-1797`).
- **Doctrine drift in `AGENTS.md`** (`:28` workspace pollution vs the `./tmp/read-only` spill; `:29`
  fail-closed vs the acknowledged fail-open exits at `loop.py:1623,1689`).

---

## Posture check — what is right

- **The architecture is sound and the doctrine is doing its job.** Every finding here is a *leak* in a
  principle the project already states correctly, not a missing principle. The sweep's five lenses were
  all derived from `docs/principles.md`.
- **Selection is measured and correct.** The error-class filter that drops `imported but unused` exists
  because showing it made the model "fix" working code ~20× in one session. That is grounded filtering,
  not substitution, and it should stay.
- **The strongest mechanisms held up.** The ledger's ok/failed split, the spill pointer's post-`cp`
  ordering, `guard_ground_truth`'s silence on a couldn't-run gate, and the satisfaction-gated empty
  replan were all checked and cleared.
- **The fail-closed posture is real.** `probegate`'s completion path fails closed on a timeout even
  where a sibling path doesn't — the inconsistency is the finding, not the posture.
- **Three of this round's Tier 1 items are incomplete fixes from today**, found by pointing the sweep at
  the author's own work. That is the process working, not the code rotting.

## Method note

Findings that critique fixes made earlier the same day (`1f7adf3`, `96becb0`, `81d9b4d`) were
independently verified by the synthesizer before being recorded — two by reproduction, one by reading
the caller. Agent findings are candidates, not conclusions.


---

## Outcome (2026-07-26, same day)

All three tiers fixed at the operator's instruction. Suite 1183 → 1208 green.

**Two findings were overstated and are recorded as such** rather than "fixed":

- `verify.txt` was cited for hardcoding `read_file with start_line/end_line`. It already conditions
  on the real menu ("doable with a tool the coder actually has (its tools are listed below)"), so
  only the reasoner-facing sibling needed the same treatment. Agent findings are candidates.
- The briefing envelope's forgeability has no clean fix that preserves its design: it is deliberately
  marker-free so `strip_history` spares it, and there is deliberately NO server-side copy. It is now
  line-anchored and requires both delimiters, which stops the accidental parrot — the case that
  actually occurs — and the residual risk is documented rather than papered over with machinery.

**The distinction that came out of this sweep**, now in `AGENTS.md`: cria may SELECT which of a
checker's real lines to show (grounded, measured — dropping `imported but unused` stopped the model
"fixing" working code ~20× in a session). It may never SUBSTITUTE its own words for what the tool
actually said. Every Tier-1 item was an instance of the second thing wearing the first thing's
clothes.
