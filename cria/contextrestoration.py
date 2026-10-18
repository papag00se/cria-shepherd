"""Missing current-file text policy; workspace observations and wire credit are foundations.

The driver supplies lazy transcript facts from its existing authoritative ledger/read
parsers. It must not infer successful reads from sent calls or refused results.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Callable, Mapping, Protocol

from . import bodykeys, filecommands, groundtruth, modelview, prompts
from .assistcontract import Policy, Reference


class Workspace(Protocol):
    surveyed: bool
    may_have_changed: bool
    def isfile(self, path: str) -> bool | None: ...
    def request_current_body(self, path: str) -> None: ...
    def read_bytes(self, path: str) -> bytes | None: ...
    def files(self) -> list: ...
    def rel(self, path: str) -> str | None: ...


@dataclass(frozen=True)
class FileHistory:
    ledger_paths: tuple[str, ...]
    written_paths: tuple[str, ...]
    whole_reads: tuple[str, ...]
    whole_writes: tuple[str, ...]
    key: Callable[[str], str]
    touch: Mapping[str, int]


@dataclass(frozen=True)
class RestoreInput:
    workspace: Callable[[], Workspace | None]
    history: Callable[[], FileHistory]


@dataclass(frozen=True)
class RestoreResult:
    message: dict | None
    offered: dict[str, str]
    named: tuple[str, ...] = ()


def restore(source: RestoreInput, *, enabled: bool = True) -> RestoreResult:
    if not enabled:
        return RestoreResult(None, {})
    view = source.workspace()
    if view is None or not view.surveyed:
        return RestoreResult(None, {})
    facts = source.history()
    candidates = {facts.key(p) for p in facts.ledger_paths + facts.written_paths}
    candidates -= {facts.key(p) for p in facts.whole_reads + facts.whole_writes}
    text, offered, named = render(view, sorted(candidates), facts.touch)
    if not offered and not text:
        return RestoreResult(None, {})
    return RestoreResult({"role": "user", "content": text,
                          bodykeys.RESTORED_FILES: modelview.restored_hint(text, offered, sorted(named))},
                         offered, tuple(named))


def render(view: Workspace, rels: list[str], touch: Mapping[str, int]) -> tuple[str, dict, list[str]]:
    """Whole literal bodies only; unavailable and over-budget files are named."""
    if not rels:
        return "", {}, []
    todo = [r for r in rels if not r.startswith(groundtruth._SPILL_REL) and view.isfile(r) is True]
    if not todo:
        return "", {}, []
    unavailable: list[str] = []
    if view.may_have_changed:
        for rel in todo:
            view.request_current_body(rel)
        unavailable, todo = list(todo), []
    mtime = {view.rel(e.path): (e.mtime or 0) for e in (view.files() or [])}
    todo.sort(key=lambda r: (-touch.get(r, 0), -(mtime.get(r) or 0), r))
    limit = filecommands.READ_INLINE_MAX
    labels = prompts.load_map("fetched_facts_sections")
    shown, omitted, omitted_rels, taken, restored = [], [], [], 0, {}
    for rel in todo:
        raw = view.read_bytes(rel)
        if raw is None:
            unavailable.append(rel)
            continue
        text = raw.decode("utf-8", "replace")
        if groundtruth.content_reduce_mod.looks_binary(text):
            continue
        if len(raw) > limit or taken + len(raw) > limit:
            omitted.append(f"{rel} ({len(raw)} bytes)")
            omitted_rels.append(rel)
            continue
        taken += len(raw)
        shown.append(prompts.fill(labels["restore_file"], path=rel, body=text))
        restored[rel] = hashlib.sha1(raw).hexdigest()
    if not shown and not omitted and not unavailable:
        return "", {}, []
    parts = [labels["restore_header" if shown else "restore_header_bare"].rstrip()] + shown
    if omitted:
        parts.append(prompts.fill(labels["restore_omitted"], paths=", ".join(omitted), limit=limit))
    if unavailable:
        parts.append(prompts.fill(labels["restore_unavailable"], paths=", ".join(unavailable)))
    return "\n".join(parts), restored, list(restored) + omitted_rels + unavailable


@dataclass
class ReadCredit:
    """Per session, per coder call; replace even on a failed/empty delivery."""
    current: dict[str, str] = field(default_factory=dict)

    def begin(self) -> None:
        """Before calling the coder, including when that call later raises."""
        self.current = {}

    def settle(self, delivered: Mapping[str, str]) -> None:
        self.current = dict(delivered)


def settle_wire(source: modelview.DeliveryInput) -> modelview.DeliveryResult:
    """Always-run last-wire foundation, including when the producer is disabled."""
    return modelview.settle_delivery(source)


@dataclass(frozen=True)
class Definition:
    policy: Policy
    execute: Callable[..., RestoreResult]


DEFINITION = Definition(Policy(
    "restore-current-file-text", "coder-context-restoration", 4, family_id="F72",
    prompts=("fetched_facts_sections",), state="ReadCredit per session/coder call; shared ledger unchanged",
    services=("workspace-view", "landed-file-history", "final-wire-delivery"),
    hooks=(Reference("cria/loop.py", "Loop._prepare_coder_context"),
           Reference("cria/loop.py", "_restored_text_message"),
           Reference("cria/loop.py", "Loop._work_item"),
           Reference("cria/loop.py", "Loop._drive_single_item"),
           Reference("cria/modelview.py", "settle_restored_text"),
           Reference("cria/loop.py", "Loop._coder_turn")),
    regressions=(Reference("tests/test_context_restoration_policy.py", "test_render_source_parity"),
                 Reference("tests/test_common_context_preparation.py", "test_absent_context_selection_never_runs_optional_leaf_detection"),
                 Reference("tests/test_common_context_preparation.py", "test_actual_driver_floor_delivery_earns_only_surviving_restoration_credit")),
    migrated=False), restore)
