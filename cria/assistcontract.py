"""Small, inert ownership metadata shared by executable stage definitions."""
from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass(frozen=True)
class Reference:
    """Inert repository-relative path/symbol; discovery, not execution evidence."""
    path: str
    symbol: str


@dataclass(frozen=True)
class Policy:
    id: str
    stage: str
    default_level: int
    family_id: str = ""
    prompts: tuple[str, ...] = ()
    state: str = "none"
    services: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    scope: str = "runtime"
    triggers: tuple[tuple[str, int], ...] = ()  # caller intent may require a higher rung
    hooks: tuple[Reference, ...] = ()
    regressions: tuple[Reference, ...] = ()
    migrated: bool = False  # a structural claim, never behavioral acceptance


class ExecutableDefinition(Protocol):
    """Registry surface only; each source owns its execute input/result types.

    Stage consumers call their concrete typed definitions, not a type-erased
    dispatcher with a universal evidence bag. Registration conveys order/identity.
    """
    policy: Policy
    execute: Callable[..., object]
