"""Result shapes exactly as the REAL producers print them (`cria.resultpacket`), for fixtures that cannot run the command.

The write and edit programs print a typed `landed` record first (carrying their own typed reports, never tags in a tail).
Use these with a call lowered by `translate_outbound` so the receipt in the call's own sentinel is the one the record
carries."""
from cria import denial, resultpacket, toolwire, writeproxy
from tests.harnessenv import harness_env

LANDED_SHORTHAND = "\u27e6ctx:wrote\u27e7"     # old fixtures wrote this flat line to mean "the write landed"; it is no longer printed


def receipt(tc):
    return toolwire.receipt_of(writeproxy._command_of(tc["function"]["arguments"]), tc.get("id"))


def record(tc, kind, **kw):
    return resultpacket.line(receipt(tc), kind, **kw)


def landed(tc, rest="", survey=None, rep=None):
    """What a lowered write/edit prints when the mutation landed: the typed record (with its typed reports), the survey record
    when the sentinel declared one, then the program's own remaining lines."""
    return (record(tc, denial.LANDED, rep=rep)
            + (resultpacket.line(receipt(tc), resultpacket.SURVEY, body=survey.encode()) if survey else "") + rest)


def survey_record(tc, survey):
    return resultpacket.line(receipt(tc), resultpacket.SURVEY, body=survey.encode())


def lowered(name, arguments, text, cid="c1", kind=denial.RAN, rep=None):
    """``(sentinel line, result)`` for a call lowered by the REAL compiler's rules, from a hand-written result ``text``.

    A fixture that predates the typed records wrote the program's output as flat text: a landed-write shorthand line, then a
    survey block. The real programs print a `landed` record (with typed reports), then — when the sentinel declares one — the
    survey as a SECOND record, then their own lines. This turns the flat text into exactly that, so the fixture still pins what
    it meant to (a landed write, a survey riding home) through the real consumer."""
    from cria import wsview
    arguments = arguments if isinstance(arguments, str) else __import__("json").dumps(arguments)
    rcpt = denial.receipt_for(cid, name, arguments)
    before, sep, survey = text.partition(wsview.SURVEY_OPEN)
    survey = (sep + survey) if sep else ""
    sentinel = toolwire._sentinel(name, arguments, rcpt, bool(survey))
    wrote = any(ln.strip() == LANDED_SHORTHAND for ln in before.splitlines())
    before = "".join(ln for ln in before.splitlines(keepends=True) if ln.strip() != LANDED_SHORTHAND)
    first = resultpacket.line(rcpt, denial.LANDED if wrote else kind, rep=rep)
    second = resultpacket.line(rcpt, resultpacket.SURVEY, body=survey.encode()) if survey else ""
    return sentinel, first + second + before


def leading_frame(stdout, token):
    """``(kind, text of the first record line)`` of a real program's stdout, or ``(None, "")`` — the read the inbound pass
    does, for a test that runs the command and then asks what it printed first."""
    rec = resultpacket.read_record(stdout, 0, token)
    return (rec.kind, stdout[:rec.end]) if rec is not None else (None, "")


def rep_of(stdout):
    """The typed reports (`ev`, `late`, `rm`, `ef`, `st`) of the FIRST record a real program printed, or None."""
    import json
    first = stdout.split("\n", 1)[0]
    return (json.loads(first).get("rep") if first.startswith('{"v":1,') else None)


_FETCHES = [0]


def _fetch_url_of(content):
    import re
    m = re.search(r"\u00b7\s*(https?://\S+)", content)
    return m.group(1) if m else "https://fixture.example/"


def _lower_run_represent(url, patches):
    """The production round trip for ONE web_fetch call: the real `translate_outbound`, the real compiled program executed in a
    shell, the real `represent_inbound`. ``patches`` are the context managers that replace NETWORK I/O only."""
    import contextlib
    import json as _json
    import os
    import subprocess
    import tempfile
    from cria import wsview
    _FETCHES[0] += 1
    cid = f"genuine-fetch-{_FETCHES[0]}"
    comp = {"choices": [{"message": {"tool_calls": [{"id": cid, "type": "function", "function": {
        "name": "web_fetch", "arguments": _json.dumps({"url": url})}}]}}]}
    shell = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        writeproxy.translate_outbound(comp, shell, injected={"web_fetch"}, workspace_root="/w")
    tc = comp["choices"][0]["message"]["tool_calls"][0]
    with tempfile.TemporaryDirectory() as cwd:
        env = harness_env(cwd)
        p = subprocess.run(["bash", "-c", _json.loads(tc["function"]["arguments"])["cmd"]], cwd=cwd, env=env,
                           capture_output=True, text=True)
        raw = ("Chunk ID: ab\nWall time: 0.0 seconds\nProcess exited with code 0\nOriginal token count: 9\nOutput:\n"
               + p.stdout + p.stderr)
        token = wsview.bind(wsview.View(cwd, "uv"))
        try:
            return writeproxy.represent_inbound(
                [{"role": "assistant", "tool_calls": [tc]}, {"role": "tool", "tool_call_id": cid, "content": raw}],
                workspace_root=cwd)
        finally:
            wsview.unbind(token)


def genuine_call(name, arguments, cid, cwd, cut_stdout=None, running=False):
    """``[assistant call, tool result]`` for ONE lowered file tool call through the WHOLE production path: the real
    `translate_outbound` (workspace root = ``cwd``), the compiled private program executed in ``cwd``, the real
    `represent_inbound` that stamps the typed outcome hint. Nothing is replaced. A write the program refuses (e.g. content that
    does not parse for its type) comes back typed `refused`; one that lands comes back typed `landed`. ``cut_stdout=N`` keeps only
    the first N bytes of the program's stdout (a transport that delivered a cut first record): the write still HAPPENED on disk,
    but what cria received cannot prove it — the result comes back with no typed outcome. ``running=True`` delivers what the harness
    answers when a command outlives its yield window ("Process running with session ID …", no output yet): the program HAS run to
    completion here (so the disk shows its effect), but the reply received says it is still running — arrival, not completion."""
    import json as _json
    import os
    import subprocess
    from cria import wsview
    comp = {"choices": [{"message": {"tool_calls": [{"id": cid, "type": "function", "function": {
        "name": name, "arguments": _json.dumps(arguments)}}]}}]}
    shell = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}
    writeproxy.translate_outbound(comp, shell, injected={name}, workspace_root=str(cwd))
    tc = comp["choices"][0]["message"]["tool_calls"][0]
    env = harness_env(cwd)
    p = subprocess.run(["bash", "-c", _json.loads(tc["function"]["arguments"])["cmd"]], cwd=str(cwd), env=env,
                       capture_output=True, text=True)
    stdout = p.stdout if cut_stdout is None else p.stdout[:cut_stdout]
    if running:
        raw = ("Chunk ID: ab\nWall time: 1.0 seconds\nProcess running with session ID 7\nOriginal token count: 0\nOutput:\n")
    else:
        raw = ("Chunk ID: ab\nWall time: 0.0 seconds\nProcess exited with code " + str(p.returncode)
               + "\nOriginal token count: 9\nOutput:\n" + stdout + ("" if cut_stdout is not None else p.stderr))
    token = wsview.bind(wsview.View(str(cwd), "uv"))
    try:
        return writeproxy.represent_inbound(
            [{"role": "assistant", "tool_calls": [tc]}, {"role": "tool", "tool_call_id": cid, "content": raw}],
            workspace_root=str(cwd))
    finally:
        wsview.unbind(token)


def typed_result(cid, content, outcome=None):
    """A tool result as `represent_inbound` hands it on: the text plus, when cria PROVED an outcome, the typed hint
    (`denial.LANDED` / `denial.REFUSED` / `denial.UNCERTAIN` …). No hint = cria proved nothing (unknown)."""
    from cria import bodykeys
    m = {"role": "tool", "tool_call_id": cid, "content": content}
    if outcome is not None:
        m[bodykeys.RESULT_OUTCOME] = outcome
    return m


def genuine_fetch(url, document, *, status=200, content_type="application/json"):
    """``[assistant web_fetch call, tool result]`` from the WHOLE production path with ONLY the HTTP GET replaced: real parse of the
    document, real renderer, real fact producer (`webfetch.structure_facts`), real lowering, executed private program, real
    representation. ``document`` is the body the server sends (a dict is served as JSON)."""
    import json as _json
    from unittest import mock
    from cria import webfetch
    body = document if isinstance(document, str) else _json.dumps(document)
    webfetch._DOC_CACHE.pop(url, None)
    get = mock.patch.object(webfetch, "fetch", return_value=webfetch.FetchResult(status, url, content_type, body, False))
    return _lower_run_represent(url, [get])


def genuine_mcp_fetch(url, *, get_status=405, tools=()):
    """The same, for an MCP endpoint: only the HTTP GET and the JSON-RPC POSTs are replaced (a GET 405, then a working
    initialize/tools/list). ``tools`` are MCP tool definitions the server lists."""
    import json as _json
    from unittest import mock
    from cria import webfetch
    init = _json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-03-26", "serverInfo": {"name": "svc"}}})
    listing = _json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"tools": list(tools)}})

    def post(u, payload, headers):
        method = payload.get("method")
        return (200, init if method == "initialize" else listing if method == "tools/list" else "{}", {})
    webfetch._DOC_CACHE.pop(url, None)
    get = mock.patch.object(webfetch, "fetch", return_value=webfetch.FetchResult(get_status, url, "text/plain", "jsonrpc method not allowed", False))
    return _lower_run_represent(url, [get, mock.patch("cria.apidiscovery._post_json", side_effect=post)])


def fetch_pair(content, url=None, *, status=200, routes=(), shapes=(), catalog=(), observed=""):
    """DOWNSTREAM-CONSUMER fixture only — it mocks `fetch_nav_result`, so it proves nothing about how facts are produced (use
    `genuine_fetch` for that). ``[assistant web_fetch call, tool result]``: the real `translate_outbound` lowers the
    call, the real `_fetch_command` composes the program that prints the typed `ran` record (`rep.fx`) carrying the facts the
    PRODUCER declares (``status``, ``routes`` (tuple of str), ``shapes`` (tuple of `fetchfacts.Shape`), ``catalog`` (tuple of str), ``observed`` — given explicitly, never scanned out of
    ``content``), the program is executed, and the real `represent_inbound` lifts it. Only the HTTP fetch is replaced."""
    import json as _json
    import os
    import subprocess
    import tempfile
    from unittest import mock
    from cria import wsview
    url = url or _fetch_url_of(content)
    _FETCHES[0] += 1
    cid = f"fetch-fixture-{_FETCHES[0]}"
    from cria import fetchfacts
    facts = {"url": url, "status": f"HTTP {status}", "routes": list(routes), "shapes": [fetchfacts.report(s) for s in shapes],
             "catalog": list(catalog), "observed": observed}
    comp = {"choices": [{"message": {"tool_calls": [{"id": cid, "type": "function", "function": {
        "name": "web_fetch", "arguments": _json.dumps({"url": url})}}]}}]}
    shell = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}
    with mock.patch.object(writeproxy.webfetch, "fetch_nav_result", return_value=(content, False, status, facts)):
        writeproxy.translate_outbound(comp, shell, injected={"web_fetch"}, workspace_root="/w")
    tc = comp["choices"][0]["message"]["tool_calls"][0]
    with tempfile.TemporaryDirectory() as cwd:
        env = harness_env(cwd)
        p = subprocess.run(["bash", "-c", _json.loads(tc["function"]["arguments"])["cmd"]], cwd=cwd, env=env,
                           capture_output=True, text=True)
        raw = ("Chunk ID: ab\nWall time: 0.0 seconds\nProcess exited with code 0\nOriginal token count: 9\nOutput:\n"
               + p.stdout + p.stderr)
        token = wsview.bind(wsview.View(cwd, "uv"))
        try:
            return writeproxy.represent_inbound(
                [{"role": "assistant", "tool_calls": [tc]}, {"role": "tool", "tool_call_id": cid, "content": raw}],
                workspace_root=cwd)
        finally:
            wsview.unbind(token)


def native_fetch_pair(content, url=None):
    """``[assistant web_fetch call, tool result]`` for the harness's OWN `web_fetch`: no cria record, bytes visible, facts UNKNOWN."""
    import json as _json
    url = url or _fetch_url_of(content)
    _FETCHES[0] += 1
    cid = f"native-fetch-{_FETCHES[0]}"
    return [{"role": "assistant", "tool_calls": [{"id": cid, "type": "function", "function": {
        "name": "web_fetch", "arguments": _json.dumps({"url": url})}}]},
        {"role": "tool", "tool_call_id": cid, "content": content}]
