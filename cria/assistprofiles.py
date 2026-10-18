"""Explicit operator selections, not a second registry of assist implementations."""

RANKING_REVISION = "079116e4c99635722a0f3327246fd9e359586eb5"
RANK4_ABLATION = "rank4-ablation"
# Frozen Rank-4 selection from docs/audits/assist-principles-ranking.md,
# assessed at RANKING_REVISION. Later policy repairs do not change this experiment.
RANK4_DISABLED = (
    "text-call-recovery",
    "call-debris-repair",
    "malformed-argument-repair",
    "shell-tool-adaptation",
    "edit-patch-adaptation",
    "tool-free-text-recovery",
    "spill-path-correction",
    "malformed-shell-refusal",
    "workspace-boundary",
    "reference-file-protection",
    "fused-file-refusal",
    "shrinking-file-protection",
    "edit-failure-recovery",
    "environment-failure-advice",
    "empty-search-note",
    "filtered-failure-note",
    "missing-dependency-note",
    "dependency-source-note",
    "dependency-api-evidence",
    "search-repeat-admission",
    "fetch-repeat-admission",
    "search-spill-read-judgment",
    "task-classification",
    "focused-tool-menu",
    "tool-menu-instructions",
    "generation-runaway-guard",
    "rolling-transcript-memory",
    "focus-duplicate-pairs",
    "focus-soft-failure-history",
    "superseded-write-history",
    "wire-repeated-payloads",
    "history-rewrite-reorientation",
    "verified-harness-preamble",
    "experimental-step-preparation",
    "task-required-test-participation",
    "exact-file-form-approval",
    "approval-inspection-confirmation",
    "harness-memory-handoff",
    "outgoing-search-relevance",
    "grounded-stalled-work",
    "experimental-plan-gather",
    "experimental-plan-revision",
    "pasted-file-recovery",
    "experimental-living-plan",
    "experimental-completed-work-briefing",
    "automatic-protocol-discovery",
    "automatic-document-guidance",
    "research-spill-admission",
)


def resolve(profile: str, disabled: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(profile, str) or profile not in ("default", RANK4_ABLATION):
        raise ValueError("Unknown assist profile: " + repr(profile))
    if profile == RANK4_ABLATION:
        if disabled:
            raise ValueError("rank4-ablation is exact; additional opt-outs are not supported")
        return RANK4_DISABLED
    return disabled
