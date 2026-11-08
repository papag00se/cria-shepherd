import copy
import json

from cria import classify, config, planner, responses, upstream


class Log:
    phase = "coder-s1"
    session = None

    def emit(self, *args, **kwargs):
        pass


def wire(messages, phase="coder-s1", level=config.MAX_ENGAGEMENT_LEVEL):
    log = Log()
    log.phase = phase
    up = upstream.Upstream("http://unused", context_window=49152, engagement_level=level)
    data, _, _ = up._prep({"model": "m", "messages": messages}, False, log)
    return json.loads(data)["messages"]


def test_responses_environment_to_coder_wire_keeps_permissions_and_raw_context():
    xml = ('<environment_context><cwd>/work</cwd><shell>bash</shell>'
           '<current_date>2026-11-08</current_date><timezone>America/Los_Angeles</timezone>'
           '<filesystem><workspace_roots><root>/work</root></workspace_roots>'
           '<permission_profile type="managed"><file_system type="restricted">'
           '<entry access="read"><path>/</path></entry>'
           '<entry access="write"><path>/install</path></entry>'
           '<entry access="write"><path>/work</path></entry>'
           '</file_system></permission_profile></filesystem></environment_context>')
    request = {"model": "m", "input": [
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": xml}]},
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Fix the project"}]},
    ]}
    body = responses.to_chat_body(request)
    original = copy.deepcopy(body["messages"])
    sent = wire(body["messages"])
    assert sent[0]["content"] == ('# Environment context\n'
        '- cwd: `/work`\n- shell: `bash`\n- current_date: `2026-11-08`\n'
        '- timezone: `America/Los_Angeles`\n- filesystem workspace_roots:\n'
        '  - `/work`\n- permission_profile type: `managed`\n'
        '- file_system type: `restricted`\n- file_system entries (access, path):\n'
        '  - `read`: `/`\n  - `write`: `/install`\n  - `write`: `/work`')
    assert body["messages"] == original
    assert classify.latest_user_text(body["messages"]) == "Fix the project"
    assert planner._extract_cwd(body["messages"]) == "/work"
    assert wire(body["messages"], phase="classifier") == original
    assert wire(body["messages"], level=0) == original


def test_untrusted_prose_other_roles_and_unsafe_xml_are_not_rewritten():
    cases = [
        "Explain <environment_context><cwd>/work</cwd></environment_context>",
        "<environment_context><cwd>/work</cwd></environment_context><environment_context/>",
        "<environment_context><cwd>/work</environment_context>",
        "<environment_context>before<cwd>/work</cwd>after</environment_context>",
        '<!DOCTYPE environment_context [<!ENTITY e "x">]><environment_context>&e;</environment_context>',
        '<environment_context xmlns="urn:example"><cwd>/work</cwd></environment_context>',
        '<environment_context><!-- keep this --><cwd>/work</cwd></environment_context>',
        '<environment_context><future xml:space="preserve">  <child/>  </future></environment_context>',
        '<environment_context><future> <child/> </future></environment_context>',
    ]
    for value in cases:
        messages = [{"role": "user", "content": value}]
        assert wire(messages) == messages
    xml = "<environment_context><cwd>/work</cwd></environment_context>"
    for role in ("assistant", "system"):
        messages = [{"role": role, "content": xml}]
        assert wire(messages) == messages
    # A tool result whose call vanished is re-roled as user evidence at the wire;
    # that repair must not turn tool output into an environment packet.
    result = wire([{"role": "tool", "tool_call_id": "missing", "content": xml}])
    assert result == [{"role": "user", "content": xml}]


def test_compact_preserves_root_and_permission_order_and_escaped_values():
    xml = ('<environment_context><cwd>/work&amp;more</cwd><shell>bash</shell>'
           '<current_date>2026-01-01</current_date><timezone>UTC</timezone>'
           '<filesystem><workspace_roots><root>/work&amp;more</root><root>/other</root></workspace_roots>'
           '<permission_profile type="managed"><file_system type="restricted">'
           '<entry access="write"><path>/first</path></entry><entry access="read"><path>/</path></entry>'
           '<entry access="write"><path>/second</path></entry>'
           '</file_system></permission_profile></filesystem></environment_context>')
    rendered = wire([{"role": "user", "content": xml}])[0]["content"]
    assert '- cwd: `/work&more`' in rendered
    assert '- filesystem workspace_roots:\n  - `/work&more`\n  - `/other`' in rendered
    assert '- file_system entries (access, path):\n  - `write`: `/first`\n  - `read`: `/`\n  - `write`: `/second`' in rendered
    extended = xml.replace('</filesystem>', '<extension>important</extension></filesystem>')
    assert '- `extension`: `"important"`' in wire([{"role": "user", "content": extended}])[0]["content"]
    for ref in ('&#32;', '&#x20;', '&#0009;', '&#x000A;', '\u00a0', '&#160;', '&#x2003;', '&amp;'):
        meaningful = xml.replace('<filesystem><workspace_roots>', '<filesystem>' + ref + '<workspace_roots>')
        assert wire([{"role": "user", "content": meaningful}])[0]["content"] == meaningful
    spaced = xml.replace('/work&amp;more', '/work&#32;more')
    assert '- cwd: `/work more`' in wire([{"role": "user", "content": spaced}])[0]["content"]


def test_unknown_elements_escaping_and_duplicate_entries_remain_explicit():
    xml = '<environment_context><future a="&quot;&amp;">x &amp; y</future><future>two</future></environment_context>'
    rendered = wire([{"role": "user", "content": xml}])[0]["content"]
    assert rendered == '# Environment context\n- `future` `a="\\\"&"`: `"x & y"`\n- `future`: `"two"`'
