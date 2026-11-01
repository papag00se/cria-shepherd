"""A whole fixture session through the real server: every body the model is sent is free of the product's name and private names."""
import json
import os
import re
import subprocess
import urllib.error
import urllib.request

import pytest

from cria import callcapture
from cria.config import RoutingConfig
from test_server_config_http import OPEN, FakeUpstream, Wire

SEEN = re.compile(r"(?i)cria|shepherd|mpsnap|___CTX_|__CTX_|__ctx_|\.ctx-(?:done|edits|gate|helper|mpsnap|private)")
STEPS = [("edit_file", {"old_string": "x = 1", "new_string": "x = 2"}), ("read_file", {}), ("write_file", {"content": "y = 3\n"})]
TASK = "Change x to 2 in app.py, read it back, then write b.py with y = 3."
SHELL = {"type": "function", "name": "exec_command", "description": "run", "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}}}


class Coder(FakeUpstream):
    """The model: one edit, one read, one write (each only when its tool is on the menu), then a closing message. Everything
    else (classifier, tokenizer, template) is answered as the plain fake does."""
    workspace = None

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        text = json.dumps(body.get("messages"))
        if self.path.endswith("/tokenize"):
            return self._reply({"tokens": [1] * (len(body["content"]) // 3)})
        if self.path.endswith("/apply-template"):
            return self._reply({"prompt": text})
        if "REQUEST CLASSIFIER" in text:
            return self._reply({"choices": [{"message": {"content": '{"engagement": "task", "task_type": "coding", "reason": "x"}'}}]})
        self.server.chats.append((dict(self.headers), body))
        menu = {t["function"]["name"] for t in body.get("tools") or [] if t.get("function")}
        done = sum(m.get("role") == "tool" for m in body["messages"])
        if done < len(STEPS) and STEPS[done][0] in menu:
            name, args = STEPS[done]
            target = Coder.workspace / ("b.py" if name == "write_file" else "app.py")
            call = {"id": f"call_{done}", "type": "function", "function": {"name": name, "arguments": json.dumps({"path": str(target), **args})}}
            return self._reply({"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [call]}, "finish_reason": "tool_calls"}]})
        return self._reply({"choices": [{"message": {"role": "assistant", "content": "All done: app.py sets x = 2 and b.py is written."}, "finish_reason": "stop"}]})


def post(wire, body):
    req = urllib.request.Request(f"http://127.0.0.1:{wire.cria.server_address[1]}/v1/responses", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "X-Cria-Session-Id": "fixture-1"})
    try:
        with OPEN(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as error:        # the server's own words, not a bare status
        raise AssertionError(f"after {len(body['input'])} input items: " + error.read().decode()[:600]) from error


def request(history, ws):
    user = lambda t: {"type": "message", "role": "user", "content": [{"type": "input_text", "text": t}]}
    return {"model": "m", "stream": False, "instructions": "You are a coding agent running in the Codex CLI.", "prompt_cache_key": "fixture-1",
            "input": [user(f"<environment_context>\n<cwd>{ws}</cwd>\n</environment_context>"), user(TASK), *history], "tools": [SHELL], "tool_choice": "auto"}


def test_a_fixture_session_and_its_replay_through_a_restarted_server_never_show_the_model_a_private_name(tmp_path, monkeypatch):
    """The structure lint covers composers one at a time; this one runs them together. A real edit, read and write are composed by the
    live server (L5), RUN by bash in a scratch workspace like the harness would, and their results fed back; then the whole history is
    replayed through a SECOND server with no memory of it (a restart, a resumed conversation). Every body either server sent upstream -
    messages, tools, keys and headers - is scanned for the product name and every private marker/directory name. The scan is not
    vacuous: the files really changed and the model's history shows the tools it called, not the shell programs that carried them."""
    monkeypatch.setattr(urllib.request, "_opener", None)
    monkeypatch.setattr(callcapture, "_seq", {})
    ws, scratch = tmp_path / "ws", tmp_path / "scratch"
    ws.mkdir(), scratch.mkdir()
    (ws / "app.py").write_text("x = 1\nprint(x)\n")
    Coder.workspace = ws
    history, bodies = [], []
    first = Wire(tmp_path / "one", lambda url: RoutingConfig(engagement_level=5))
    first.fake.RequestHandlerClass = Coder          # the model of this session answers instead of the plain fake
    try:
        for _ in range(8):
            items = post(first, request(history, ws)).get("output") or []
            history += items
            calls = [i for i in items if i.get("type") == "function_call"]
            if not calls:
                break
            for call in calls:
                done = subprocess.run(["bash", "-c", json.loads(call["arguments"])["cmd"]], cwd=ws, capture_output=True, text=True, timeout=60,
                                      env={**os.environ, "TMPDIR": str(scratch)})
                history.append({"type": "function_call_output", "call_id": call["call_id"],
                                "output": f"Chunk ID: a1\nWall time: 0.0100 seconds\nProcess exited with code {done.returncode}\nOriginal token count: 10\nOutput:\n{done.stdout}{done.stderr}"})
        bodies += first.fake.chats
    finally:
        first.close()
    assert (ws / "app.py").read_text() == "x = 2\nprint(x)\n" and (ws / "b.py").read_text() == "y = 3\n"
    second = Wire(tmp_path / "two", lambda url: RoutingConfig(engagement_level=5))
    second.fake.RequestHandlerClass = Coder
    try:
        post(second, request(history, ws))
        bodies += second.fake.chats
    finally:
        second.close()
    sent = [b for _, b in bodies]
    assert len(sent) >= 4
    seen = [(m.group(0), i) for i, (headers, b) in enumerate(bodies) for m in SEEN.finditer(json.dumps([headers, b], ensure_ascii=False))]
    assert seen == []
    last = [m for m in sent[-1]["messages"] if m.get("tool_calls")]
    assert [c["function"]["name"] for m in last for c in m["tool_calls"]] == [s[0] for s in STEPS]
