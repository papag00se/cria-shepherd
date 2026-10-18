"""Shared WHOLE_FILE/OTHER reader; admission, prompts and effects belong to policies."""
from typing import Protocol
from .classify import JUDGE_MAX_TOKENS


class ClosedJudge(Protocol):
    def __call__(self, question: str, *, phase: str, max_tokens: int,
                 retry_off: bool) -> str: ...


def whole_file_ruling(answer: str) -> str:
    """Read the first word, not a substring or a bare-answer-only judgment."""
    head = answer.upper().split()[0].strip(".,:;`*\"'") if answer.split() else ''
    return head if head in ('WHOLE_FILE', 'OTHER') else answer.strip().upper()[:40]


def judge_whole_file(ask: ClosedJudge, question: str, *, phase: str) -> str:
    """Use the existing closed reader without adding retries or changing role policy.

    The provider is the ordinary ask_closed seat with chat, role and log bound.
    Its reasoning-off/temperature-zero handling remains that shared reader's job.
    """
    return whole_file_ruling(ask(question, phase=phase, max_tokens=JUDGE_MAX_TOKENS, retry_off=False))
