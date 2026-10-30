"""Exact-form measurement lifecycle over shared message/workspace adapters.

Adapters interpret tool dialects; this owner decides which bytes remain evidence.
No filesystem access, global state, guessed paths, or content from pending calls.
"""
from dataclasses import dataclass
from typing import Callable, Protocol

from . import denial, filefacts


class WorkspaceBytes(Protocol):
    usable: bool
    may_have_changed: bool
    def read_bytes(self, path: str) -> bytes | None: ...
    def rel(self, path: str) -> str | None: ...


@dataclass(frozen=True)
class MeasurementServices:
    write_tools: frozenset[str]
    whole_write_tools: frozenset[str]
    edit_tools: frozenset[str]
    failed_ids: Callable[[list[dict]], set[str]]
    writes_something: Callable[[str, str], bool]
    command: Callable[[object], str]
    arguments: Callable[[object], dict]
    path: Callable[..., str | None]
    same_path: Callable[[str, str], bool]
    view: Callable[[], WorkspaceBytes | None]


def written_file_facts(messages: list[dict], services: MeasurementServices) -> list[filefacts.FileFact]:
    events = []
    pending = {}
    failed = services.failed_ids(messages)
    for idx, message in enumerate(messages or []):
        if not isinstance(message, dict):
            continue
        for call in message.get("tool_calls") or []:
            fn = call.get("function") or {}
            name, args = fn.get("name"), fn.get("arguments") or ""
            if call.get("id") and (name in services.write_tools or services.writes_something(name, services.command(args))):
                pending[call["id"]] = (name, args)
        tid = message.get("tool_call_id") or message.get("call_id")
        if tid in pending:
            result = message.get("content") if message.get("content") is not None else message.get("output")
            result = result if isinstance(result, str) else ""
            if tid in failed or denial.unlanded(message):
                continue
            if pending[tid][0] in services.write_tools and not denial.landed(message):
                continue          # a write/edit tool's bytes are a fact only when its own program said it landed
            name, args = pending[tid]
            whole = None
            if name in services.whole_write_tools and not denial.report(message).get("late"):
                # A write that ran before a same-file predecessor finished (its program's typed `late` report) may have been
                # replaced after it: its own bytes are not what the file holds, so it is a touch, never a whole-file fact.
                body = services.arguments(args).get("content")
                whole = body if isinstance(body, str) else None
            patch_ok = name not in services.whole_write_tools and name not in services.edit_tools
            events.append((idx, name, services.path(args, patch_ok=patch_ok), whole))
    paths = []
    for _, name, path, _ in events:
        if path and name in services.write_tools and not any(services.same_path(path, other) for other in paths):
            paths.append(path)
    view = services.view()
    use_view = view is not None and view.usable and not view.may_have_changed
    facts = []
    for path in paths:
        last = max((i for i, (_, _, p, whole) in enumerate(events)
                    if p and whole is not None and services.same_path(p, path)), default=None)
        if last is None:
            continue
        touched = any(name in services.write_tools and whole is None and (p is None or services.same_path(p, path))
                      or name not in services.write_tools for _, name, p, whole in events[last + 1:])
        if touched:
            continue
        if use_view:
            raw = view.read_bytes(path)
            if raw is not None:
                facts.append(filefacts.FileFact(view.rel(path) or path, raw, True))
                continue
        facts.append(filefacts.FileFact(path, events[last][3].encode("utf-8", "replace"), False))
    return facts
