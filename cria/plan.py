"""The plan artifact — `./.cria/<id>.md`, the structured-markdown file the phase-6
loop drives through, one item at a time.

cria never writes this file itself — it owns no executors. It produces the
*content* (`to_markdown`) and parses content the harness reads back
(`from_markdown`); the phase-6 loop does the actual create/read via the harness's
own file tools, in the harness's workspace.

Format (readable by a human, parseable without a library):

    ---
    id: 20260707T004512-3f9a1c2b
    created: 2026-07-07T00:45:12+00:00
    status: in_progress
    task: Write a Python Lambda handler that resolves an Ada Handle...
    ---

    # Plan

    - [ ] Confirm the api.handle.me response shape
    - [x] Write lambda_handler.py using urllib
      > wrote handler.py; resolves via /handles/{handle}

A small `key: value` frontmatter (no YAML dep) + a GitHub task list. Each `- [ ]`
/ `- [x]` is a step; an indented `> …` line under it is the note phase 6 records
about what was done.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_ITEM = re.compile(r"^\s*-\s*\[([ xX])\]\s*(.*)$")
_NOTE = re.compile(r"^\s+>\s?(.*)$")


@dataclass
class PlanItem:
    text: str
    done: bool = False
    note: str | None = None  # a clean status — only ever "verified" (a step advances ONLY on a pass)
    # NB: there is deliberately no `pinned` flag. A step cria held out of the living re-derivation was an
    # inescapable mandate, and the only step it ever protected was one cria authored itself — planning
    # cria has no business doing. Every step is re-derivable from the real work.


@dataclass
class Plan:
    id: str
    task: str
    created: str
    status: str = "in_progress"  # in_progress | done
    items: list[PlanItem] = field(default_factory=list)

    def current(self) -> PlanItem | None:
        """The first not-yet-done step — the one to hand the coder next."""
        return next((it for it in self.items if not it.done), None)

    def remaining(self) -> int:
        return sum(1 for it in self.items if not it.done)

    def to_markdown(self) -> str:
        head = [
            "---",
            f"id: {self.id}",
            f"created: {self.created}",
            f"status: {self.status}",
            f"task: {_oneline(self.task)}",
            "---",
            "",
            "# Plan",
            "",
        ]
        body: list[str] = []
        for it in self.items:
            body.append(f"- [{'x' if it.done else ' '}] {it.text}")
            if it.note:
                for line in it.note.splitlines() or [""]:
                    body.append(f"  > {line}")
        return "\n".join(head + body) + "\n"

    @classmethod
    def from_markdown(cls, text: str) -> "Plan":
        meta, body = _split_frontmatter(text)
        items: list[PlanItem] = []
        for line in body.splitlines():
            m = _ITEM.match(line)
            if m:
                items.append(PlanItem(text=m.group(2).strip(), done=m.group(1).lower() == "x"))
                continue
            n = _NOTE.match(line)
            if n and items:
                prev = items[-1]
                prev.note = f"{prev.note}\n{n.group(1)}" if prev.note else n.group(1)
        return cls(
            id=meta.get("id", ""),
            task=meta.get("task", ""),
            created=meta.get("created", ""),
            status=meta.get("status", "in_progress"),
            items=items,
        )


def _oneline(s: str, cap: int = 500) -> str:
    return " ".join(s.split())[:cap]


def _split_frontmatter(text: str) -> tuple[dict, str]:
    lines = text.splitlines()
    if not (lines and lines[0].strip() == "---"):
        return {}, text
    meta: dict[str, str] = {}
    i = 1
    while i < len(lines) and lines[i].strip() != "---":
        if ":" in lines[i]:
            k, v = lines[i].split(":", 1)
            meta[k.strip()] = v.strip()
        i += 1
    return meta, "\n".join(lines[i + 1 :])
