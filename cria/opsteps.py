"""What a decision of the operation engine can be (cria/ops.py, cria/readops.py): issue the next steps, finish with the text the
model is told, or keep waiting for a result."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Issue:
    steps: tuple
    blobs: dict = field(default_factory=dict)       # text the steps refer to by hash, recorded once (a spill's whole text)


@dataclass(frozen=True)
class Final:
    outcome: str
    text: str
    extra: dict = field(default_factory=dict)      # facts the ledger keeps beside the text (a read's source, note and hold)


Wait = object()
