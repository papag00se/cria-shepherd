# November 6 L5-only red reruns

Campaign: `red-20261106-l5`. Scope: exactly the17 operator-selected red L5 cells, planner OFF, suite sandbox, deployed source `f132382e`. Completed November6 at about21:51Pacific. No assist behavior was changed during the campaign.

## Final independent usefulness judgments

All17 selected cells have archived final-source usefulness judgments. All ended through requirement-pace review rather than verified whole-task completion. Percentages assess reusable delivered work, not passed-check ratios or a claim of task completion.

- `qwen3.8_9b_distill`: Python75%, Java45%.
- `k2_horizon_7b`: Ruby45%, Python75%, Java0%, Rust95%.
- `phi4`: Ruby3%, Go0%, Python5%, Java25%, Node15%, Rust25%.
- `ling3.0_tiny`: Ruby15%, Go20%, Python75%, Java30%, Node30%.

The Rust implementation is substantially complete but remains under a nested project directory, so the requested root Cargo invocation fails. The75% Python deliveries retain substantial integrated work but leave migration or functioning HTTP integration tests unfinished. Low scores describe delivered artifacts, not an explanation of why cria failed to redirect the run.

Authoritative rows: `suite/results/results.jsonl`; operator report regenerated only with `python suite/battery_status.py --write`. Final reasons and evidence are recorded by `suite/usefulness.py`. Milestones are separate interim judgments, not final scores.

## Confirmed assist observations and investigation leads

Detailed capture paths and contemporaneous observations are retained in `~/.cria/suite/_campaigns/red-20261106-l5/assist-observations.md`.

- **Missing current evidence in focused review:** phi4/Go session `20261106T170103-01a1b385-f832-7d41-b518-1c13e2bc2393`, capture `0024-satisfaction`. Fully inspected prompt/reply/reasoning. Prompt preserves original task but provides zero readable work files and explicitly makes current source unavailable. Reply uses an unverified handoff's test-success claim as evidence. Diagnosis is withheld. This establishes firing and restraint, not effective corrective guidance or outcome benefit.
- **False scheduled approval:** phi4/Node session `20261106T173233-01a1b3a2-cef0-7582-b6ee-e951d6b6b21f`, capture `0030-satisfaction`. Fully inspected prompt and reply; no separate reasoning returned. Prompt includes original tests/Dockerfile requirements and paired current source requiring node-fetch, alongside an explicitly unverified completion handoff. Reply approves and explicitly excludes tests/Dockerfile from original requirements. Event sequence logs `loop.confirm_unchecked` with `workspace not surveyed`, then `confirmed:true` and `status:approved`. Later survey/replanning occurs and the run continues: this does not establish that every final completion brake was bypassed.
- **Evidence pollution:** captured tool results contain extensive unrelated mise tool-version/GitHub rate-limit warnings and truncation. These are environmental noise in review evidence, not requested implementation work.

These are concrete upstream investigation leads. The campaign does not establish that a useful grounded steer improved these coding outcomes, and firing or withholding is not counted as demonstrated usefulness. No causal rate or prevalence estimate is inferred.

## Operations and recovery

An earlier mistaken all-level expansion was corrected before this supervision. Six accidental L0 runs were stopped and were neither resumed nor scored here.

Disk exhaustion interrupted L5 cells and stopped the driver. Interrupted/harness-error attempts were not assigned final usefulness scores. After the operator resolved disk capacity and authorized continuation, the selected-only driver restarted at20:28Pacific and reran remaining interrupted cells. Earlier, two disposable cached installer archives were removed to unblock snapshot allocation; no run evidence or installed software was deleted.

Both cards were filled when compatible selected work was available. Attempts to colocate a second model sometimes exceeded GPU memory; no unselected work was launched to fill those slots. After the last cell ended, the driver exited and restored its saved hardware/service state. The supervising heartbeat `ac24b5de` was deleted after verifying all17 final judgments.
