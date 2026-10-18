"""Structural service interfaces only; no shrink policy, defaults or concrete state."""
from typing import Callable, Collection, Protocol


class EventLog(Protocol):
    def emit(self, kind: str, **fields) -> None: ...


class ShrinkState(Protocol):
    approved: dict[tuple[str, str], str]


class ShrinkSession(Protocol):
    first_survey_files: Collection[str] | None
    state: ShrinkState


class ShrinkView(Protocol):
    surveyed: bool
    def rel(self, path: str) -> str | None: ...
    def isfile(self, path: str) -> bool | None: ...
    def read_bytes(self, path: str) -> bytes | None: ...


class ShrinkServices(Protocol):
    session: Callable[[], ShrinkSession | None]
    view: Callable[[], ShrinkView]
    ask: Callable[..., str] | None
    log: EventLog
