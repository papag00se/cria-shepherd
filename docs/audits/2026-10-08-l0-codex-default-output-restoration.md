# Restore pinned Codex's default output policy, not a new L0 assist

The capability catalog added in35cf333c declared `truncation_policy={tokens,limit:context}`. CPU-only tests of the exact pinned Codex0.159.3 binary establish this unintentionally widened its unknown-local-model default. The same dense command produces approximately10KB of model-facing tool-result text without a catalog,40KB with the old catalog,10KB with `bytes/10000`, and40KB with `tokens/10000`. Artifacts: `~/.cria/validation/l0-ornith-feed-rerun-1-failure/output-policy-probe/`.

The operator explicitly requests restoring the pinned default and resuming the planner-off campaign. Both primary read-only reviewers converged on restoring `bytes/10000`, not changing the85% compaction trigger or installing a new reserve. No server-side clipping, context floor, semantic assist, task-code fix, native-window change or sampling change is part of this restoration. Codex itself retains its own truncation and marker; cria forwards that result unchanged. The source/catalog boundary is disclosed; earlier results are retained with their original policy/provenance, never silently rejudged or replaced.

## Grounded incident

Native and Codex-recorded usage match for the examined transition. The new tool output is estimated locally by Codex before another native measurement, so accurate preceding usage does not guarantee the next request fits. Rerun0031 received native40060964>49152;0032 was prepared but not transmitted because `upstream.refit_no_change` suppressed the identical body. Original attempt0244 reached48935prompt+217output=49152, producing an incomplete historical call that later poisoned compaction. The historical envelope fixes the rendering failure but not the oversized-output cause.

## Validation and limits

- Real pinned harness/fake backend, sandboxed and isolated: both recorded incident baselines fail with the old catalog against an adverse dense-output tokenizer, and pass with the restored default. The entire client tool message equals the forwarded message; default/no-catalog output bodies match. No floor/planner/loop/reconnect or overflow-assisted deletion is admitted as a pass.
- Native **CPU-only** `/apply-template` plus `/tokenize`, with no generation: the unchanged original requests reproduce60964 and48935tokens. Replacing only the final tool message with the pinned default-policy dense fixture yields35290 and23812tokens respectively, both within49152. These are fixture substitutions, not historical artifacts or proof of a successful coding run. Full requests/templates/token arrays are retained under `native-default-capacity/`.
- The lossless historical malformed-JSON envelope renders successfully; the separately probed non-object array argument also renders on current Ornith. This is not universal backend/schema certification.
- The row event census now discloses exact `upstream.history_args_enveloped` events and original argument counts under `wire_translations`, separate from coding assists. The ladder comments distinguish model-visible lossless historical rendering from L1 executable-argument recovery. Old rows remain immutable.
- The argument codec repair was separately removed in6ab61477: valid/malformed argument strings now remain exact; structured falsey values are not invented empty objects.

This repair is bounded to the proven default-regression and measured bursts. Parallel/explicitly oversized outputs, near-window histories, large user messages and compaction overflow are not universally solved. Freeform incomplete-envelope conversion and other existing wire-fidelity concerns remain disclosed rather than repaired by guesses. No blanket invisibility or byte-identity claim is made.

The existing catalog sends explicit reasoning effort`none`, unlike the no-catalog probe. This is unchanged here; it must not be called absence of a reasoning request. Prior judgments under the widened output policy remain preserved and separately identified. Sandbox read visibility of older archives remains a contamination risk to inspect during judgment, not evidence that reuse occurred.
