# Rust L5 — candidate selection and recovered evidence review

## Decision

**No new deterministic owner is safe.** The file-versus-directory collision already has the one deterministic source owner, and its fact reaches the existing recovery architecture. A second deterministic recovery would either repeat that owner’s delivered directive or choose a destructive filesystem operation. Neither is admissible.

**Recovered-evidence correction, 2026-10-05:** CALL 0025 → CALL 0026 does not demonstrate an answer/verdict delivery defect. The author's reasoning considers repairs, but ultimately calls the activity progress and chooses `ON_TRACK`; recovery preserves that conclusion. The earlier inference that a rescue was suppressed contradicts the complete reasoning. Cria's unresolved failure here is the author's judgment about progress and its confused reading of the file/directory facts.

## Captured evidence

- **CALL 0015** (`chunk04.txt`): `write_file(path="src")` creates the regular file `src` although the content is headed `# src/main.rs`.
- **CALL 0016** (`chunk05.txt`): the result is `Wrote src`; the fresh workspace envelope then lists `src (1720 B)`. The same call writes regular file `tests` with `# Directory created for tests`.
- **CALL 0018** (`chunk07.txt`): `write_file(tests/nested_key_test.rs)` receives the typed parent-file refusal and a rejected-candidate label; its bytes are explicitly not disk state.
- **CALL 0024** (`chunk13.txt`): after the current inventory, prior refusal, and check evidence, the coder repeats `read_file(tests)`; the capture marks it as the third identical call.
- **CALL 0025** (`chunk14.txt`): the stuck judge receives the rejected child write, an explicit `FILE src` / `FILE tests` inventory, the missing child, and the Cargo target failure. Its reasoning repeatedly confuses the blocking file with a directory. It considers a binary target and test repairs, then concludes that creating files, attempting tests, and running failed checks constitute progress. Its final choice and emitted answer both say `ON_TRACK`.
- **CALL 0026** (`chunk14.txt`): the dedicated answer-recovery asks what that reasoning concluded. Its own reasoning reads the author's conclusion as progress, and its emitted `ON_TRACK` agrees. Neither call contains a final stuck ruling lost on delivery.
- **CALL 0070 / 0071 / 0081** (`chunk56.txt`, `chunk57.txt`, `chunk67.txt`) retain parent-file refusals and historical Cargo failures in proxy-input prompts. They also contain survey **command source**. The recovered text does not provide a survey block accepted by `wsview.strip_survey`; the script's `EMIT("F…")` statements must not be counted as emitted file records. This review does not re-establish final disk topology from those statements.

The decisive author packet already supplies the obstruction and checker evidence. The author does not use them to reach the needed judgment, and its recovery faithfully carries that judgment forward. This is an upstream judgment problem, not proof of a discarded directive. There is no demonstrated fact gap for another deterministic collision detector to fill.

## Existing owners and non-duplication check

1. **Parent-collision fact owner — `cria/writeproxy.py:_WRITE_PY` / `cria/prompts/write_parent_is_file.txt`.** Before `mkdir`, `_WRITE_PY` finds the nearest existing parent and, when it is not a directory, emits the `denial.mark(...)`-marked exact path and parent type. The prompt already says that nothing was written, to inspect the blocker, then move or delete it and re-send the child write. This is the authoritative, harness-executed fact source.
2. **Inbound write-failure owner — `cria/writeproxy.py:represent_inbound`.** It strips the lowered shell envelope, preserves the denied result, labels rejected payloads as never written, and deliberately delegates only `⟦ctx:editfail⟧` reports to `cria/editrecovery.py:recover`. The latter explicitly leaves write refusals and real errors unchanged. Extending it with another parent-file message duplicates owner 1 and conflates edit-text recovery with filesystem topology.
3. **Typed missing-file remediation owner — `cria/loop.py:_arm_completion_remediation`, `_settle_completion_remediation`, and `_frame_for_item`; prompt `cria/prompts/completion_remediation.txt`.** It owns a verified task-named absent file and releases only after an observed successful write to that exact subject. A collision is not that condition: the needed child cannot be written until an ancestor changes type, so routing it here would falsely treat a child-path write as the repair criterion.
4. **Stuck/reasoned redirect owner — `cria/loop.py`’s reasoned-steer path.** The action log labels denied calls structurally through `cria/denial.py:is_denied`; CALL 0025 proves this owner already received the collision, file inventory, and check evidence. CALL 0026 reads the complete author reasoning and preserves its progress conclusion. Current source still routes an absent action through `_steer_from_reasoning`; there is no missing recovery invocation in this pair.

A deterministic owner cannot safely select `delete`, `move`, or `rename`: those are destructive alternatives whose correctness depends on the file’s intended role and contents. Repeating “inspect, then move or delete” is already the exact source-owned prompt and adds no new fact or capability. Blocking more child writes or validation merely reproduces the existing refusal/gate loop and violates the additive, regression-only constraint.

## Provenance and source validation — 2026-10-05

The native capture directory and standalone chunks are absent. Authentic original `read` tool results survive in the retained Pi journals for this repository. The complete `chunk14.txt` tool result is identical in independent reads, including records `73d72b59` and `e8462f9e` in journal `2026-09-24T05-09-08-426Z_01a0d1d1-46ca-747d-a637-fbefd0c498e4.jsonl`. Its UTF-8 SHA-256 is `b9131197751093658196dc210e7a737d6ac7b859d8c5cfaa0277b8feb1f83c01`. Complete `chunk04` and contiguous reads of `chunk56`, `chunk57`, and `chunk67` also survive. The latter are recovered by documented source-line offsets; their final-newline identity cannot be checked against a native-file hash. Raw packets remain private.

A source replay transcribed only the author's observed content, complete thinking, and `stop` finish, and returned the recovery's observed answer through a fake transport. The current recovery system prompt matches the captured system prompt, retains the whole original thinking, and returns no directive after the authentic `ON_TRACK` confirmation. This validates response delivery only. It does not replay a model judgment or establish task usefulness.

## Remaining research

Investigate why the existing author treats blocked activity as progress despite the file inventory and refusals. A future change needs a grounded judgment comparison, including actual progress controls; this pair supplies no fails-before response-delivery defect to repair. Do not force a directive, reinterpret private prose deterministically, select move/delete/rename, or add another parent-file fact owner.

No loop or prompt behavior changed. Existing focused response-recovery, structural-refusal, action-contract, and diagnostic-grounding tests passed. No model request, task execution, live run, deployment, or service/model swap was performed.
