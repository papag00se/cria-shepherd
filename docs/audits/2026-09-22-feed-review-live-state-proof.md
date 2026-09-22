# Feed `REVIEW.md` live-state proof — proposed before implementation

## Status and decision

**No implementation and no rerun follow from this document.** This is the one
acceptance proof that a candidate must satisfy before a behavior change can be
considered. It replaces the earlier terminal-artifact and pre-armed-replay
claims with a live-state transition. It has not been executed, so it is not
passes-after evidence and must not be presented as such.

The question is deliberately narrow:

> From a real, unarmed Feed session state in which the importer work and CSV
> dependency are already on disk but the task-named `REVIEW.md` is absent, can
> the ordinary live path obtain its own current absence evidence and emit a
> single `REVIEW.md` remediation before it frames the ordinary plan cursor?

This does **not** ask a deterministic transform to make the coder write a
file. It proves only the supervisor-owned transition from observable state to
an outgoing, task-scoped remediation. The harness's subsequent tool result is
the only proof that the file landed.

## Retained evidence and cohort

The fixture is restricted to retained terminal Feed captures. It does not read
a final workspace as a substitute for a historical view, use a fresh Feed run,
or mix in another task.

| role | retained capture | required captured material |
| --- | --- | --- |
| primary state and live judge loop | `20260921T164500-01a0c65b-cd75-7ab3-b3dd-3d839bfb3b35` (`1790034274`) | `0106`–`0109-satisfaction.{json,response.json}`, `0110`–`0111`, `0112-coder-s3.{json,response.json,reasoning.txt}` |
| independent terminal-state fixture | `20260921T110810-01a0c527-6c46-74b3-bf8d-91cb6d18d707` (`1790014067`) | its terminal coder body and the survey/tool turns immediately before it |
| independent terminal-state fixture | `20260921T131112-01a0c598-12c3-7973-8ebd-3f87b1ce0016` (`1790021450`) | its terminal coder body and the survey/tool turns immediately before it |
| independent terminal-state fixture | `20260921T144153-01a0c5eb-172a-7002-b4cf-64ac66d26edf` (`1790026888`) | its terminal coder body and the survey/tool turns immediately before it |

`1790034274` is the primary because its recorded satisfaction conversation
actually reaches a complete root listing and returns the typed, task-named
absence. Its on-disk evidence in the judge view contains `pom.xml` with
`commons-csv` and `src/main/java/pipeline/Importer.java`; the root listing
returned by `0107-satisfaction` omits `REVIEW.md`. `0109-satisfaction.response.json`
then returns `missing_file`, subject `REVIEW.md`, with
`workspace_absence` evidence. The next actual coder body, `0112-coder-s3.json`,
contains the original task, the importer/dependency state, and a remediation
for `REVIEW.md`; its reply recognizes the missing document but elects to
inspect rather than write it.

That last action is important negative evidence: delivery in this capture is
not a missing-delivery incident. It cannot be repurposed as proof that a
stronger serializer wording would cause a write.

The three corroborating captures establish that the fixture is not a
single-final-tree story. Each may participate only when its *pre-frame,
complete survey* records `pom.xml` and `src/main/java/pipeline/Importer.java`
and omits `REVIEW.md`. A capture whose survey is incomplete, whose artifact
bytes never arrived, or whose state does not establish those two landed
artifacts is excluded for that assertion rather than inferred from its final
score.

## Candidate boundary

The only candidate boundary is `Loop._work_item()` between the existing
periodic/step/satisfaction decisions and `_frame_for_item()`:

1. A complete current `wsview` survey is available for the harness workspace.
2. The session has no remediation subject, no pending verdict, and no injected
   `REVIEW.md` string beyond the ordinary original task/history.
3. The ordinary active plan item is about to be framed.
4. The candidate may ask the existing constrained completion/deliverable judge
   once. It must validate any returned claim through the existing typed
   provenance owner.
5. Only a validated `missing_file` for an exact task-named path may replace the
   cursor for that one outgoing coder body. The internal marker must be
   consumed at `Upstream._prep`; it must not reach the model.

This is a session-state boundary, not `_frame_for_item()` in isolation,
`_negative_diagnosis_nudge()` called with an already-made object, or a final
workspace scan. It has the necessary reach: the survey is harness-executed,
complete, and current; the reasoner judges its meaning; the wire is inspected
at the final serializer.

## The one transition

The eventual test is one parameterized live-state transition with the primary
capture as its required first case and the three corroborators as additional
cases. Every case starts at its recorded pre-frame body and reconstructs only
state that was available then.

### Initial state (common to both arms)

- Parse the selected terminal coder body to recover the original user task,
  plan cursor, tool menu, workspace root, and any real prior transcript. Do
  not replace the plan with `Add REVIEW.md.` and do not mark prior items done
  by hand.
- Build `wsview.View` exclusively by replaying the captured harness survey
  records that precede that frame. Require the survey's own `complete` flag
  and fingerprint. Do not synthesize a two-file listing and do not read the
  archived final workspace.
- Construct `PlanSession` from the recovered plan/session values with
  `completion_remediation_subject == ""`, `nudge_reason == ""`, no saved
  verdict, and the actual drive/gate values. This is the unarmed condition.
- Verify objective preconditions from the reconstructed survey, not source
  text: `pom.xml` is present; `src/main/java/pipeline/Importer.java` is
  present; `REVIEW.md` is absent; and the original task contains the exact
  `REVIEW.md` requirement.

The initial state intentionally proves **landed importer/dependency work plus
an absent required document**, not that all runtime requirements are complete.
The `1790034274` compiler and source evidence is retained as context, but it
is not promoted into an all-task-success predicate.

### Fails-before arm

Run the historical candidate boundary with its observation disabled only by
its *pre-change implementation* (not by a mock verdict, fabricated survey,
or a pre-set remediation field). Let `_work_item()` produce and serialize its
ordinary outgoing body.

The required failure is a wire fact:

- the final prepared body retains the ordinary active plan cursor; and
- it has no typed current-absence remediation that names `REVIEW.md` and the
  exact task quote.

This arm must not assert a particular coder tool call or final file state.
Those are model/harness events downstream of the boundary.

### Passes-after arm

Start again from a fresh copy of the identical unarmed state. Enable the
candidate boundary and let it make its normal live judge call against the
reconstructed complete survey. The test double may transport the captured
harness tool protocol, but it may **not** provide a verdict, patch
`observe_task_missing_file`, patch `judge_satisfaction`, construct a
`VerdictNudge`, or seed `completion_remediation_subject`.

The pass requires all of the following:

1. The judge is invoked only after the complete survey precondition.
2. Its returned data independently survives `_negative_diagnosis_nudge()` as
   `missing_file` / `REVIEW.md` / `workspace_absence`, with an exact contiguous
   task quote. An undecidable, malformed, stale, or unsupported answer is
   silent and fails this proof.
3. The ordinary active cursor is absent from the final serialized coder body.
4. The final serialized body contains the exact task requirement, the
   tool-voiced current-absence statement for `REVIEW.md`, and the bounded
   instruction to create that exact task-named file. It does not contain the
   internal body hint.
5. The session stays red/open as it was. Observation must not turn failed or
   unknown checks green, complete a step, or end the session.

A separate release test, not this proof, must demonstrate that remediation is
cleared only after the harness returns a successful write result for that exact
path. A proposed write, a read, an error, or a response that merely says it
wrote the file does not pass that release condition.

## Evidence an independent reviewer must retain

The test artifact must write a compact manifest containing, for each capture:

- SHA-256 and relative name of every consumed capture file;
- the recovered task quote, active cursor, drive/gate values, and complete
  survey fingerprint;
- the exact survey entries establishing `pom.xml` and `Importer.java` present
  and `REVIEW.md` absent;
- before/after serialized body SHA-256 plus the selected body messages (never
  a substring count); and
- the complete judge request, response, reasoning, tool calls/results, and
  provenance-validation result.

The reviewer must be able to start from that manifest, replay the harness
survey protocol, and inspect the final JSON body without access to a mutable
workspace or a terminal-score narrative. The primary capture's stored judge
request/response is a historical control and a schema/provenance oracle only;
it is not allowed to be injected into the pass arm.

## Rejected explanations and invalid evidence

The following are closed for this candidate:

- **Shared judge-to-coder delivery ceiling.** Rejected. `1790034274`'s valid
  `0109` diagnosis appears in the actual `0112` coder body; `1790024016` and
  `1790026888` also contain delivered typed gaps. A later non-write is not a
  dropped message.
- **Terminal absence proves a delivery defect.** Rejected. A final archive can
  establish that `REVIEW.md` is absent, but cannot show whether an earlier
  survey existed, what a judge concluded, or what was serialized next.
- **`_frame_for_item()`-only replay proves the live path.** Rejected. It has no
  session cadence, survey, judge, compaction boundary, or actual final outgoing
  request.
- **Pre-armed verdict/replay proves observation.** Rejected. Feeding a captured
  `VerdictNudge`, mocked `judge_satisfaction`, mocked
  `observe_task_missing_file`, or a session that already has a remediation
  subject proves only a serializer branch. It cannot prove the candidate can
  reach its subject (principle 11b).
- **Synthetic two-file survey proves current absence.** Rejected. It is not the
  captured workspace view and erases the complete-survey precondition.
- **Score or compiler success proves all Feed requirements.** Rejected. The
  desired invariant is document absence after importer/dependency artifacts
  land; no usefulness percentage, Maven exit, source comment, or coder summary
  converts that into complete runtime verification.
- **A forced `REVIEW.md` write proves the change.** Rejected. That would make
  cria author work and test an action decision rather than its own observable
  state-to-wire responsibility.

## Acceptance gate

Do not implement or keep a candidate from this theory until the one transition
above is accepted and passes unchanged for the primary capture and every
corroborator with a complete qualifying survey. A failure in any required
precondition is an abstention, not a reason to manufacture evidence or widen
the candidate. This document records no code change, replay, service restart,
or live Feed run.
