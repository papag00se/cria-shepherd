"""Server-side helpers on their real inputs: which web calls the conversation still shows (refused ones never ran), the workspace remembered per session
(never cria's own '.'), the ⟦cria⟧ line placement in completions, the proxy body's persona stripping and the Responses session identity."""
import json

import pytest

from cria import responses, server
from cria.loop import session_key


def call(cid, name, **args):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def test_visible_web_calls_list_only_calls_the_model_can_still_read():
    """web_fetch keys carry (url, find, cursor, raw); searches are queries; a call with no url/query is ignored; non-assistant and non-dict messages are skipped."""
    messages = ["junk", {"role": "user", "content": "hi"},
                {"role": "assistant", "tool_calls": [call("a", "web_fetch", url="http://x/doc", find="needle", cursor=3),
                                                      call("b", "web_fetch", url="http://x/raw", raw=True, cursor="9"),
                                                      call("c", "web_fetch"), call("d", "web_search", query="rust lifetimes"),
                                                      call("e", "local_web_search", query="go modules"), call("f", "web_search", query=""),
                                                      call("g", "shell", cmd="ls")]},
                {"role": "tool", "tool_call_id": "a", "content": "page text"}]
    fetch_keys, queries = server._visible_web_calls(messages)
    assert queries == ["rust lifetimes", "go modules"]
    assert [k.key for k in fetch_keys] == [("http://x/doc", "needle", "3", False), ("http://x/raw", "", "", True)]   # raw drops the cursor


@pytest.mark.parametrize("existing, line, expected", [
    ("answer", "⟦cria⟧ note", "⟦cria⟧ note\nanswer"),
    (None, "⟦cria⟧ note", "⟦cria⟧ note"),
    ("", "⟦cria⟧ note", "⟦cria⟧ note"),
])
def test_assist_notes_lead_the_content_as_their_own_line(existing, line, expected):
    """A note is prepended as its own line (created when the turn was tool-calls-only); no choices means nothing to decorate; footers go after."""
    completion = {"choices": [{"message": {"role": "assistant", "content": existing}}]}
    server._prepend_content_line(completion, line)
    assert completion["choices"][0]["message"]["content"] == expected
    bare = {"choices": []}
    server._prepend_content_line(bare, line)
    server._append_content_line(bare, line)
    assert bare == {"choices": []}
    footer = {"choices": [{"message": {"content": "answer"}}]}
    server._append_content_line(footer, "stats")
    assert footer["choices"][0]["message"]["content"].startswith("answer") and footer["choices"][0]["message"]["content"].endswith("stats")
    created = {"choices": [{}]}
    server._append_content_line(created, "stats")
    assert created["choices"][0]["message"]["content"] == "stats"


def test_the_session_workspace_is_remembered_across_a_compaction_turn_and_never_cria_own_dir():
    """The first turn advertises <cwd>; the later summary turn does not and must still resolve to it; '.' is refused; an unknown session stays None."""
    ad = [{"role": "user", "content": "<environment_context><cwd>/work/app</cwd></environment_context> build it"}]
    assert server._session_cwd("sid:cwd-test", ad) == "/work/app"
    assert server._session_cwd("sid:cwd-test", [{"role": "user", "content": "summarize"}]) == "/work/app"
    dot = [{"role": "user", "content": "<environment_context><cwd>.</cwd></environment_context>"}]
    assert server._session_cwd("sid:cwd-dot", dot) is None
    assert server._session_cwd("sid:cwd-never", []) is None
    assert server._remember_session_cwd("sid:cwd-never", ".") == "." and server._session_cwd("sid:cwd-never", []) is None
    assert server._remember_session_cwd("sid:cwd-never", "/w2") == "/w2" and server._session_cwd("sid:cwd-never", []) == "/w2"


def test_the_proxy_body_drops_the_harness_persona_but_keeps_caller_instructions():
    """An aux call keeps only user turns and caller-authority system text; a body with nothing to strip is the same object; a non-list messages passes through."""
    from cria import bodykeys
    persona = {"role": "system", "content": "You are Codex"}
    caller = {"role": "system", "content": "sandbox rules", bodykeys.CALLER_INSTRUCTIONS: True}
    user = {"role": "user", "content": "title?"}
    stripped = server._proxy_body({"model": "m", "messages": [persona, {"role": "developer", "content": "dev"}, caller, user]})
    assert stripped["messages"] == [caller, user] and stripped["model"] == "m"
    clean = {"messages": [user]}
    assert server._proxy_body(clean) is clean and server._proxy_body({"messages": "x"} ) == {"messages": "x"}


class Headers(dict):
    pass


@pytest.mark.parametrize("headers, messages, key", [
    ({"X-Cria-Session-Id": "abc"}, [], "sid:abc"),
    ({"X-Cria-Session-Id": ""}, [{"role": "user", "content": "task one"}], None),
    (None, [], "task:none"),
])
def test_session_identity_prefers_the_header_and_otherwise_keys_on_the_task_root(headers, messages, key):
    """Header wins; an empty header falls back to the task root (stable across a changed later turn, different for a different task); nothing at all is task:none."""
    got = session_key(headers, messages)
    if key is not None:
        assert got == key
        return
    assert got.startswith("task:") and got != "task:none"
    longer = messages + [{"role": "assistant", "content": "ok"}, {"role": "user", "content": "follow-up"}]
    assert session_key(headers, longer) == got and session_key(headers, [{"role": "user", "content": "task two"}]) != got


def test_responses_session_identity_is_the_prompt_cache_key():
    """Codex's prompt_cache_key correlates a conversation; absent or empty means no identity (the caller derives one from the task)."""
    assert responses.session_key_of({"prompt_cache_key": "k-1"}) == "k-1" and responses.session_key_of({"prompt_cache_key": 42}) == "42"
    assert responses.session_key_of({}) is None and responses.session_key_of({"prompt_cache_key": ""}) is None
