"""Select only source-owned tool-result lines for a historical evidence packet."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass

from . import bodykeys, callsyntax, compactionpacket, jsontext, prompts, resultnotes, selfcompact


@dataclass(frozen=True)
class Selection:
    source: compactionpacket.ToolEvidence
    lines: tuple[int, ...]

    def render(self) -> str:
        lines = self.source.result.splitlines(keepends=True)
        pieces = []
        previous = 0
        for n in self.lines:
            if n > previous + 1:
                pieces.append(prompts.load("history_selection_gap") + "\n")
            pieces.append(lines[n - 1])
            previous = n
        if previous < len(lines):
            if pieces and not pieces[-1].endswith(("\n", "\r")):
                pieces.append("\n")
            pieces.append(prompts.load("history_selection_gap") + "\n")
        return prompts.render("history_selection_rendered", id=self.source.call_id,
                              call=f"{self.source.name}({self.source.arguments})", result="".join(pieces))


def validate(sources: tuple[compactionpacket.ToolEvidence, ...], answer: object) -> tuple[Selection, ...]:
    """Accept only unique known IDs and exact source line coordinates; no generated prose rides."""
    if not isinstance(answer, dict):
        return ()
    counts = Counter(source.call_id for source in sources)
    selected = []
    for source in sources:
        numbers = answer.get(source.call_id)
        lines = source.result.splitlines(keepends=True)
        if (counts[source.call_id] != 1 or not isinstance(numbers, list) or not numbers
                or any(type(n) is not int or n < 1 or n > len(lines) for n in numbers)
                or len(set(numbers)) != len(numbers)):
            continue
        indexes = set(numbers)
        # When the harness provided a structured process status, always preserve its
        # own line. The envelope's anchored parser, not stdout vocabulary, owns it.
        envelope = resultnotes.exec_envelope(source.result)
        match = resultnotes._EXEC_HEADER.match(source.result) if envelope else None
        if match:
            for group in ("exit", "session"):
                if match[group] is not None:
                    indexes.add(source.result.count("\n", 0, match.start(group)) + 1)
        selected.append(Selection(source, tuple(sorted(indexes))))
    return tuple(selected)


def select(sources: tuple[compactionpacket.ToolEvidence, ...], task: str, chat_fn, role, rlog) -> tuple[Selection, ...]:
    """Ask once, abstaining if the reasoner or its answer is unavailable."""
    if not sources or not task or chat_fn is None or role is None:
        return ()
    messages = [{"role": "system", "content": prompts.load("history_selection_system")}]
    for source in sources:
        lines = source.result.splitlines(keepends=True)
        numbered = "".join(f"{i}: {line}" for i, line in enumerate(lines, 1))
        content = prompts.render("history_selection_entry", id=source.call_id,
                                 call=f"{source.name}({source.arguments})", lines=numbered)
        messages.append(selfcompact.internal_evidence_message(content))
    messages.append({"role": "user", "content": prompts.render("history_selection_question", task=task)})
    body = {"stream": False, "messages": messages, bodykeys.DENSITY_KIND: "summary"}
    try:
        if role is not None:
            role.apply(body, internal=True, rlog=rlog)
        old_phase = getattr(rlog, "phase", None)
        try:
            rlog.phase = "history-selection"
            completion = json.loads(chat_fn(body, rlog))
        finally:
            rlog.phase = old_phase
        if callsyntax.is_truncated(completion):
            return ()
        message = ((completion.get("choices") or [{}])[0].get("message") or {})
        text = message.get("content")
        if message.get("tool_calls") or not isinstance(text, str) or callsyntax.has_tool_call_leak(text):
            return ()
        return validate(sources, jsontext.extract_json_object(text))
    except Exception:
        return ()
