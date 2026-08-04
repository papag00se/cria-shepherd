# Audit lens — did the last 48 hours of changes footgun the regression campaign?

Seed symptom: six models passed campaign run 1 and cratered on run 2; gemma4 (temperature 0)
never passed at all despite a 4/4 ladder baseline. Three orthogonal lenses; two subagent searches,
synthesis and verification by hand; every acted-on finding reproduced against the real code or
captures before any fix.

## Lens 1 — environment/external (deterministic). CLEAN.

Per-model tok/s stable across passes; api.handle.me 403 bursts uncorrelated with failure (one run
ate 53 and scored 4/4); compaction/floor events patternless; sampling identical between ladder and
campaign eras. qwythos/ornith/qwopus flapping is genuine temp-0.6 variance. gemma4 is temp 0 —
its collapse could only come from changed inputs, which made lens 2 load-bearing.

## Lens 2 — model-facing surface delta (gemma4 4/4 baseline vs two 0/4s). FOOTGUN FOUND.

The 08-03 plan-off rewiring (68912bf + ef0b771) replaced the raw task — the active ask every turn
in the baseline — with a synthetic plan caged behind "Do ONLY this step (k of n), then stop",
hidden later steps, and living replans that split the user's task further. Both failing runs spent
all ~86–89 coder calls pinned on step 1; the README was structurally unreachable. Secondary
observed deltas: replans freezing an unclearable step-1 order; the step repair-note forbidding
whole-file rewrites to a model whose small edits chronically miss (adjacent to the run-2
`rm`-own-tests incident); the fetch-facts ledger sharing prompts with the known false camelCase
steer; and the baseline pass having been carried by ~18 code-dictating steers that the (younger)
dictated-code judge now drops — the pass was assisted, the fails were caged AND unassisted.

**Operator ruling (2026-08-04): the intent was ONLY a research step on both paths.** Fix landed:
`plan_off` sessions drive the reading step through the step machinery, then HAND BACK to the
raw-task single-item drive the moment the current item is the task (`loop.plan_off_handback`),
and the living re-derivation never runs on plan-off — the tail is the user's task, not a planner
guess. Tests: tests/test_plan_off_handback.py (framing test fails on pre-fix HEAD).

## Lens 3 — tonight's three campaign fixes (state-machine). ONE CRITICAL, TWO HIGH — all fixed.

1. **CRITICAL — `_veto_refuted_by_disk` overreach.** The regex+substring version overturned vetoes
   about content missing INSIDE existing files, absent functions, and a genuinely-missing `X.py`
   "covered" by `test_X.py`; one live misfire captured. Operator ruling: fuzzy-deterministic code
   is against principle — REBUILT as gather-then-ask: stat() gathers exact per-path facts, one
   reasoner call rules STANDS/REFUTED (prompt: confirm_veto_disk.txt), every failure direction
   keeps the veto.
2. **HIGH — completion probe misread.** The plan-ON backstop keyed off `done_probe`, which the
   plan-ON periodic satisfaction check also sets and strands; the backstop could read a stale or
   overwritten result. Fixed: the backstop has its own `completion_probe_id` and reads only the
   probe it issued.
3. **HIGH — compaction fail-open.** A harness compaction between the completion probe's emit and
   read erased the result and the backstop fail-opened. Fixed: `rewritten` now reaches `_work`;
   an erased result is re-issued (bounded by MAX_PROBE_REISSUES), parity with the other two probe
   readers.
4. **MEDIUM — verb-blind confirm skip.** The production-verb list missed "Update/Fix/Rewrite…".
   Operator ruling: same class as (1) — the verb list is GONE; a named file stays deterministic,
   the verbless case is one reasoner question (confirm_applies.txt), unreadable → the brake runs.
5. **MEDIUM — red-state blind spot.** `_confirm_applies`' red arm saw only the call-site findings;
   it now also takes the session's standing `last_gate_red`.
6. **LOW (fixed) —** red completion reopens are counted (`completion_gate_reds` in the gate emit);
   a DONE corrective step is never overwritten (append instead).
7. **LOW (deferred, rationale) —** TLD-shaped filenames (`main.io`) read as domains in the
   artifact scan. Fixing it inside `first_domain_in` risks the search-escape's real .io domains;
   the collision needs a TLD-extension file AND a verbless step AND a green repo. Revisit if a
   walk ever shows it.

## Campaign consequences

- gemma4's two 0/4 rows are superseded (causation proven at temperature 0); it reruns on the
  fixed routing.
- The other pass-2 failures (qwythos, qwopus, ornith, mellum2) were walked as model-attributable
  variance, but every plan-off row before this fix measured the caged routing; whether to void
  them and rerun is the operator's call, recorded in the regression report.

## Addendum — lens 4, evidence provenance (operator-directed, same day)

Seed: the dictated-code drop's evidence base. Finding: its harm was measured on a BLIND steer
author (empty truth slot 6/6 runs, fixed in the same commit ab51e59); the 08-01 dense ladder
passes ran with sighted dictation flowing (the regex drop was inert); the 08-02 reasoner judge
then suppressed the channel on the stale evidence. Systematic sweep found four more guards with
fouled provenance (full detail in the audit transcript): the flail-steer cap (one blind-era
fabliq run; bound dense campaign runs 11 times), the same-checks suppression (measured wholly on
the blind corpus), the roleplay first-person arm (two blind-era MoE incidents), and edit-recovery's
forced whole-file rewrite (weak-model rationale, no telemetry, window-fill deaths on both gemma4
0/4s). Checked-and-sound: spill gating, blames-service, repetition redirect, repeat-collapse note,
work-log labeling, truncation/rumination, URL/citation grounding.

Retunes landed (operator: "go"; trust ruling — the dense models' passing record under the old
conditions outranks guards built on fouled evidence):
- dictated-code drop → OBSERVE-ONLY (judge logs DICTATES, steer delivered);
- roleplay FIRST-PERSON arm → observe-only (transcript-syntax arms still drop);
- flail cap resets whenever the gate findings MOVE (silence still lands after 3 steers at an
  unmoving target);
- same-checks suppression grants ONE grounded second look per unchanged-findings streak;
- editrecovery whole-file escalation now emits (`editrecovery.escalated`) so its cost is countable.
Deferred pending re-measure: edit-recovery behavior itself; the noise-scrub's 27 pre-878ead2 dense
drops (one-time audit).
