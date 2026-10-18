"""Typed effects at memory boundaries, not a context bag or wire executor.

Selection is resolved by the caller before entering a policy. Foundations (floor,
usage, protocol repair and sent-body provenance) are deliberately not selectable
through these contracts. No module here performs I/O or owns workspace evidence.
"""
from dataclasses import dataclass
from enum import Enum


class Effect(Enum):
    NO_OP = "no-op"
    WITHHELD = "withheld"
    REDUCED = "reduced"
    PENDING = "pending"
    DELIVERED = "delivered"
    SETTLED = "settled"


@dataclass(frozen=True)
class MessageEffect:
    messages: list[dict]
    effect: Effect = Effect.NO_OP
    count: int = 0

    def __post_init__(self):
        if not isinstance(self.effect, Effect) or self.count < 0:
            raise ValueError("Invalid memory effect")
        if self.effect is Effect.NO_OP and self.count:
            raise ValueError("No-op cannot report changed items")
