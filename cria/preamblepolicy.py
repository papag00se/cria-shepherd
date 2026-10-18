"""Provenance-gated harness preamble reframing, shared by coder and reasoner.

This optional policy is not a credential scrubber, transport boundary, permission
interpreter, task detector, or system/developer-frame remover. Those foundations
and callers keep their authority when this policy is disabled. Recognition uses
the existing shared environment-shape predicate, never a new keyword classifier.
There are no model questions, durable state, or cross-session instruction caches.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Callable, Protocol

from . import prompts, selfcompact
from .assistcontract import Policy, Reference

ENV_FIELDS = (("cwd", "cwd"), ("shell", "shell"), ("current_date", "date"), ("timezone", "timezone"))
INSTRUCTION_FILES = ("AGENTS.md", "AGENT.md", "CLAUDE.md", "GEMINI.md", "CONVENTIONS.md",
                     ".cursorrules", ".windsurfrules", ".github/copilot-instructions.md")


class Workspace(Protocol):
    surveyed: bool

    def read(self, path: Path) -> str | None:
        """Trusted shared workspace body, or unknown/unreadable; may queue a survey demand."""
        ...


class Provenance(Enum):
    NOT_REQUESTED = auto()
    NO_WORKSPACE = auto()
    UNSURVEYED = auto()
    UNVERIFIED = auto()  # no matching trusted text; not a claim that a file is absent
    VERIFIED = auto()


@dataclass(frozen=True)
class Instructions:
    provenance: Provenance
    text: str | None = None
    filename: str | None = None


@dataclass(frozen=True)
class PreambleInput:
    message: dict
    workspace: Callable[[str], Workspace]


class Effect(Enum):
    NOT_SELECTED = auto()
    UNCHANGED = auto()
    REFRAMED = auto()


@dataclass(frozen=True)
class PreambleResult:
    message: dict
    effect: Effect
    instructions: Instructions = Instructions(Provenance.NOT_REQUESTED)


def text_content(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, list):
        return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content or ""


def tag_body(text: str, name: str) -> str | None:
    opening, closing = f"<{name}>", f"</{name}>"
    lo, hi = text.find(opening), text.find(closing)
    if lo == -1 or hi == -1 or hi < lo:
        return None
    return text[lo + len(opening):hi]


def workspace_instructions(cwd: str, relayed: str, workspace: Callable[[str], Workspace]) -> Instructions:
    """First matching workspace file, in original precedence and whitespace rules.

    Unknown and unreadable results do not establish provenance. No local open,
    existence probe, directory scan, or inference is substituted for the reader.
    The shared reader, not this policy, owns reachability, privacy and freshness.
    """
    if not cwd:
        return Instructions(Provenance.NO_WORKSPACE)
    view = workspace(cwd)
    if not view.surveyed:
        return Instructions(Provenance.UNSURVEYED)
    blob = " ".join(relayed.split())
    for name in INSTRUCTION_FILES:
        own = (view.read(Path(cwd) / name) or "").strip()
        if own and " ".join(own.split()) in blob:
            return Instructions(Provenance.VERIFIED, own, name)
    return Instructions(Provenance.UNVERIFIED)


def reframe(source: PreambleInput, *, enabled: bool = True) -> PreambleResult:
    message = source.message
    if not enabled:
        return PreambleResult(message, Effect.NOT_SELECTED)
    if message.get("role") != "user" or not selfcompact.is_env_context(message):
        return PreambleResult(message, Effect.UNCHANGED)
    text = text_content(message)
    instruction_text = tag_body(text, "INSTRUCTIONS") or tag_body(text, "user_instructions")
    env = tag_body(text, "environment_context")
    cwd = tag_body(env or "", "cwd") or ""
    instructions = Instructions(Provenance.NOT_REQUESTED)
    parts: list[str] = []
    if instruction_text and instruction_text.strip():
        instructions = workspace_instructions(cwd.strip(), instruction_text, source.workspace)
        if instructions.text:
            parts.append(prompts.render("preamble_instructions",
                instructions=instructions.text.replace("\r", "").strip()))
    if env:
        fields = [(label, value.strip()) for tag, label in ENV_FIELDS
                  if (value := tag_body(env, tag)) and value.strip()]
        if fields:
            parts.append(prompts.render("preamble_environment",
                fields=", ".join(f"{key}: {value}" for key, value in fields)))
    new = "\n\n".join(parts) if parts else None
    if not new:
        # Legacy no-extraction behavior: retain the raw message, not an empty
        # replacement or a claim that unknown instructions are foreign/absent.
        return PreambleResult(message, Effect.UNCHANGED, instructions)
    return PreambleResult({**message, "content": new}, Effect.REFRAMED, instructions)


@dataclass(frozen=True)
class BatchInput:
    messages: list[dict]
    workspace: Callable[[str], Workspace]


def reframe_messages(source: BatchInput, definition: Definition | None, *, enabled: bool = True) -> list[dict]:
    """Same selected policy for either caller; no role filtering or frame changes."""
    if not enabled or definition is None:
        return source.messages
    messages = [definition.execute(PreambleInput(m, source.workspace)).message for m in source.messages]
    return source.messages if all(a is b for a, b in zip(messages, source.messages)) else messages


@dataclass(frozen=True)
class Definition:
    policy: Policy
    execute: Callable[..., PreambleResult]


# Earliest legacy reach is the ungated harness-handoff evidence/retry path.
# Ordinary compaction framing is L3 and coder framing L4. Selection must not
# manufacture a new L0 invocation or silently remove the existing evidence seat.
DEFINITION = Definition(Policy(
    "verified-harness-preamble", "context-preamble", 0, family_id="F67",
    triggers=(("harness-handoff-evidence", 0), ("compaction-context", 3), ("coder-frame", 4)),
    prompts=("preamble_instructions", "preamble_environment"),
    state="stateless; reread current shared workspace facts per message; no reset/cache/pending effect",
    services=("shared-environment-shape-recognition", "surveyed-workspace-instruction-reader"),
    hooks=(Reference("cria/loop.py", "Loop._prepare_coder_context"),
           Reference("cria/loop.py", "reframe_preamble"),
           Reference("cria/loop.py", "_workspace_instructions"),
           Reference("cria/loop.py", "_frame_for_item"),
           Reference("cria/loop.py", "_drop_harness_frame"),
           Reference("cria/server.py", "_compaction_messages")),
    regressions=(Reference("tests/test_preamble_policy_source.py", "test_source_parity"),
                 Reference("tests/test_preamble_policy_source.py", "test_real_coder_and_reasoner_body_parity"),
                 Reference("tests/test_common_context_preparation.py", "test_absent_context_selection_never_runs_optional_leaf_detection")),
    migrated=False), reframe)
