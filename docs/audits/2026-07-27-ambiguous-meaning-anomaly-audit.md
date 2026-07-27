# Anomaly sweep — ambiguous meaning in text that reaches the model (2026-07-27)

## Why this ran

Two failures in one morning, both caused by a sentence **I** wrote, both diagnosed by reading the
model's own `reasoning_content` rather than its verdict:

1. A plan challenge ended *"…or word the step to READ the route from that source instead of naming
   one."* I meant "have the STEP tell the coder to read it". The planner read it as "have the CODE
   read it" and planned a `fetch_api_docs()` function that downloads the API docs at runtime. Its
   reasoning quoted my sentence back. (`e986e57`)
2. A plan challenge said *"nothing you fetched in this session shows that route exists, so it is a
   guess."* Literally true. The planner read it as **evidence the route does not exist**, decided the
   service might be unreachable, and submitted a reachability probe as its entire plan. The URL
   returns HTTP 200. (`4ec372d`)

cria's whole job is shaping a weak model's context. Ambiguity a frontier model resolves silently is,
here, a defect with a measurable cost in derailed runs.

## Method

Five parallel agents, one orthogonal lens each, over every file in `cria/prompts/` plus inline
model-facing strings in `cria/*.py`:

1. **absence of evidence stated as evidence of absence**
2. **actor ambiguity** — who does this: the model now, the coder later, or the program being written?
3. **judge prompts that invite the model to DO the work** instead of judging it
4. **negation / conditional / quantifier ambiguity**
5. **scope, timing and referent ambiguity** — when, to what, and "above"/"below" claims that
   compaction can falsify

Findings below are the agents' work, **re-verified against source before being listed as Tier 1**.
Subagent findings are candidates, not conclusions.

---

## Tier 1 — verified by hand, act on these

### T1.1 — the ON_TRACK sentinel's own fix reintroduced the NOT_STUCK trap ✅ FIXED (`fd5c4d7`)

Both steer prompts ended by spelling out `"is NOT ON_TRACK"`, the second in final position. Running
the real `_steer_or_none`:

| reasoner reply | result |
| --- | --- |
| `NOT ON_TRACK` | → `"NOT"` → under the floor → read as an **on-track veto**, rescue cancelled |
| `The coder is NOT ON_TRACK` | → `"The coder is NOT"` → cleared the floor → **injected into the coder as its rescue** |

A negated verdict now takes its whole sentence; a bare token is still excised so the hedge survives.
Both prompts reworded, with a test asserting they never teach the bigram again.

### T1.2 — `verify.txt` has no judge fence at all

`grep -c "NO tools\|no tools"` → `verify.txt: 0`, `satisfaction.txt: 2`, `plan_coverage.txt: 1`.
It is the highest-frequency judge in the system (every step, every attempt), it lists three
tool-shaped examples (`grep -n … via the shell tool`, `read_file … with a start_line/end_line
range`, `web_fetch the library's docs URL`), and `loop.py` appends the coder's **real tool
catalogue** directly below them. The repo's own comment records the consequence: *"the reasoner
over-thought or leaked a tool call"*. `_verify` fails **closed**, so a leak means a finished step
never advances.

This is exactly the failure that `plan_coverage.txt` was measured to have and that the fence fixed
(4/8 → correct verdicts, 0/8 false alarms).

### T1.3 — `plan_evidence.txt` still carries the seed sentence, and the regression test misses it

Line 6: *"make the step READ the source for it rather than naming one"* — the byte-for-byte
ambiguity of failure #1 above, in the **final drafting instruction**, deliberately placed last for
maximum salience. `test_every_prompt_that_shapes_a_plan_says_research_is_not_runtime_discovery`
enumerates four texts (`plan`, `replan`, `submit_ungrounded`, `host_unread`). `plan_evidence.txt` is
a fifth plan-shaping text; `plan_noise_steps.txt` is a sixth. Neither is covered.

### T1.4 — a judge-invented URL is fetched with no grounding check

`guard_search_query` substitutes the reasoner's recommendation straight into the coder's live tool
call:

```python
if _looks_like_url(rec):
    url = rec if rec.lower().startswith("http") else "https://" + rec
    return _substitute_fetch(coder, msg, search_tc, url, …)
```

`grep -n "ungrounded_urls" cria/loop.py` → one hit, in the steer path only. The steer path validates;
this one does not — and this one **redirects the coder's own action**, the more dangerous class.
`search_query_judge.txt` compounds it: line 5 says *"never invented"*, line 6 asks it to synthesise
`<domain>/openapi.json`.

### T1.5 — the fetch ledger declares failed URLs nonexistent

`fetched_facts_sections.txt`: *"THESE URLS DID NOT WORK — the fetch returned an error status, so
there is nothing behind them to use. Do not fetch them again"*, and `fetch_repeat_failed`:
*"refetching returns the same failure. There is nothing behind that URL to use."*

Any error status qualifies. A 401 (**proves the route exists**), 429, 503 or a timeout permanently
blacklists a real endpoint — in a ledger built to survive compaction — and forbids the retry that
would succeed. "Refetching returns the same failure" is a claim about cria's cache stated as a claim
about the server.

---

## Tier 2 — investigated; fixed unless noted

All checked against source. Outcome marked on each.

- ✅ FIXED — **`coder_system.txt` vs `step_framing.txt`, same system message.** *"Do NOT end … while any part of
  the task is unfinished"* concatenated with *"Do ONLY this step (N of M), then stop"*. Also
  *"break the user's task into … steps"* — work cria has already done and forbids.
- ✅ FIXED (scoped to research; building an HTTP client is explicitly still fine) — **`coder_system.txt`: *"do NOT hand-write a script (requests/curl/fetch) just to pull a URL"***
  — the restrictive "just to" may be dropped, and the justification ("the dependency may not be
  installed") argues against `requests` generally, colliding with a deliverable that must use it.
- ⚠️ KEPT, deliberately — **`verify.txt`: *"NEVER on the items it demonstrably lacks"*** — my own wording from this morning.
  The judge cannot distinguish "the source lacks it" from "the coder never found it", and it only
  ever sees a tail-bounded evidence window. May pass an unfinished research step.
- ✅ FIXED (bullet 11 is now "COVER THE ASK", about coverage rather than adding a lint step) — **`plan.txt` bullet 10 forbids "run linting" as a step; bullet 11 says "Ensure code correctness
  when necessary (linting)".** Adjacent, same prompt.
- ✅ FIXED in Tier 1 (now "only when it matches one of the cases below") — **`plan_noise_steps.txt`: *"Mark a step for REMOVAL when it is NOT that"*** — negation over a
  four-way disjunction. `planner.py`'s own comments record 4-of-6 acted-on verdicts deleting steps
  the prompt explicitly excludes.
- ✅ FIXED (both examples reworded) — **Worked examples that model the banned thing** — `replan.txt`'s *"fetch the spec and use its real
  paths"* and `plan.txt`'s *"call the <specific_endpoint> FROM THE FETCHED SPEC"* both read as
  runtime discovery, three lines from the rule forbidding it. Weak models copy examples.
- **`"still above" / "below" claims that compaction falsifies** — `fetch_repeat` ("this is the SAME
  result you got before, still above; use it"), the rollup's "the recent turns follow verbatim
  below" (at a step boundary the summary is the **last** message), `refused_command` and
  `scratch_note` asserting a `web_fetch` result "above" that may never have happened.
- ✅ FIXED (both now say "EACH of them") — **Singular pronouns filled with a comma-joined list** — `submit_ungrounded` and `host_unread` say
  *"go fetch **that url**"* for N urls; the check fires once, so the remainder ship unverified.
- ✅ FIXED (input reframed off the word "NOTHING") — **`plan_host_unread.txt`'s `NONE`** is a near-synonym of the framing word `NOTHING` that dominates
  its input header — the trap shape, on the veto side.
- ✅ FIXED (both fenced) — **`selfcompact_summary.txt` / `done_summary.txt` unfenced** against act-mode, with 6/6 measured
  compactor failures already recorded in `loop.py`'s comments.
- ✅ FIXED (the ban now names write FORMS: `echo >`, `cat <<HEREDOC`, `tee`, `sed -i`) — **`cheatsheet.txt` bans `cat` for writing and prescribes `cat` for reading**, ~12 lines apart, both
  emitted together.

---

### Why `verify.txt`'s "demonstrably lacks" stays

The critique is fair — the judge sees only a tail-bounded evidence window, so it cannot truly
establish that a source *lacks* something. But the wording exists because the opposite failure was
MEASURED and expensive: a step demanding fields the API does not have held one plan open for 111
calls with zero files written. The clause is already gated on "once the coder HAS read the real
source", and the preceding rule still fails a step whose source was never read. Replacing a measured
block with an unmeasured pass is not an improvement, so it stays until a run shows it passing an
unfinished research step.

## Tier 3 — all fixed

`coder_system.txt`'s garbled *"a SHORT, clean, tasks with, concrete, verifiable steps"*; *"its tools
are listed below"* when one caller prepends them; `probegate`'s *"this turn"* read a turn later;
relative spill paths (`./tmp/read-only/…`) that never say what they are relative to.

---

## The pattern

Nearly every Tier 1 finding is one of two shapes:

1. **cria stating its own epistemic limit as a fact about the world** — "nothing shows it exists",
   "there is nothing behind that URL", "the source demonstrably lacks it". The model has no way to
   tell "cria did not find it" from "it is not there", and it acts on the stronger reading.
2. **describing work in the imperative where a verdict was wanted** — a judge prompt that opens
   "Read the request and list…" gets a plan, not a verdict.

Both are already doctrine (`docs/principles.md` #8's "the tell", and the judge-fence corollary added
today). What this sweep shows is that the doctrine was written faster than the prompts were audited
against it.

## Standing rule this produced

When a judgement comes back wrong, **read the model's `reasoning_content` before concluding it cannot
do the job**. A verdict says only that it failed; the reasoning says *where* — and "it found the
answer then lost it" needs a completely different fix from "it never found it".
