"""Shared planning data records, not executable stages, selection or planning state."""
from dataclasses import dataclass
from typing import Protocol


@dataclass
class PlanOutcome:
    """Per-``plan_for`` outcome, owned by the calling Loop session."""
    survey_pending: bool = False
    externalization_owner: object | None = None
    current_externalization_owner: object | None = None


@dataclass(frozen=True)
class ToolResult:
    """One gather tool call: its visible text, whether it taught the planner, and whether a
    workspace-file answer is still pending.

    ``learned`` is stated by the code that ran the tool — it knows whether the command printed
    anything, whether the file opened, whether the fetch answered — so the caller never has to
    re-derive it by reading the text. That distinction is load-bearing: measured (run 0727-090143),
    an empty workspace answered `ls -la` and `find` with nothing, the gather counted two calls as
    having researched, and the planner drafted from memory and invented an endpoint the coder then
    built. A refusal, an error, and a command that printed nothing are all calls that taught it
    nothing.

    ``pending`` is narrower: only a workspace ``read_file`` whose bytes have not reached the view
    yet sets it. Its result is neither a file answer nor a repeatable refusal; the next harness
    survey may carry the requested bytes. An empty or missing file is answered even though it may
    not have taught the planner anything."""
    text: str
    learned: bool
    pending: bool = False
    externalization: object | None = None
    externalization_owner: object | None = None
    externalization_stored: bool = False
    externalization_provenance: object | None = None


class EventLog(Protocol):
    def emit(self, event: str, **fields: object) -> None: ...
