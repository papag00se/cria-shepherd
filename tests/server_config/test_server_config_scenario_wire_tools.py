"""Real HTTP with tools in all four wire modes (write_file lowered to a runnable exec_command), the Responses ticker, failure and shutdown drain, and a compaction turn."""
import json
import urllib.request
import subprocess

import pytest

from cria.config import Backend, Role, RoutingConfig
from cria.indicators import PROSE_DROPPED_MARKER
from cria.server import LOCAL_COMPACT_MARKER
from test_server_config_http import MODES, OPEN, Wire, no_installed_opener, reply_text, request, sse_events  # noqa: F401

EXEC = {"name": "exec_command", "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}}}
CLASSIFYING = lambda url: RoutingConfig(backends={"local": Backend("local")}, failover={"coding": ("coder",)}, engagement_level=3,
                                        roles={"classifier": Role("classifier", "local"), "coder": Role("coder", "local")})


def tool_calls(mode, raw):
    """The (name, arguments) function calls a client of that wire mode would act on."""
    if mode == "chat-buffered":
        return [(c["function"]["name"], c["function"]["arguments"]) for c in json.loads(raw)["choices"][0]["message"]["tool_calls"]]
    if mode == "chat-stream":
        out = {}
        for e in sse_events(raw):
            for c in (e.get("choices") or [{}])[0].get("delta", {}).get("tool_calls", []):
                name, args = out.get(c["index"], ("", ""))
                out[c["index"]] = (name + c["function"].get("name", ""), args + c["function"].get("arguments", ""))
        return list(out.values())
    items = (json.loads(raw)["output"] if mode == "responses-buffered"
             else [e["item"] for e in sse_events(raw) if e.get("type") == "response.output_item.done"])
    return [(i["name"], i["arguments"]) for i in items if i["type"] == "function_call"]


@pytest.mark.parametrize("mode", MODES)
def test_a_write_file_call_reaches_every_wire_mode_as_a_runnable_exec_command_that_writes_the_file(tmp_path, mode):
    """The model only knows write_file, the harness only exec_command: in every framing the harness gets ONE exec_command whose command, run in a real shell, lands the exact file."""
    w = Wire(tmp_path / "w", CLASSIFYING, indicators=True)
    try:
        path, body = request(mode, "__TOOL__ please write hello.txt")
        body["tools"] = [{"type": "function", "function": EXEC}] if mode.startswith("chat") else [{"type": "function", **EXEC}]
        raw = w.post(path, body)[1]
    finally:
        w.close()
    calls = tool_calls(mode, raw)
    assert [n for n, _ in calls] == ["exec_command"] and "write_file" not in raw.split('"cmd"')[0]
    work = tmp_path / "harness"
    work.mkdir()
    done = subprocess.run(["bash", "-c", json.loads(calls[0][1])["cmd"]], cwd=work, capture_output=True, text=True)
    assert done.returncode == 0 and '"k":"landed"' in done.stdout
    assert (work / "hello.txt").read_text() == "hi there\n"
    if mode == "responses-stream":  # the ticker narrates the pipeline into a status item the model never re-reads
        shown = [e["delta"] for e in sse_events(raw) if e.get("type") == "response.output_text.delta"]
        assert shown[:2] == ["⟦cria⟧ (classifier) ⋯ classifying\n", "⟦cria⟧ writing hello.txt\n"]


def test_a_responses_stream_ends_with_a_retryable_failure_on_upstream_error_and_on_shutdown(tmp_path):
    """An upstream 500 becomes response.failed with the upstream's words, never an empty completion; a restart mid-generation drains the open stream with a codeless (retryable) response.failed."""
    w = Wire(tmp_path, heartbeat=0.05)
    try:
        failed = [e for e in sse_events(w.post(*request("responses-stream", "__500__"))[1]) if e["type"].startswith("response.")]
        assert failed[-1]["type"] == "response.failed" and failed[-1]["response"]["error"]["message"] == "template rejected"
        assert all(e["type"] != "response.completed" for e in failed)
        path, body = request("responses-stream", "__SLOW__")
        req = urllib.request.Request(f"http://127.0.0.1:{w.cria.server_address[1]}{path}",
                                                           json.dumps(body).encode(), {"Content-Type": "application/json"})
        with OPEN(req, timeout=20) as r:
            seen = b""
            while b"response.in_progress" not in seen:  # the stream is open and registered
                seen += r.readline()
            assert w.cria.drain_streams() == 1
            w.fake.release.set()  # the model call finishes after the drain; nothing more reaches the client
            seen += r.read()
    finally:
        w.fake.release.set()
        w.close()
    last = [e for e in sse_events(seen.decode()) if e["type"].startswith("response.")][-1]
    assert last["type"] == "response.failed" and "restarting" in last["response"]["error"]["message"] and "code" not in last["response"]["error"]


def conversation(workspace, last, task="build app.py"):
    """A coding session's history (one tool call, one answer) ending in `last`, as chat messages and as Responses input items."""
    chat = [{"role": "user", "content": f"<environment_context><cwd>{workspace}</cwd></environment_context> {task}"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "exec_command", "arguments": '{"cmd":"cat app.py"}'}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "print(1)"}, {"role": "assistant", "content": "done with app.py"},
            {"role": "user", "content": last}]
    text = lambda role, t: {"type": "message", "role": role, "content": [{"type": "input_text" if role == "user" else "output_text", "text": t}]}
    items = [text("user", chat[0]["content"]), {"type": "function_call", "call_id": "c1", "name": "exec_command", "arguments": '{"cmd":"cat app.py"}'},
             {"type": "function_call_output", "call_id": "c1", "output": "print(1)"}, text("assistant", "done with app.py"), text("user", last)]
    return chat, items


@pytest.mark.parametrize("mode", ["chat-buffered", "responses-buffered", "responses-stream"])
@pytest.mark.parametrize("plan", [False, True])
def test_a_compaction_request_is_rewritten_judged_and_only_a_retrospective_briefing_is_handed_back(tmp_path, mode, plan):
    """A marked compaction turn goes to the compactor under a no-tools prompt without the marker, never to the classifier; a retrospective briefing is returned as
    written, one prescribing a next step is replaced by the deterministic record of what the tools did (prose-dropped marker + the issued `cat app.py`)."""
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "app.py").write_text("print(1)\n")
    w = Wire(tmp_path / "w", lambda url: RoutingConfig(
        backends={"local": Backend("local")}, failover={"coding": ("coder",)}, engagement_level=3,
        roles={r: Role(r, "local") for r in ("classifier", "reasoner", "coder", "compactor")}))
    chat, items = conversation(tmp_path / "proj", f"{LOCAL_COMPACT_MARKER} summarize the work so far",
                              "build app.py" + (" __PLAN__" if plan else ""))
    try:
        path, body = ("/v1/responses", {"model": "m", "prompt_cache_key": "sid-1", "input": items, "stream": mode.endswith("stream")}) if mode.startswith("resp") else (
            "/v1/chat/completions", {"model": "m", "messages": chat})
        reply = reply_text(mode, w.post(path, body)[1])
        skipped = "classify.skipped" in [e["kind"] for e in w.events()]
    finally:
        w.close()
    compactor = next(b for _, b in w.fake.chats if "You are writing a briefing" in json.dumps(b["messages"]))
    assert "tools" not in compactor and LOCAL_COMPACT_MARKER not in json.dumps(compactor)
    assert skipped and not any("REQUEST CLASSIFIER" in json.dumps(b) for _, b in w.fake.chats)  # 131 minutes once
    if plan:
        assert reply.startswith(PROSE_DROPPED_MARKER) and "issued (result recorded; execution not established): cat app.py" in reply and "rewrite app.py" not in reply
    else:
        assert reply == "The user asked for app.py. app.py now exists and prints 1; no check has failed."
