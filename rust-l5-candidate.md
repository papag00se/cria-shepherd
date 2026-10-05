# Rust L5 — final candidate selection (read-only)

## Decision

**No new deterministic owner is safe.** The file-versus-directory collision already has the one deterministic source owner, and its fact reaches the existing recovery architecture. A second deterministic recovery would either repeat that owner’s delivered directive or choose a destructive filesystem operation. Neither is admissible.

## Replayed evidence

- **CALL 0015** (`chunk04.txt`): `write_file(path="src")` creates the regular file `src` although the content is headed `# src/main.rs`.
- **CALL 0016** (`chunk05.txt`): the result is `Wrote src`; the fresh workspace envelope then lists `src (1720 B)`. The same call writes regular file `tests` with `# Directory created for tests`.
- **CALL 0018** (`chunk07.txt`): `write_file(tests/nested_key_test.rs)` receives the typed parent-file refusal and a rejected-candidate label; its bytes are explicitly not disk state.
- **CALL 0024** (`chunk13.txt`): after the current inventory, prior refusal, and check evidence, the coder repeats `read_file(tests)`; the capture marks it as the third identical call.
- **CALL 0025** (`chunk14.txt`): the stuck judge receives the rejected child write, the current `src`/`tests` facts, and the Cargo target failure. Its private reasoning identifies the need to add a binary target / address the blocked tests, but emits `ON_TRACK`.
- **CALL 0026** (`chunk14.txt`): the dedicated answer-recovery asks whether that reasoning found the coder stuck and again emits `ON_TRACK`.
- Later captures preserve the same topology rather than expose a missing observation: **CALL 0070** (`chunk56.txt`) has the compacted parent-file refusals and `F` survey entries; **CALL 0071** (`chunk57.txt`) repeats the same facts while Cargo exits 101; **CALL 0081** (`chunk67.txt`) still has regular `src` after `tests` alone was removed, followed by repeated failed gates.

This is a capture-shaped chain: accepted whole-file writes create `src`/`tests`; a child write produces a verified parent-type refusal; the workspace survey and Cargo error independently confirm the consequence; the existing reasoned recovery sees those facts but suppresses its own rescue. There is no fact gap for another deterministic detector to fill.

## Existing owners and non-duplication check

1. **Parent-collision fact owner — `cria/writeproxy.py:_WRITE_PY` / `cria/prompts/write_parent_is_file.txt`.** Before `mkdir`, `_WRITE_PY` finds the nearest existing parent and, when it is not a directory, emits the `denial.mark(...)`-marked exact path and parent type. The prompt already says that nothing was written, to inspect the blocker, then move or delete it and re-send the child write. This is the authoritative, harness-executed fact source.
2. **Inbound write-failure owner — `cria/writeproxy.py:represent_inbound`.** It strips the lowered shell envelope, preserves the denied result, labels rejected payloads as never written, and deliberately delegates only `⟦ctx:editfail⟧` reports to `cria/editrecovery.py:recover`. The latter explicitly leaves write refusals and real errors unchanged. Extending it with another parent-file message duplicates owner 1 and conflates edit-text recovery with filesystem topology.
3. **Typed missing-file remediation owner — `cria/loop.py:_arm_completion_remediation`, `_settle_completion_remediation`, and `_frame_for_item`; prompt `cria/prompts/completion_remediation.txt`.** It owns a verified task-named absent file and releases only after an observed successful write to that exact subject. A collision is not that condition: the needed child cannot be written until an ancestor changes type, so routing it here would falsely treat a child-path write as the repair criterion.
4. **Stuck/reasoned redirect owner — `cria/loop.py`’s reasoned-steer path.** The action log labels denied calls structurally through `cria/denial.py:is_denied`; CALL 0025 proves this owner already received the collision, survey, and check evidence. CALL 0026 proves its answer-recovery also reached the same conclusion path.

A deterministic owner cannot safely select `delete`, `move`, or `rename`: those are destructive alternatives whose correctness depends on the file’s intended role and contents. Repeating “inspect, then move or delete” is already the exact source-owned prompt and adds no new fact or capability. Blocking more child writes or validation merely reproduces the existing refusal/gate loop and violates the additive, regression-only constraint.

## Next cell

Investigate the **existing reasoned stuck-response delivery** rather than add a collision heuristic: replay CALL 0025 → CALL 0026 with their exact action-log, survey, and check packet; establish why reasoning that identifies the blocked topology is serialized as `ON_TRACK`; then repair that upstream answer/verdict path and add a capture-shaped regression. The recovery must remain reasoned about the destructive choice, while the existing writeproxy parent-file owner continues to supply the ground truth.

No implementation was changed and no tests or live run were rerun.
