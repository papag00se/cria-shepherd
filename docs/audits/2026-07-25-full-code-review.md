# Full code review — 2026-07-25

**Scope.** All ~17.7K lines of `cria/*.py` (48 modules) + the ~14K-line test suite, reviewed
against [`../principles.md`](../principles.md) for six dimensions: weak spots · half-written code ·
fragile assumptions · **deterministic-trying-to-be-fuzzy** · self-serving/shallow tests · refactor /
duplication.

**Method.** Seven parallel review agents, one per module cluster, each finding candidates across all
dimensions. **Every finding below was adversarially re-verified against the real code** (executed or
grepped) before inclusion — the doctrine's "ground truth over judgment" applied to the review itself.
Findings the agents raised that did NOT survive verification are omitted.

**Verdict.** Most core seams are sound (the reasoner-refactor seam, the gemma recursive parser,
edit-recovery, the JSON salvage ladder all held up). But the review surfaced **two holes in the
never-truncate subsystem itself** — the doctrine's #1 rule — where model-read content is silently
corrupted (H6) or the pinned task is dropped (H5); those are the most important fixes. The issues
cluster into **five themes**:

1. **Parity gaps** — several ground-truth guards are wired only on the plan-OFF path and are inert on
   the real multi-step (plan-ON) path.
2. **Deterministic-trying-to-be-fuzzy** — a few prose/keyword/digit scrapes make a *judgment* (the
   worst is in code added this session).
3. **Fail-open pockets** — a few places return empty/benign on an undecidable result instead of
   failing closed.
4. **Dead / half-written code** — unused funcs/params/aliases. (An earlier "dead failover executor"
   claim was RETRACTED — see H3; it's a documented deferral, not dead code.)
5. **Duplication & de-overfit debt** — duplicate tool-name / shell-set / code-sniff helpers; several
   English-phrase-overfit detectors.

Severity: **HIGH** = wrong result reaches the model / a guard the doctrine relies on is silently off.
**MED** = misfires on a plausible real input, safe-direction or narrow. **LOW** = cosmetic, dead, or
very-low-prevalence.

---

## HIGH — fix first

### H1 · `reasoned_noise_indices` scrapes every digit from the reasoner's prose → deletes correct plan steps
`cria/planner.py:205` · *fuzzy + fragile* · **(introduced this session, in the reasoner refactor)**
`return {int(n)-1 for n in re.findall(r"\d+", ans) ...}` reads deletion targets out of free prose.
Verified: answer `"Steps 1 and 2 look fine; step 3 is plumbing."` on a 5-step plan → drops indices
{0,1,2} — deletes the two steps it called *fine*. Fires at both call sites (initial plan +
`loop.reassess_remaining`). The never-empty guard only catches a *total* wipe; partial over-drop leaves
a corrupted subset and the loop can reach a false "done". Violates principles #2/#4/#8.
**Fix:** strict parse — honor only a clean `NONE` or a pure integer list (`re.fullmatch`), else the
safe-null (drop nothing) this path already claims.

### H2 · The anti-laundering rollup gate + vacuous-green evidence are DEAD on the plan-ON path (a test masks it)
`cria/loop.py:2665` (`_briefing_gate_ground_truth`), `:895` (`_reopen_if_unsatisfied`), consumed `:1055`/`:897` · *weak spot / parity*
`last_gate_red` and `last_gate_testless` are assigned **only** in the plan-OFF readers
(`guard_periodic_result` :2533-2537, `guard_gate_verdict` :2630-2640). The genuine multi-item path
`_verify_after_probe` sets `last_gate_flag`/`gate_git` but **never** those two — so on a real
multi-step plan `_briefing_gate_ground_truth` always returns `""` (a coder's "all tests pass" rollup
is never overridden by cria's real RED gate state during self-compaction), and the C4 vacuous-green
signal never reaches the completion critic. `tests/test_loop.py:1276` hand-sets `last_gate_red=True`
— state the production plan-ON path never produces — so it passes green over dead wiring.
**Fix:** set `last_gate_red`/`last_gate_testless` in `_verify_after_probe` from the interpreted
outcome (mirror `guard_gate_verdict`); add a test whose gate state comes from a driven gate.

### H3 · ~~The runtime failover chain-walk is dead code, tested as if live~~ — RETRACTED (2026-07-25)
**This finding was wrong and is withdrawn.** The failover *mechanism* IS used and was deliberately built:
`router.route()` (`routing.py:58`, live at `server.py:553`) walks the failover chain for RESOLVABILITY —
a role with a missing key/binary is skipped and the chain collapses to whatever resolves — and
`upstream.chat` retries the same endpoint once on a transient timeout, which `failover.py:8-11` calls
"**the load-bearing behavior**" under the single-local-model posture. Both landed in commit `90b2a0d`
("feat(failover): runtime failover executor + retry-same-on-timeout + per-role endpoints").

What is *not* wired — `route_chain()` + `failover.run()`, the **cross-role walk on a runtime call
failure** (a resolvable role that then 429s/503s) — is a **deliberate, documented deferral**, not dead
code: `failover.py:10-11` states "Chain-walk matters once distinct endpoints exist (per-role `base_url`)
or cloud roles are enabled", and `docs/port-fidelity-audit.md` files it under "Deferred — cloud routing"
(trigger: "first `local_only = false` with a real key"). Unit-testing a built-ahead executor is correct
practice, not "false confidence." **No action** — it activates when a multi-endpoint / cloud-role config
is used. Lesson for this audit: a "dead code / tested as if live" call must be checked against the
module's own docstring and the deferrals ledger before it ships as a HIGH finding.

### H4 · `clean_gate_output` raw-scrapes failing-check output → re-buries the real error it exists to surface
`cria/probegate.py:166-195` · *weak spot / fuzzy* · model-facing on every multi-line failing check
For a non-clean section it forwards **every** raw `text.splitlines()` line as an "error-class problem",
never calling the structured `parse_*`. Verified: a failing pytest section renders to the model with
the `=== FAILURES ===` banners, underscore rules, source echoes, and `1 failed in 0.03s` intact —
while the *sibling* `completion_block_nudge` distills the same failure to one line
(`test_lambda.py:15: AssertionError: 400 != 200`). The model gets two divergent renderings, the raw
one re-creating the exact "buried the one real error under plumbing" footgun this function's docstring
claims to cure. Misfires on every multi-line tool (pytest/cargo/go/tsc).
**Fix:** run each section through `proberun.interpret_probe_output` and render the parsed `findings`,
as `interpret_gate` already does.

### H5 · `content_reduce` silently deletes source-code keywords from a comment-dominant file the model reads — a direct rule #5 violation
`cria/content_reduce.py:43` (prose gate) + `:330` (`_looks_like_code`), reached from `contextfloor.py:300` · *fuzzy + weak spot* · **the single worst finding — it corrupts the model's authoritative read**
`_looks_like_code` is a structural sniff (≥40% lines end `:{};` or ≥12% symbol density). A module dominated by docstrings/comments with a few code lines scores as prose-and-not-code, so `strip_prose_text` runs. Verified: a comment-heavy module → `looks_like_prose=True, looks_like_code=False` → `for item in items` and `is not None` are **destroyed**. Under window pressure the floor reduces a `read_file` result this way → the model edits from and re-emits broken code. This is exactly the silent mid-content corruption of model-read content rule #5 exists to prevent — a confirmed hole in the very guard built to prevent it (a semantic "is this code?" judgment masquerading as deterministic policy).
**Fix:** for the unknown/`None`-content-type path, treat "code" as the default — bail out of the stripper if **any** line trips `_looks_like_code`'s structural signals, rather than requiring the *whole blob* to read as code.

### H6 · The floor drops self-compaction's pinned task + rollup summary (marker sets out of sync; a comment falsely claims "floor-protected")
`cria/contextfloor.py:61` vs `cria/selfcompact.py:36,37` / `loop.py:107` · *weak spot / fragile*
`_PROTECT_MARKERS = ("⟦ctx:briefing⟧", "___CRIA_GATE_", "⟦ctx:compacted⟧")` — verified to **omit**
selfcompact's `⟦ctx:rollup⟧` (SUMMARY_MARKER), `⟦ctx:task⟧` (TASK_MARKER), and `⟦ctx:continuation⟧`.
selfcompact runs *before* the floor (`loop.py:1048`); its `⟦ctx:task⟧`/`⟦ctx:rollup⟧` messages are
`role:"user"`, outside the last-user active span, carrying no protected marker → `_drop_oldest`
deletes them as the oldest droppable turns. Reproduced at the 8192 `_FALLBACK_WINDOW` (routine when
`/props` detect misses, e.g. GPU busy): `TASK verbatim: False`, `ROLLUP verbatim: False`. The session
loses its north-star and the floor re-digests the rollup into a summary-of-a-summary — the exact
"rollup-of-a-rollup task-inversion" selfcompact was built to prevent. `selfcompact.py:36` literally
annotates SUMMARY_MARKER "floor-protected" — it is not.
**Fix:** add `SUMMARY_MARKER`, `TASK_MARKER`, `CONTINUATION_MARKER` to `_PROTECT_MARKERS`; extend the
sync test (`test_contextfloor.py:34`) to assert all three.

---

## MED — real misfires, mostly safe-direction or narrow

### Parity / fail-open
- **M1 · Completion critic judges the compaction SUMMARY, not the real task.** `loop.py:895`
  `_reopen_if_unsatisfied` feeds `judge_satisfaction` `task = _history_root(messages)[0]` — after a
  harness compaction that's the *summary* (which may have dropped a requirement), not the authoritative
  `sess.plan.task` that the sibling `_replan_tail` correctly uses. Green-but-incomplete slips through.
  **Fix:** use `sess.plan.task`.
- **M2 · Periodic ground-truth check-in + reasoned thrash-assist are plan-OFF-only.** `loop.py:1593`
  (`coder_turns++` only in `_drive_single_item`), thrash/`track_gate_progress` only in plan-off readers.
  A multi-step plan editing many different things for ~90 turns without spiraling gets no
  `GATE_EVERY_CODER_TURNS` check and no thrash-assist — the exact scenario that guard was built for.
  **Fix:** increment `coder_turns` and run the periodic gate/thrash in `_work_item`/`_verify_after_probe`.
- **M3 · Timeout collapses into fail-open-toward-done.** `proberun.py:392`/`:347` A Test probe that
  times out (exit→`None`, e.g. a 46s pytest hitting the 45s cap) with no salvaged finding yields
  `findings=None, failed=[]`; `guard_gate_verdict` doesn't consult `unran_probes`, so the "done" is
  accepted GREEN. A timeout means the command ran and did *not* finish — it must fail closed (#13).
  **Fix:** carry a `timed_out` flag distinct from launch-failure; treat it as not-clean at completion.
- **M4 · Buffered/proxy path returns an empty completion on a non-JSON 200.** `server.py:679`
  `except (JSONDecodeError, TypeError): return {}` → the client sees a *successful but empty* turn (an
  upstream `200 <html>502…`), fail-open-toward-empty. **Fix:** raise `UpstreamError` → clean 502/failed.
- **M5 · Oversized-spill bypasses the repeat-fetch gate.** `writeproxy.py:439` On a repeat fetch
  `fetch_nav` returns the "you already fetched this" refusal, but the next lines call
  `oversized_spill` and `return _spill_command(...)`, discarding it. `OVERSIZE_CHARS`=16 KB, so most
  specs spill → the repeat-fetch guard is a no-op for exactly the large-doc class that causes fetch
  loops. **Fix:** if the fetch was refused, return that refusal before spilling.

### Deterministic-trying-to-be-fuzzy
- **M6 · `_looks_like_domain` accepts dotted code identifiers as API domains.** `searchloop.py:78`
  Verified: `urllib.request`, `requests.get`, `os.path` all pass; `task_api_domain("use urllib.request
  to call the Stripe API")` → `"urllib.request"`. Feeds the **live** search-escape, burning both
  ground-truth escapes fetching `https://urllib.request/openapi.json`. **Fix:** restrict the TLD label
  to a public-suffix set / reject known stdlib module names (a tighter *structural* trigger, not a
  reasoner call).
- **M7 · `strip_think` regex/`rfind` token mismatch leaks `<thinking>`-dialect reasoning into the parsed JSON.**
  `jsontext.py:14`/`:28` `_THINK` requires `<think\b` (so `<thinking>` isn't stripped), and `rfind("<think")`
  finds `</think`-less tail → the reasoning stays and `_scan_object` returns the FIRST brace object.
  Verified: a `<thinking>…{"engagement":"question"}…</thinking>\n{"engagement":"task"...}` string parses
  to the *reasoning's* object → under-engages a real coding task. Affects every JSON-consuming caller
  (classifier/critic/planner). **Fix:** use `<think(?:ing)?` consistently in both places.
- **M8 · Gate error-class filter is English-phrase + py/js/ts-code matching.** `probeparse.py:506`/`:520`
  `_ADVISORY_PHRASES` (English substrings) never match under a non-English locale → advisories gate;
  `_STYLE_CODE` (`W###|E###|C####|R####`) doesn't recognize rubocop `C:` severity or golangci `(ineffassign)`
  → Ruby/Go style offenses gate as errors (safe direction, but floods). **Fix:** scope `C####/R####`
  to the pylint family; document that non-py/js/ts advisory severities intentionally gate.
- **M9 · Rumination marker arm is a 22-phrase English list + count≥6.** `rumination.py:27` Overfit to
  English/one dialect (never fires for other reasoners → only the length backstop protects) and can
  false-abort a verbose-but-productive English reasoner. Streaming precludes a reasoner call here.
  **Fix:** make the length + `degenerate_tail` backstops primary; demote the marker arm; base-rate it (#15).
- **M10 · Search-repeat gate over-matches short distinct queries.** `searchloop.py:42` `overlap≥2 and
  Jaccard≥0.5` refuses `"python requests timeout"` vs `"python requests retry"` (2 shared / 4 union).
  **Fix:** require ≥3 shared words (or scale the threshold with query length) for short queries.

### Deletion/redirection of correct content (principle #2)
- **M11 · Write-success reframe keys on `⟦ctx:wrote⟧`, which lives in the heredoc source.** `writeproxy.py:793`
  Safe on Codex (stdout-only), but any harness that echoes the command into the result gets a fabricated
  "Wrote {path}" even on a *failed* write — harness-agnostic fail-toward-false-success. **Fix:** require
  the token as a runtime-emitted last stdout line / unique nonce, not a substring of the whole result.
- **M12 · `_search_command` surfaces a raw Python traceback as the model's `web_search` result.**
  `writeproxy.py:510` The lowered `curl … | python3 -c json.load … && printf` has no error handling; a
  429-HTML/empty body makes `json.load` raise and the harness records the traceback as the search output
  — the same class as "model read a refusal as an API problem and hallucinated an endpoint." **Fix:**
  try/except a clean model-facing message; don't gate the pointer behind the parse's exit code.
- **M13 · `_DIALECT_MARKER` truncates a plan step at a bare `<message>`/`<think>`/`<channel>` mention.**
  `planner.py:86` via `_clean_step`. Verified: `"Handle the <message> XML element in the parser"` →
  `"Handle the"`. Any XML/streaming task whose plan names such a tag is silently corrupted. **Fix:**
  strip only the pipe-delimited leak forms (`<|tool_call|>`…), not bare `<tag>` HTML/XML.

### Concurrency / transport
- **M14 · claude-CLI escalation sends only the latest user line as the prompt.** `claude_cli.py:66` →
  `latest_user_text`. On the first (un-resumed) escalation Claude gets one line — no system, no task
  from an earlier turn, no tool outputs. **Fix:** serialize system + recent turns + tool results on the
  first call.
- **M15 · claude-CLI `--resume` bleeds session state across sessionless conversations.** `claude_cli.py:51`
  No session id → every request collapses onto key `"main"` on a shared provider instance → the second
  unrelated conversation resumes the first's Claude session (violates session-scoped guard-state, #23);
  `_sessions` also unbounded. **Fix:** never resume without a real session id; bound the dict.
- **M16 · Chat SSE streams aren't registered for shutdown drain; only the Responses path is.**
  `server.py:581` vs `:778`. A `/v1/chat/completions` stream in flight during a restart (this repo
  restarts constantly) gets the bare mid-stream EOF the drain mechanism exists to prevent. Codex uses
  the Responses path (covered), so MED-leaning-LOW. **Fix:** register/unregister the chat-path heartbeat too.

### Duplication (MED-weight)
- **M17 · Divergent `SKIP_DIRS` — the syntax/lint floor descends into `vendor/bin/obj/coverage`.**
  `linterprobe.py:58` (used by the floor) lacks the non-hidden generated dirs that `probediscovery.py:73`
  prunes → `php -l` over thousands of vendored files. **Fix:** share one `SKIP_DIRS` constant.
- **M18 · A protected tool-result anchor is dropped when its assistant call isn't independently protected.**
  `contextfloor.py:455` (`_strip_orphan_tools`) + `_protected_mask`/`_drop_oldest`. A `tool` result can
  carry a protect marker while its paired assistant `tool_calls` message carries none → the call is
  dropped as oldest, then `_strip_orphan_tools` removes the "protected" result as an orphan. The real
  gate survives *only* because its shell command happens to echo `___CRIA_GATE_` (so the call is
  protected too) — an implicit coupling the code never enforces; any anchor whose call lacks the marker
  is silently discarded, and a dangling call (result dropped, call kept) is rejected by the strict
  templates this module cites. **Fix:** protect the assistant message whose `tool_calls[*].id` matches a
  protected result (and prune calls with no surviving result).

---

## LOW — dead code, cosmetics, very-low-prevalence

- ~~**L1 · Dead `route_chain`/`failover.run`**~~ — VOID (see the H3 retraction): a documented deferral,
  not dead code.
- **L2 · Dead `_assistant_message(raw: bytes)`** `planner.py:519` — no callers (near-dup of
  `_assistant_message_obj`). Delete.
- **L3 · Dead `reduce_lossless`** `content_reduce.py:48` — zero callers; `webfetch.reduce_for_cache`
  superseded it; its two tests only prove it transforms its own fixtures. Delete fn + tests.
- **L4 · Dead alias `has_incomplete_write_args`** `massage.py:991` — only tests reference it. Delete,
  update tests to `has_incomplete_tool_args`.
- **L5 · Dead `completion` param** `turnstats.py:64` — `observe(completion, …)` never reads it; the
  elaborate `test_turnstats` completion fixtures are ignored (would pass with `{}`). Drop the param.
- **L6 · Misplaced `unittest.main()`** `tests/test_loop.py:2538` (dup of `:3803`) — 21 TestCase classes
  are defined *after* it, so a direct `python tests/test_loop.py` silently skips 42% of the suite
  (pytest/CI unaffected). Delete the stray block.
- **L7 · `author_search_fetch` decline is a loose substring.** `loop.py:2988` `"NONE" in text[:12].upper()`
  → `"Nonetheless, fetch https://…"` reads as a decline and the real URL is discarded. **Fix:**
  `text.strip().upper().startswith("NONE")`.
- **L8 · Second, drifted shell-tool set.** `loop.py:2810` `_SHELL_TOOLNAMES` is a hand-copy of
  `shelltool.SHELL_TOOL_NAMES`, already drifted (missing `shell_command`, adds `container.exec`) → a
  `shell_command` harness isn't flagged shell-capable to the steer reasoner (#18). **Fix:** derive from
  `shelltool.SHELL_TOOL_NAMES`.
- **L9 · `do_POST` doesn't strip the query string** (`do_GET` does). `server.py:347` →
  `POST /v1/chat/completions?x=1` 404s. **Fix:** `self.path.split("?",1)[0].rstrip("/")`.
- **L10 · Buffered `chat` retry classifies with `status_code=None`.** `upstream.py:328` A genuine 429/408
  on the buffered path is mis-classified `MODEL_UNAVAILABLE` (no retry-after honoring). **Fix:** pass
  `e.code` to `classify_failure`.
- **L11 · `parse_pycompile` dead chained comparison.** `probeparse.py:450`
  `"error" in t.split(":")[0:1] == ["error"]` parses as a chained comparison → always False; the
  `"Error" in t` disjunct carries it. Inert dead logic that will mislead a future edit. **Fix:** the
  intended `t.split(":",1)[0].strip().lower().endswith("error")`.
- **L12 · `dirguard` false "Writing" refusal on an external READ under `read` level.** `dirguard.py:130`
  `_WRITE_VERB.search(command)` scans the whole command, so `grep pat /etc/hosts > local.txt` (external
  read + internal write) is refused with a reason that misnames it. Best-effort-not-a-sandbox mitigates.
  **Fix:** scope the write test to whether the *external token* is the redirect/verb target.
- **L13 · Dead-but-benign / de-overfit debt:** `reframe_compaction` keys on an exact English sentence
  (`loop.py:1934`) — brittle to harness/wording drift; `_repair_double_escaped` (`writeproxy.py:822`)
  can expand a legit one-line file containing literal `\n`; Add-File `apply_patch` with unprefixed `-`
  lines silently drops them (`massage.py:1105`); leaked-call recovery can eat a pure text answer that
  merely quotes tool-call dialect (`massage.py:429`); `apply_reasoning(off, openai)` emits
  `reasoning_effort:"none"` which api.openai.com rejects (`reasoning.py:38`); `_gemma_scalar` uses
  Python `int()` (`1_000`/`+5`) diverging from the ported i64 dialect (`massage.py:654`); `_strip_exec_envelope`
  strips a re-presented read's own leading/trailing blank lines (`writeproxy.py:694`).
- **L14 · `tokenratio.MAX_RATIO = 3.5` can't cover ~4× density content.** `tokenratio.py:22` With
  `est=chars/4`, near-1-char/token content (dense CJK, base64) has true ratio ≈4.0 > 3.5 → under-budgeted
  → overflow, recovered only by the `_overflow_refit` 400+retry, but `record` re-clamps to 3.5 so *every*
  such turn pays a wasted round-trip. **Fix:** raise `MAX_RATIO` to ≥4.0, or persist the refit's true density.
- **L15 · `_PROSE_FIELDS_EXCLUDE` is dead (∩ `_PROSE_FIELDS` = ∅).** `content_reduce.py:300` — the
  `and k not in _PROSE_FIELDS_EXCLUDE` clause can never change the result. **Fix:** delete the clause.
  (`reduce_lossless` is likewise dead — see L3.)
- **L16 · Density ratio learned/consumed on mismatched estimate bases.** `upstream.py:175` (`est_total`,
  one `//4` over the join) vs `contextfloor.py:141` (Σ per-message `//4`). `Σ⌊len/4⌋ ≤ ⌊Σlen/4⌋` → the
  floor budgets slightly loose (overflow direction), bounded + refit-recovered. **Fix:** compute
  `sent_estimate` with the same per-message summation the floor uses.

---

## Cross-cutting themes

**Parity gaps (plan-OFF vs plan-ON).** H2, M1, M2 are the same shape: a ground-truth guard was built and
tested on the plan-off path and never wired into the multi-item path — where the doctrine most needs it.
Worth a dedicated sweep: grep every `sess.last_gate_*`/`coder_turns`/`gate_stall` writer and confirm the
plan-ON path (`_work_item`/`_verify_after_probe`) maintains the same state.

**The fuzzy catalog (deterministic-trying-to-be-fuzzy).** Ranked by risk: H1 (digit-scrape, *deletes*),
M6 (`_looks_like_domain`), M7 (`strip_think` token), H4/M8 (gate raw-scrape + phrase filter), M9
(rumination markers), M10 (search Jaccard), L7 (`NONE` substring). The steer/repetition/flail detectors
(`_actions_match`, `_flail_candidate`, `_STRUGGLE_RE`) are correctly *triggers* feeding a reasoner and are
**not** flagged. `classify.py`/`toolmenu.py` are structural, not fuzzy — also clean.

**Duplication map.** One shared `tool_name(t)` helper wanted (copy-pasted across toolmenu/massage/
writeproxy/shelltool, one divergent variant); `_looks_like_code` ×2 (webfetch/content_reduce, divergent);
`SKIP_DIRS` ×2 (M17); `_SHELL_TOOLNAMES` vs `SHELL_TOOL_NAMES` (L8); timeout-summary logic in 3 probe
places. None are hot bugs; all are drift risk the doctrine's "match by family / one owner" argues against.

**Test-quality gaps.** Two structural: server/upstream tests mock at the HTTP layer so real socket faults
(client disconnect, reset mid-stream) and the *live-path* absence of failover (H3) + chat-drain (M16) are
never exercised; probe parsers are tested only against fixtures reverse-engineered from the parsers (no
"real tool output" tier), so a pytest/eslint/tsc format change passes CI while breaking production. Plus
the hand-set-state masks noted in H2, and tautological fixtures (rumination L13, turnstats L5, dead
reduce_lossless L3). The rest of the suite is strong (dirguard footguns, event-sourced counting,
execution-based writeproxy/heredoc tests, the prompt-agnosticism invariants).

---

## Recommended fix order

1. ✅ **H5 + H6** — the never-truncate holes (silent code corruption + dropped north-star task). *Done `85abe97`.*
2. ✅ **H1** — strict-parse the noise judge (my digit-scrape regression). *Done `d4d993d`.*
3. ✅ **L6, L7, L8, L9, L2, L4, L11, L15** — trivial safe wins. *Done `dad04da`.*
4. ✅ **H2 + M1 + M2** — the plan-ON parity sweep. *Done `e39426d`.*
5. **H4** — route gate rendering through the parser. **DEFERRED** (attempted + reverted 2026-07-25): the
   simple in-place fix (`parse_output(family='')` per section) regresses pytest rendering — `family=''`
   misses pytest `FAILED …` short-summary lines, and `family='pytest'` is only an accidental superset that
   mishandles non-Python ecosystems. Done right it needs the `gate_plan` threaded through
   `clean_gate_results` + its 4 loop.py call sites so each section gets its EXACT family (with a
   content-sniff / generic fallback for historical sections whose plan is no longer in hand). Lowest
   real-world impact of the HIGHs — the model ALSO receives the *distilled* rendering via
   `completion_block_nudge`; `clean_gate_output` is a noisier duplicate. The existing `clean_gate_output`
   tests also use a non-real pyflakes fixture (no `:` after the column) and want realignment as part of
   this. *Do as a focused, separately-tested change.*
6. ~~**H3** — failover~~ **RETRACTED** (see H3 above): the failover mechanism is live; the cross-role
   runtime-walk is a documented deferral, not a bug. No action.
7. **M-tier** by cluster (M6/M7 fuzzy fixes and M18 anchor-protection next).

**Tally (corrected):** 5 HIGH · 18 MED · 16 LOW — **H3 retracted** (it was not a defect). Every remaining
finding re-verified against real code. The never-truncate subsystem (H5, H6) and the plan-ON parity gaps
(H2, M1, M2) are the two structural themes; both are now fixed. Note L1 (LOW) also referenced H3 and is
void.
