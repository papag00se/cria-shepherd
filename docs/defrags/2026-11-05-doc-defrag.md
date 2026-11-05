# Documentation defrag — 2026-11-05

## Scope and inventory

One wide pass over 104 tracked Markdown files, including the root README, `docs/`, suite task notes and technical references. Inventory captured paths, byte sizes and last Git modification dates; the in-progress `progress-correctness` dataset docs were excluded from edits because another agent owns them. Four independent read-only surveys examined overlap, code drift and gaps, historical records, and navigation/human experience. Their Paseo agent IDs are `43d27513`, `08519cb3`, `6e638307`, and `5eb6ba08`; findings were spot-checked before changes.

## Tier 1 — retirements

- [ ] **Deferred: `rust-l5-candidate.md`.** A one-off investigation records the existing owner of a file/directory collision and a correction to a suspected verdict-delivery defect. Keep until those decisions and their evidence are checked in full and placed in `decision-log.md`; do not delete on a heading-level review.
- [ ] **Deferred: `docs/goals/compaction-live-report.md`.** The pointer remains linked by `codex-context-window.md`; preserve its incident provenance and update the inbound link before retiring it.
- **Kept:** `docs/audits/` and `docs/media/` include historical evidence and generated provenance; do not treat their age alone as proof they are disposable. `docs/cell-loop-prompt.md` is a reusable operator prompt, not a completed task list.

No historical document was deleted in this pass. Deferral preserves decisions and incident evidence while their appropriate canonical homes are verified.

## Tier 2 — consolidate and navigate

- **Applied:** `docs/README.md` is the front door; short guides separate features, architecture and evaluation. Existing technical references remain canonical for detailed contracts rather than being copied into the guides.
- **Deferred:** `model-settings.md` mixes dated model configurations and current guidance; move historical material only after checking references and preserving version context in `model-history.md`.
- **Kept intentionally distinct:** `docs/testing.md` covers software tests; `suite/README.md` covers the coding-task evaluation suite. `battery-report.md` is generated standing output, while media snapshots preserve historical selections.

## Tier 3 — reconcile drift

- **Applied:** removed the stale current test-count claim from README and `testing.md`; dated historical measurements remain labelled as such.
- **Applied:** README identifies its L5 graphic as best retained historical selections across revisions and settings, including planner-on runs, not a controlled comparison.
- **Applied:** corrected `cria/config.py`'s module docstring: unknown configuration entries are rejected. No runtime behavior changed.
- **Protected file:** the live-model statement in `AGENTS.md` may be stale. Global instructions prohibit editing that file; the current service must be checked rather than substituting another historical label.

## Tier 4 — fill real gaps

- **Applied:** concise linked pages answer what cria does, how its harness/model boundary works, and how the task battery and usefulness judgment work. They distinguish controls, partial evidence and historical comparisons.
- **Applied:** a ChatGPT-generated editorial illustration provides a visual entry point; existing architecture and assist visuals remain in use.
- **Deferred:** detailed reference and historical pages are intentionally not rewritten into marketing copy. Their audience, scope and dates should be clear when each is next edited.

## Posture

The project already has unusually rich design doctrine, operational details, captured research and visual assets. The issue was finding a human-sized route through them—not a lack of technical material. The new guides are summaries and signposts, not replacements for source-owned contracts.
