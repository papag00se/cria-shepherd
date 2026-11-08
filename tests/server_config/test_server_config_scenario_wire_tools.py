"""Real HTTP with tools in all four wire modes (write_file lowered to a runnable exec_command), the Responses ticker, failure and shutdown drain, and a compaction turn."""
import json
import urllib.request
import subprocess

import pytest

from cria.config import Backend, Role, RoutingConfig
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


def test_native_write_with_shell_keeps_native_write_and_advertises_search(tmp_path):
    w = Wire(tmp_path, CLASSIFYING)
    try:
        path, body = request('chat-buffered', '__TOOL__ please write hello.txt')
        body['tools'] = [{'type': 'function', 'function': EXEC},
                         {'type': 'function', 'function': {'name': 'write_file', 'parameters': {'type': 'object'}}}]
        raw = w.post(path, body)[1]
        menus = [{t['function']['name'] for t in sent.get('tools', [])} for _, sent in w.fake.chats]
        before = len(w.fake.chats)
        body['tools'] = [body['tools'][1]]
        no_shell_raw = w.post(path, body, sid='no-shell')[1]
        no_shell_menus = [{t['function']['name'] for t in sent.get('tools', [])} for _, sent in w.fake.chats[before:]]
    finally:
        w.close()
    assert [name for name, _ in tool_calls('chat-buffered', raw)] == ['write_file']
    assert [name for name, _ in tool_calls('chat-buffered', no_shell_raw)] == ['write_file']
    assert any({'write_file', 'exec_command', 'grep', 'glob'} <= names for names in menus)
    assert all('grep' not in names and 'glob' not in names for names in no_shell_menus)


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


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("failure", ["__NONJSON__", "__500__"])
@pytest.mark.parametrize("classifier_present", [False, True])
def test_compaction_survives_optional_writer_failure(tmp_path, mode, failure, classifier_present):
    w = Wire(tmp_path / "w", lambda url: RoutingConfig(
        backends={"local": Backend("local")}, failover={"coding": ("coder",)}, engagement_level=3,
        roles={r: Role(r, "local") for r in ("classifier", "reasoner", "coder")}))
    class Judge:
        def judge_compaction_topic(self, task, response, *, rlog):
            pytest.fail("an absent writer response must not be classified")
    if classifier_present:
        w.cria.system1 = Judge()
    chat, items = conversation(tmp_path, f"{LOCAL_COMPACT_MARKER} summarize", f"build app.py {failure}")
    path, body = (("/v1/responses", {"model": "m", "prompt_cache_key": "sid-1", "input": items, "stream": mode.endswith("stream")})
                  if mode.startswith("responses") else ("/v1/chat/completions", {"model": "m", "messages": chat, "stream": mode.endswith("stream")}))
    try:
        reply = reply_text(mode, w.post(path, body)[1])
    finally:
        w.close()
    assert "build app.py" in reply and "print(1)" in reply and "cat app.py" in reply
    assert "MODEL-SUGGESTED NEXT ACTION" not in reply


@pytest.mark.parametrize("later", ["", "Use Rust instead."])
def test_two_compactions_authenticate_prior_evidence_and_followup(tmp_path, later):
    from cria.loop import PlanSession, reframe_compaction
    from cria.planner import Plan, PlanItem
    w = Wire(tmp_path / "w", lambda url: RoutingConfig(
        backends={"local": Backend("local")}, failover={"coding": ("coder",)}, engagement_level=4,
        roles={r: Role(r, "local") for r in ("classifier", "reasoner", "coder")}))
    w.cria.loop._put_session("sid:sid-1", PlanSession(plan=Plan(id="p", task="build app.py", created="c", items=[PlanItem("build app.py")]), synthetic=True))
    history, _ = conversation(tmp_path, f"{LOCAL_COMPACT_MARKER} summarize")
    history.insert(-1, {"role": "user", "content": "Use Go for the implementation."})
    try:
        _, raw = w.post("/v1/chat/completions", {"model": "m", "messages": history})
        first = reply_text("chat-buffered", raw)
        second_history = [{"role": "user", "content": first}, {"role": "assistant", "content": "more work"}]
        if later:
            second_history.append({"role": "user", "content": later})
        second_history.append({"role": "user", "content": f"{LOCAL_COMPACT_MARKER} summarize again"})
        _, raw = w.post("/v1/chat/completions", {"model": "m", "messages": second_history})
        second = reply_text("chat-buffered", raw)
        origin = w.cria.loop._store.get("sid:sid-1").handoff_origin
    finally:
        w.close()
    assert second.count("HISTORICAL tool (call id c1) MESSAGE:\nprint(1)") == 1
    expected = later or "Use Go for the implementation."
    assert expected == origin.packet.latest_user
    expanded, _ = reframe_compaction([{"role": "user", "content": second}], origin=origin)
    assert expanded[-1] == {"role": "user", "content": expected}


@pytest.mark.parametrize("mode", MODES)
def test_marked_compaction_with_tools_still_returns_packet(tmp_path, mode):
    w = Wire(tmp_path / "w", lambda url: RoutingConfig(
        backends={"local": Backend("local")}, failover={"coding": ("coder",)}, engagement_level=3,
        roles={r: Role(r, "local") for r in ("classifier", "reasoner", "coder")}))
    chat, items = conversation(tmp_path, f"{LOCAL_COMPACT_MARKER} summarize")
    path, body = (("/v1/responses", {"model": "m", "prompt_cache_key": "sid-1", "input": items, "stream": mode.endswith("stream"), "tools": [{"type": "function", **EXEC}]})
                  if mode.startswith("responses") else ("/v1/chat/completions", {"model": "m", "messages": chat, "stream": mode.endswith("stream"), "tools": [{"type": "function", "function": EXEC}]}))
    try:
        reply = reply_text(mode, w.post(path, body)[1])
    finally:
        w.close()
    assert "build app.py" in reply and "print(1)" in reply and "cat app.py" in reply


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("plan", [False, True])
def test_compaction_preserves_task_and_tool_output_in_each_wire_mode(tmp_path, mode, plan):
    """A compaction handoff retains the original task and actual tool output, not unjudged model prose."""
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "app.py").write_text("print(1)\n")
    w = Wire(tmp_path / "w", lambda url: RoutingConfig(
        backends={"local": Backend("local")}, failover={"coding": ("coder",)}, engagement_level=3,
        roles={r: Role(r, "local") for r in ("classifier", "reasoner", "coder", "compactor")}))
    chat, items = conversation(tmp_path / "proj", f"{LOCAL_COMPACT_MARKER} summarize the work so far",
                              "build app.py" + (" __PLAN__" if plan else ""))
    try:
        path, body = ("/v1/responses", {"model": "m", "prompt_cache_key": "sid-1", "input": items, "stream": mode.endswith("stream")}) if mode.startswith("resp") else (
            "/v1/chat/completions", {"model": "m", "messages": chat, "stream": mode.endswith("stream")})
        reply = reply_text(mode, w.post(path, body)[1])
        skipped = "classify.skipped" in [e["kind"] for e in w.events()]
    finally:
        w.close()
    writer = next(b for _, b in w.fake.chats if "Answer the final question using the provided evidence" in json.dumps(b["messages"]))
    assert "tools" not in writer and LOCAL_COMPACT_MARKER not in json.dumps(writer)
    assert skipped and not any("REQUEST CLASSIFIER" in json.dumps(b) for _, b in w.fake.chats)
    assert "build app.py" in reply and "print(1)" in reply and "cat app.py" in reply
    assert "rewrite app.py" not in reply
