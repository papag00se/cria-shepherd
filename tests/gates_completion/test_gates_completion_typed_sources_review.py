"""The step judge's sources block keeps WHAT KIND of read each entry is: a file on disk is never worded as a web response."""
import json
import logging
from types import SimpleNamespace

from cria import research, stepreview
from cria.fetchfacts import Shape


def _messages():
    return [{"role": "assistant", "content": None, "tool_calls": [{"id": "r1", "type": "function", "function": {
                 "name": "read_file", "arguments": json.dumps({"path": "src/Importer.java"})}}]},
            {"role": "tool", "tool_call_id": "r1", "content": "class Importer {}\n"}]


def _ledger():
    return {"https://api.example/openapi.json": ("HTTP 200", ("/v1/handle",), (Shape("GET /v1/handle", "{address: string}"),), ())}


def _judged_user(sources):
    asked = []
    services = stepreview.StepServices(
        read=lambda request: asked.append(request.user) or stepreview.StepAnswer({"done": False}, "{}"),
        normalize_flag=lambda verdict, _flag, _phase: verdict, confirm=lambda _step: None, diagnosis=lambda _d: "",
        persist=lambda _record: None, confirmation_nudge=lambda text: text, named_gap=lambda _text: "")
    log = SimpleNamespace(emit=lambda *a, **k: None)
    stepreview.review_step(stepreview.StepInput("Read the API and Importer.java", "done", "", stepreview.ProbeEvidence(), services, log,
                                                sources_read=tuple(sources)))
    return asked[0]


def test_a_file_read_reaches_the_step_judge_as_a_file_and_a_web_read_keeps_its_fields_wording():
    """ornith1.5_9b / Java: a file read rendered as `response fields it defines: N chars read from disk`, the label of a web
    entry's shapes slot. The kind now travels from the ledger to the judge's request."""
    user = _judged_user(research.sources_read(_ledger(), _messages()))
    lines = user.splitlines()
    web = lines.index("- https://api.example/openapi.json")
    assert lines[web + 1] == "    routes it defines: /v1/handle" and lines[web + 2].startswith("    response fields it defines: GET /v1/handle")
    file_at = lines.index("- src/Importer.java")
    assert "18 chars" in lines[file_at + 1] and "response fields" not in lines[file_at + 1] and "routes it defines" not in lines[file_at + 1]
