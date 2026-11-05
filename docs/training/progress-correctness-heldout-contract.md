# Progress correctness: independent held-out author contract

This is a **contract and interface**, not a test set. The independent held-out author owns family selection, authorship, executable checks and private payload. The builder must not build or read that payload and must not use it to choose training examples, prompts, thresholds or quality remedies. Do not open or reuse the consumed historical fresh TEST and its predictions. There is no held-out payload in this document or in `suite/progress_correctness/heldout_adapter.py`.

## Partition and independence

Choose and record actual TEST project/source/template families **before** writing their variants. Keep all requirements from a project and every sibling, translation, derivative and near-clone in that family's TEST split. Use a private `heldout-author/` family namespace and maintain the private family list. A namespace alone is not evidence of disjointness: compare project identity and high-level scope with the non-payload TRAIN/DEV family registry; resolve a collision by choosing a different project, not by moving a written case. The author receives this contract and the project-name registry, not TRAIN examples, implementation generators, defect recipes, predictions or review outcomes. Author independently in varied programming languages and domains. Nominal target: 200 requirement groups / 600 rows, subject to sound labels; paired siblings are not independent projects.

## What the classifier is asked

Use the existing `offline_onejev_progress` policy and `render_state` schema: `{requirement, workspace_changes}`. The classifier receives the full requirement and full seed-to-snapshot unified diff, not the seed tree as a separate attachment, verification output, intended labels, rationales, private reasoning or hidden project files. Only changes count as progress. `DONE` means the changed code fully delivers the requirement; `PARTIAL` means it delivers some requested work but a specified part remains missing or wrong; `NOT_STARTED` means no change implements any requested part. If meaning or sufficiency is uncertain, redesign or quarantine instead of silently relabeling. A partially working result with no clearly delivered requested clause needs particular care, not a new class definition.

For each group author an unmet seed and complete, meaningful partial and no-progress full snapshots. Mix unchanged seeds with substantive unrelated changes; distribute realistic unrelated changes among all three classes. Vary bug shapes and implementations without using stage-coded paths, comments, test names or prose. Include correct but unconventional implementations and meaningful partial work, not merely deletion of a line from every complete solution. A partial must pass checks for delivered behavior and demonstrably fail a named requested clause. Derive expected values from the requirement independently, not by running the proposed implementation. Passing authored checks is evidence, not an independent semantic review.

All code needed to judge a claim must be visible in the diff, or the requirement must be self-contained. Do not infer correctness from an unchanged hidden helper, nor treat performance, concurrency, live services or external behavior as proven without classifier-visible evidence. Every changed UTF-8 text file must be included, without clipping. The adapter includes complete context for changed files, deleted-file contents, and explicit missing-final-newline markers; this differs from the older `seed_diff` two-line context and its abbreviated deletion representation, deliberately preserving evidence. It cannot make an unchanged helper visible. Non-text/binary evidence is outside this adapter; redesign or quarantine rather than claim it was shown.

## Author-private JSON schema

Save a JSON object `{"groups": [...]}` under the author's private `~/.cria/` area. Each group contains:

- `family`: private family ID; `group`: unique stable requirement-group ID; `requirement`: exact request text.
- `seed_files`: object mapping workspace-relative paths to complete UTF-8 file contents.
- `snapshots`: object with keys `DONE`, `PARTIAL`, `NOT_STARTED`; each value is the **entire** workspace file mapping for that snapshot, including unchanged files and excluding deletions. Stage keys are author-side metadata, not paths or diff text.
- `rationale`: author-private explanation of the delivered and missing clauses.
- `checks`: array of `{name, argv, files, timeout_seconds}`. `argv` is an argument array, never a shell string; `files` maps extra independent verifier paths to complete UTF-8 contents and must not overwrite snapshot files. The verifier is separate from the visible workspace diff. `timeout_seconds` is optional, defaults to 10. Use a meaningful set of requirement-derived checks, with separately identifiable ordinary behavior and omission/defect checks. Do not name verifier files with a stage in the visible snapshot.

Do not place secrets, private reasoning, executable download/install commands or network calls in fixtures. Tests are trusted authored programs, **not a security sandbox**. Each check runs sequentially in a fresh disposable directory under `$TMPDIR` or `/var/tmp`, with its own temporary HOME/cache, offline Go/Cargo settings and a timeout. This isolation does not prevent arbitrary programs from using the network or accessing other host paths: the independent author must inspect commands and code and not author such operations. A missing toolchain or timeout is recorded as unknown, never success. Adapt checks to installed toolchains; do not install software globally or fabricate execution.

## Adapter and review handoff

The author, in their own isolated process, runs:

```sh
python -m suite.progress_correctness.heldout_adapter \
  --spec "$HOME/.cria/training/<author-private>/spec.json" \
  --out "$HOME/.cria/training/<author-private>/adapter-output"
```

This module imports the existing policy/state renderer but **does not import the TRAIN builder or case definitions**. `review-blind.jsonl` contains opaque randomized IDs, full policy, state, rendered state and label options. `private-evidence.jsonl` contains the mapping, intended label, snapshots, rationale, verifier programs and complete outcomes; raw stdout/stderr are also retained losslessly in base64. Only the blind file goes to blind reviewers. A nonzero verifier exit is not automatically an incorrect case: DONE, PARTIAL and NOT_STARTED have different expected observations, which the author and later independent reviewer must interpret. The adapter does not assign or certify semantic labels, choose projects, enforce quotas, silently discard cases, or turn a timeout into a pass.

Review each full blind input before unblinding. Independently derive probes from the requirement, then compare labels and outputs; classify disagreements and quarantine or redesign unsupported cases. Keep holdout payload and findings out of TRAIN/DEV selection and dataset-quality tuning; the isolated author and designated reviewer coordinate the final handoff separately. Do not rerun and reshuffle an already distributed packet during its review.
