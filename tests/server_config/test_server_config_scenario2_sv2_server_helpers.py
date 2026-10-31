"""Server-side helpers on their real inputs: which web calls the conversation still shows (refused ones never ran), the ⟦cria⟧ line placement in completions, the proxy body's persona stripping and the Responses session identity."""
import json

import pytest

from cria import responses, server


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


def test_responses_session_identity_is_the_prompt_cache_key():
    """Codex's prompt_cache_key correlates a conversation; absent or empty means no identity (the caller derives one from the task)."""
    assert responses.session_key_of({"prompt_cache_key": "k-1"}) == "k-1" and responses.session_key_of({"prompt_cache_key": 42}) == "42"
    assert responses.session_key_of({}) is None and responses.session_key_of({"prompt_cache_key": ""}) is None
