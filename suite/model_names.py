"""Official project model identities (operator, 2026-09-30).

Names identify logical models, not quantizations, service units or historical run IDs.
Normalize at presentation/lookup boundaries; never rewrite archived evidence or an active
campaign's executable keys. See docs/model-names.md and AGENTS.md.
"""

OFFICIAL_NAMES = (
    "gemma4_12b", "ornith1.5_9b", "ling3.0_tiny", "bonsai2",
    "k2_horizon_7b", "phi4", "qwen3.8_9b_distill",
)

# Explicit compatibility names only: do not guess model identity from punctuation or size.
ALIASES = {
    "gemma4": "gemma4_12b",
    "gemma4-qat": "gemma4_12b",
    "ornith15": "ornith1.5_9b",
    "ornith1.5": "ornith1.5_9b",
    "ling3-tiny": "ling3.0_tiny",
    "ternary-bonsai-2": "bonsai2",
    "k2-horizon": "k2_horizon_7b",
    "qwen38-distill": "qwen3.8_9b_distill",
    "defiant-fable": "qwen3.8_9b_distill",
}


def canonical_name(name: str) -> str:
    """Keep unspecified models intact; an alias must never manufacture another row."""
    return ALIASES.get(name, name)
