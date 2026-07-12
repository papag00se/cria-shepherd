#!/usr/bin/env python3
"""Probe how the loaded model responds to different planner prompts — to find out
whether Gemma needs the numbered-LIST format, the INVESTIGATE phase, or both,
before changing cria's planner. Run against whatever model is on :18084."""

import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cria.classify import completion_text  # noqa: E402
from cria.events import EventLog  # noqa: E402
from cria.jsontext import extract_json_object  # noqa: E402
from cria.planner import PLAN_PROMPT as CRIA_JSON_PROMPT  # noqa: E402
from cria.upstream import Upstream  # noqa: E402

TASK = (
    "Write a Python Lambda handler that resolves an Ada Handle to a Cardano address "
    "via api.handle.me, returning the resolved address, holder address, and total "
    "handles. Add unit tests, a live test for `goose`, and a README."
)

# A clean numbered-list ask — no JSON, no tools, no investigate phase.
LIST_PROMPT = (
    "You are a planner for a SMALL local coding model. Break the user's task into a "
    "SHORT ordered list of 4-9 small, concrete steps the coder will do ONE AT A TIME. "
    "Output ONLY a numbered list — one short imperative sentence per step, naming the "
    "specific file or command. Do NOT write code. Do NOT explain your reasoning."
)

# codex-local's exact working prompt (investigate-then-plan). Note: this probe does
# NOT advertise tools, so if Gemma insists on a tool call here, the investigate phase
# (harness-run read-only tools) is what it actually needs.
CODEX_PROMPT = (
    "You are the PLANNER for a SMALL local coding model. Your job has TWO phases: first "
    "INVESTIGATE using your read-only tools, then output the plan.\n"
    "PHASE 2 — PLAN: When you have gathered enough, STOP calling tools and output ONLY the "
    "plan. Break the task into a SHORT, ordered list of SMALL steps.\n"
    "Once investigating is done, output ONLY a numbered list — one short imperative sentence "
    "per step, naming the specific file, command, source, or change."
)

PROMPTS = [("cria JSON (current)", CRIA_JSON_PROMPT), ("clean numbered-list", LIST_PROMPT), ("codex investigate+list", CODEX_PROMPT)]

_NUM_LINE = re.compile(r"^\s*(\d+)[.)]\s+\S", re.M)


def looks_like_a_tool_call(text: str) -> bool:
    return "<|tool_call" in text or "<tool_call" in text or '"tool_call' in text or "call:" in text


def main() -> int:
    endpoint = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18084").rstrip("/")
    with urllib.request.urlopen(endpoint + "/v1/models", timeout=5) as r:
        model = json.loads(r.read())["data"][0]["id"]
    up = Upstream(endpoint, 120)
    rlog = EventLog(level="error", dir=None, console=False, jsonl=False).bind(session="probe", turn="probe")

    print(f"### model: {model} ###\n")
    for label, sysprompt in PROMPTS:
        raw = up.chat(
            {"model": model, "stream": False, "temperature": 0,
             "messages": [{"role": "system", "content": sysprompt}, {"role": "user", "content": TASK}]},
            rlog,
        )
        text = completion_text(raw).strip()
        n_steps = len(_NUM_LINE.findall(text))
        verdict = (
            "JSON-plan" if (extract_json_object(text) or {}).get("steps") else
            f"numbered-list ({n_steps} steps)" if n_steps >= 3 else
            "TOOL-CALL (wants to act)" if looks_like_a_tool_call(text) else
            "other/unusable"
        )
        print(f"── {label} → {verdict}")
        print("   " + text.replace("\n", "\n   ")[:600])
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
