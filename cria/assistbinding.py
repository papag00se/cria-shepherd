"""Catalog-free request/task selection storage. UNBOUND is not a default selection."""
from contextlib import contextmanager
from contextvars import ContextVar
from enum import Enum
from typing import Protocol, TypeVar

from .assistcontract import ExecutableDefinition


class Selection(Protocol):
    @property
    def definitions(self) -> tuple[ExecutableDefinition, ...]: ...

    @property
    def engagement_level(self) -> int: ...


class _State(Enum):
    UNBOUND = 'unbound'


UNBOUND = _State.UNBOUND
_CURRENT: ContextVar[Selection | _State] = ContextVar('executable_assist_selection', default=UNBOUND)


def current() -> Selection | _State:
    """Return exactly the binding, or UNBOUND. Never assemble a catalog/default."""
    return _CURRENT.get()


_Definition = TypeVar('_Definition', bound=ExecutableDefinition)


def selected_definition(standalone: _Definition) -> _Definition | None:
    """Project an exact bound member without importing the catalog.

    Only an unbound library call uses its explicit standalone definition. Bound
    absence stays absent; this storage layer assembles no defaults or services.
    """
    selection = current()
    if selection is UNBOUND:
        return standalone
    matches = tuple(d for d in selection.definitions if d.policy.id == standalone.policy.id)
    if not matches:
        return None
    if len(matches) != 1 or not isinstance(matches[0], type(standalone)):
        raise TypeError('Selection requires one compatible definition: ' + standalone.policy.id)
    return matches[0]


def is_bound() -> bool:
    return current() is not UNBOUND


@contextmanager
def bound(selection: Selection):
    if selection is UNBOUND:
        raise ValueError('UNBOUND is absence, not an executable selection')
    token = _CURRENT.set(selection)
    try:
        yield selection
    finally:
        _CURRENT.reset(token)
