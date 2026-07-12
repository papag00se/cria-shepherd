# cria Port-Fidelity Audit — cria (Python) vs Codex Local (Rust)

**Date:** 2026-07-07. **Method:** anomaly sweep, 5 parallel agents, each comparing a
cria subsystem against the Rust original in `codex-rs/routing/src` (+ `core/src/local_routing.rs`)
and the specs in `docs/spec/`. Seed anomaly: `shell_args` hardcoded the tool arg field
`command`, but Codex's `exec_command` needs `cmd`, so every lowered call was rejected and
the plan loop stalled on step 1.

## The one-line answer

cria ported the **Massages** (output *repair*) faithfully — that is its strength — but
**dropped the Steering**: the local-coder system prompt, the no-action escalation, the
loop detectors, all ground-truth (probes / file-changed / completion gating), and runtime
failover. A weak model's *output* gets repaired fine, but nothing keeps it *on task*, so it
narrates instead of acting, loops within a step, and its "done" is judged from prose. That
is why the same model completes tasks under Codex Local and stalls under cria.

## Why it works in Codex Local but stalls in cria (the mechanism)

1. Codex sends its full ~20 KB apply_patch-heavy system prompt. Codex Local **replaces** it
   with a concise local-coder prompt on every local coder turn *specifically because* a 9B
   "follows that volume of instruction and emits apply_patch no matter what." cria passes it
   straight through and only appends a cheat-sheet → the model is miscued (your 72 K-token
   write_file flail).
2. The coder narrates a patch instead of emitting a tool call. Codex Local fires an
   escalating no-action prompt ("pasted code is discarded… your ENTIRE next message must be a
   SINGLE tool call"). cria's nudge is a soft "keep working" → never corrected.
3. When cria *does* build a tool call, gaps in the lowering (field name, alias set, array
   args, literal `\n`) get it **rejected by the harness** → the model retries → the loop spins.
4. cria's completion check asks the reasoner "is this step done?" from the coder's **prose** —
   the exact verifier Codex Local **deleted** for false-negativing finished work. No probes,
   no file-changed check → the loop re-drives step 1 and, after 3 fails, silently accepts it.

## Architectural reframe (important)

Several "dropped" pieces look blocked by cria's *owns-no-executors* rule, but they are **not** —
cria already *sees the harness's tool calls and their results* in the inbound message stream.
So it can port them by **observing** the stream (like it already does for `.cria/` writes):
loop detection from observed tool-call history, completion gating from observed tool results /
file-changed signals, and INVESTIGATE by having the planner emit read-only tool calls the
harness runs. The probes don't have to run *in* cria — they run in the harness; cria reads the
output. Only literally executing commands is off-limits.

---

## Tier 1 — fix-on-sight (small, cria-internal, high-impact)

**Status (2026-07-07): the fidelity fixes below are DONE — #3-#10 (168 tests pass). #1 and #2
are NOT fidelity fixes — they are un-ported features (`local_coder_prompt.md` / `no_action_prompt.rs`
have no cria equivalent), so they are OUT OF SCOPE until porting is authorized.**

Each is a contained change to an existing module; most are "make a rejected tool call valid"
or "add a missing prompt line." These are the fastest path to unstalling the loop.

| # | Gap | cria ↔ Rust | Fix |
|---|-----|-------------|-----|
| ✅ | `shell_args` wrong field (`cmd` vs `command`) | `shelltool.py` ↔ `tool_aliases.rs` | DONE this session |
| 1 | **Local-coder system prompt not injected** (harness's bloated prompt passed through) | `toolmenu.py:37` ↔ `local_coder_prompt.md` + `local_routing.rs:1899` | On local coder turns, **replace** the system message with a ported concise local-coder prompt (not just append the cheat-sheet). Highest single lever. |
| 2 | **No no-action / continuation prompt** | absent ↔ `no_action_prompt.rs:23` | When a coder turn is prose-only with no tool call, inject the escalating "re-issue as a SINGLE tool call" prompt; set `tool_choice="required"` on retry. |
| 3 | **write_file literal-`\n` not repaired** before base64 → file = one line | `writeproxy.py:124-184` ↔ `tool_aliases.rs:426,545` | Apply the double-escape repair to `content` before encoding. |
| 4 | **Shell-alias table ~17 vs ~300** (python/pytest/cargo/npm/… as tool name → rejected) | `massage.py:24,92` ↔ `tool_aliases.rs:34-349` | Port the full alias list. |
| 5 | **`exec_command` array `cmd` not normalized** when advertised (`[` run as a program) | `massage.py:115` ↔ `local_routing.rs:378` + `tool_aliases.rs:721` | Run the exec-array→shell normalizer before the "name in names" pass-through. |
| 6 | **apply_patch bare-line prefix only in Add-File** (Update hunks with raw code rejected) | `massage.py:502-561` ↔ `tool_aliases.rs:1386` | Prefix bare content lines inside ANY hunk. |
| 7 | Classifier missing "you do NOT execute" framing (small model starts doing the task) | `classify.py:31` ↔ `classifier.rs:15` | Prepend the sentence. |
| 8 | Plan prompt drops "end with a run/build/test step" + "each builds on the last" | `planner.py:25` ↔ `reasoned_guidance.rs:57` | Add the two clauses. |
| 9 | Plan provenance caveat dropped from step framing | `loop.py:251` ↔ `reasoned_guidance.rs:70` | Add "this plan was made by a model, may be wrong" to `_item_prompt`. |
| 10 | No negative plan cache + no trivial-task gate → re-drafts every turn | `planner.py:69` ↔ `reasoned_guidance.rs:77,82` | Cache the None result; add a `MIN_TASK_CHARS` skip. |

## Tier 2 — structural, scoped (medium effort)

| # | Gap | cria ↔ Rust | Fix |
|---|-----|-------------|-----|
| 11 | **Loop detectors — all 5 absent** (no tool-call history; coder loops *within* a step) | absent ↔ `loop_detector.rs`, `rumination_detector.rs` | Track tool-call/arg history from the observed stream; fire on repetition / read-without-write / thrash. |
| 12 | **Converge-vs-repeat completion logic** replaced by flat 3-fail cap | `loop.py:34,145` ↔ `local_routing.rs:1019` | Advance on a *repeated* failure reason (stuck), keep going while reasons *change* (converging), high ceiling. |
| 13 | **Honest incompletion not surfaced** (accepted-unverified reported as "complete") | `loop.py:145,212` ↔ `local_routing.rs:1038` | Track accepted-unverified steps; write "⚠ stopping with UNRESOLVED issues" into the closing message. |
| 14 | **Runtime failover absent** (resolve-once; call failure = error, no retry/chain-walk) | `routing.py:59` ↔ `failover.rs` + `local_routing.rs:1504` | Port the F1-F8 taxonomy; walk the chain on failure; retry-same+backoff on rate-limit/timeout. |
| 15 | local_only chains get no local backup-append (collapse = dead turn) | `routing.py:73` ↔ `local_routing.rs:1484` | Append the standard local roles as deduped backups. |
| 16 | Classifier itself doesn't fail over; no `classification`/`compaction`/`planning` lanes | `classify.py:60`, `config.py:105` ↔ `local_routing.rs:1171`, `project_config.rs:184` | Add a classification chain; try each classifier endpoint before bias fallback. |
| 17 | **`content_reduce` absent** (oversized web/file tool output blows the small window) | absent ↔ `content_reduce.rs` | Port MIME-aware reduction; apply to oversized tool-role messages before forwarding. |
| 18 | Gemma dialect regex-only (drops non-string args, nesting, truncated calls) | `massage.py:30,301` ↔ `tool_aliases.rs:1922` | Port the recursive delimiter parser with truncation tolerance. |
| 19 | Rumination + quality (empty/echo/refusal) guards absent | absent ↔ `rumination_detector.rs`, `quality.rs` | Re-prompt bad turns before spending a verify call; abort spirals. |

## Tier 3 — architectural (the big lever: ground truth via the harness)

| # | Gap | cria ↔ Rust | Fix |
|---|-----|-------------|-----|
| 20 | **No ground truth anywhere** — completion judged on prose (the *deleted* anti-pattern) | `loop.py:171` ↔ `no_action_prompt.rs:9`, `reasoned_guidance.rs:575`, probes | Gate step completion on **observed** file-changed + a lint/test tool call the harness runs; feed probe output (with the "did-not-run ≠ passed" rule) to the reasoner, not prose. |
| 21 | **INVESTIGATE-then-PLAN gather loop dropped** (cria plans blind; prompt even forbids tools) | `planner.py:88` ↔ `reasoned_guidance.rs:142` | Give the planner a bounded read-only gather loop via harness tool calls before drafting. |
| 22 | Loop→ground-truth→reasoned-guidance (documented primary stuck-loop response) | absent ↔ `reasoned_guidance.rs`, `ground_truth.rs` | After a detected loop, re-read touched files + the repeated failing action + a probe → reasoner authors the next step. |

## Ported faithfully — do NOT touch

The port got these right (verified at parity): the whole Massages pipeline shape;
JSON extraction (`jsontext.py` ≥ `classifier.rs:265`); weighted cloud pick; two-layer
local_only cloud blocking; the write_file↔shell base64 round-trip; the streaming/heartbeat
transport; the Responses adapter. The verifier's non-blocking fallback on an unparseable
reasoner also correctly mirrors the Rust critic.

## Recommended order

Tier 1 #1 + #2 (local-coder prompt + no-action escalation) and #3-#6 (lowering rejections)
are the fastest unstall — they directly stop the "narrate / rejected-call / retry" spin. Then
Tier 3 #20 (ground-truth completion) is the biggest correctness lever. Tier 2 loop detectors
(#11) and failover (#14) harden it. Most of Tier 1 is an afternoon; Tier 3 #20-21 is the real
project (porting the probe-via-harness model), but it is what makes weak models actually finish.
</content>
