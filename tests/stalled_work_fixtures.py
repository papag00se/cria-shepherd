"""Offline assembly of shared facts/provider transports, never legacy action policy."""
import json
from cria import groundedaction as ga, loop


class _Log:
    phase = ""

    def __init__(self):
        self.events = []

    def emit(self, kind, **fields):
        self.events.append((kind, fields))


def engine():
    public = {"guard_ground_truth", "workspace_inventory"}
    facts = ga.EvidenceServices(**{
        name: getattr(loop, name if name in public else "_" + name)
        for name in ga.EvidenceServices.__annotations__})
    return ga.GroundedActions(facts, ga.ProviderServices(loop.summarize, loop._judge_completion))


def seat(text="a vetted action", *, checks="exact failure", calls=None):
    def chat(body, log):
        if calls is not None:
            calls.append(body)
        answer = "SUPPORTED" if body.get("messages", [{}])[0].get("content", "").find("SUPPORTED") >= 0 else (text or "ON_TRACK")
        return json.dumps({"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": answer}}]}).encode()
    return ga.AuthorInput(chat, None, None, ga.ActionEvidence(original_task="ORIGINAL TASK", last_gate_flag=checks),
                          {"messages": [{"role": "user", "content": "ORIGINAL TASK"}]}, _Log(), "refusal")
