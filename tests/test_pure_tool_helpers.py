"""Direct expectations for dependency-closed tool support libraries.

No legacy facade is an oracle: these test literal data, command framing and
payload contracts. Fresh-process checks also block upper imports at runtime.
"""
import ast
from dataclasses import FrozenInstanceError
import hashlib
import json
import shlex
from pathlib import Path
import subprocess
import sys

import pytest

from cria import bodykeys, callformats, callliterals, callsyntax, filecommands
from cria import privatepaths, resultnotes, toolwire


def tool(name, properties, required=None):
    return {"type": "function", "function": {"name": name, "parameters": {
        "type": "object", "properties": properties,
        "required": list(properties) if required is None else required,
    }}}


def test_helper_identity_and_distinct_read_families():
    assert callformats._SHELL_CMD_ALIASES is callsyntax._SHELL_ALIASES
    assert callformats._decode_backslash_escapes is callliterals._decode_backslash_escapes
    assert callformats._wp_read_command is filecommands._read_command
    assert filecommands._refusal_command is toolwire._refusal_command
    assert filecommands.CRIA_HOME is privatepaths.CRIA_HOME
    assert resultnotes.bodykeys is bodykeys
    assert filecommands._READ_NAMES == {"read_file"}
    assert callformats._READ_NAMES == {"read_file", "cat_file", "view_file"}
    assert filecommands._READ_NAMES is not callformats._READ_NAMES


@pytest.mark.parametrize("first", ["callsyntax", "callliterals", "toolwire", "filecommands", "callformats", "resultnotes"])
def test_fresh_imports_and_raw_xml_never_reach_upper_modules(first):
    script = r'''
import importlib, importlib.abc, sys
from types import SimpleNamespace
blocked = {"massage", "writeproxy", "assistruntime", "toolstages", "config",
           "loop", "server", "upstream", "assistfamilies", "argumentconversion",
           "outputpolicies", "outboundpolicies", "returnedpolicies",
           "shrinkprotection", "historyarguments", "probegate", "selfcompact"}
class NoUpper(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith("cria.") and fullname.split(".")[1] in blocked:
            raise AssertionError("upper import: " + fullname)
sys.meta_path.insert(0, NoUpper())
mods = [sys.argv[1], "callsyntax", "callliterals", "toolwire", "filecommands", "callformats", "resultnotes"]
for name in mods:
    importlib.import_module("cria." + name)
from cria import assistbinding, callsyntax, callformats, filecommands, privatepaths, toolwire
calls = []
def forbidden(*args):
    calls.append(args)
    raise AssertionError("pure XML invoked a converter")
selection = SimpleNamespace(definitions=(SimpleNamespace(execute=forbidden),), engagement_level=5)
for selected in (SimpleNamespace(definitions=(), engagement_level=0), selection):
    with assistbinding.bound(selected):
        assert callsyntax._xml_args("<parameter=n>30000</parameter><parameter=flag>true</parameter>") == {"n": "30000", "flag": "true"}
assert calls == []
assert assistbinding.current() is assistbinding.UNBOUND
assert filecommands.CRIA_HOME is privatepaths.CRIA_HOME
assert callformats._wp_read_command is filecommands._read_command
assert filecommands._refusal_command is toolwire._refusal_command
assert not hasattr(toolwire, "write_landed")          # the wording reader is gone: only the typed fact lands a write
assert toolwire.original_call(toolwire._sentinel("write_file", "{}") + "\nx") == {"name": "write_file", "arguments": "{}"}
assert not ({"cria." + n for n in blocked} & sys.modules.keys())
'''
    result = subprocess.run([sys.executable, "-B", "-c", script, first],
                            cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(("body", "expected"), [
    ('<parameter=n>30000</parameter><parameter=flag>true</parameter>', {"n": "30000", "flag": "true"}),
    ('<parameter=content>let x = {"a": 1};</parameter>', {"content": 'let x = {"a": 1};'}),
    ('<parameter=content><project>x</project></function><parameter=summary>done</parameter>',
     {"content": "<project>x</project>", "summary": "done"}),
    ('<parameter=a>first<parameter=b>second</parameter>', {"a": "first", "b": "second"}),
    ('{"n": 30000, "flag": true}', {"n": 30000, "flag": True}),
    ('not an argument object', None),
])
def test_xml_literal_boundaries_and_types(body, expected):
    assert callsyntax._xml_args(body) == expected


def test_nested_xml_value_keeps_balanced_documentation():
    assert callsyntax._bounded_xml_params(
        '<parameter=content>Call <parameter=url>http://x</parameter></parameter>'
    ) == [("content", 'Call <parameter=url>http://x</parameter>'), ("url", "http://x")]


def test_complete_reasoning_frames_and_literal_only_native_calls():
    text = '<|tool_call_start|>[read_file(path="a"), read_file(path="b")]<|tool_call_end|>'
    assert callsyntax._reasoning_call_spans(text) == [
        (0, len(text), "lfm2-native", [("read_file", {"path": "a"}), ("read_file", {"path": "b"})])]
    assert callsyntax._reasoning_call_spans(text.removesuffix('<|tool_call_end|>')) == []
    assert callsyntax._lfm2_native_calls('[read_file(path=unknown)]') is None
    assert callsyntax._lfm2_native_calls('[read_file(path=str("a"))]') is None


def test_gemma_payload_punctuation_and_nested_values_survive():
    text = 'before <|tool_call>call:write_file{path:<|"|>a.py<|"|>,content:<|"|>{x}, "q"\nnext<|"|>,opts:{n:3,ok:true}}<tool_call|> after'
    calls, remaining = callsyntax._extract_gemma(text)
    assert remaining == "before  after"
    assert len(calls) == 1
    assert json.loads(calls[0]["function"]["arguments"]) == {
        "path": "a.py", "content": '{x}, "q"\nnext', "opts": {"n": 3, "ok": True}}


def test_leading_call_run_stops_before_fabricated_results():
    tools = [tool("read_file", {"path": {"type": "string"}})]
    text = 'read_file({"path":"a"})</tool_call>read_file({"path":"b"}) tool: invented read_file({"path":"c"})'
    calls, rest = callsyntax._call_syntax_calls(text, tools)
    assert [json.loads(c["function"]["arguments"]) for c in calls] == [{"path": "a"}, {"path": "b"}]
    assert rest == ' tool: invented read_file({"path":"c"})'
    assert callsyntax._call_syntax_calls('Prose ' + text, tools) == ([], 'Prose ' + text)
    assert callsyntax._call_syntax_calls(text, []) == ([], text)
    for args in ('{"path":null}', '{"path":"a","extra":1}', '{}'):
        bad = 'read_file(' + args + ')'
        assert callsyntax._call_syntax_calls(bad, tools) == ([], bad)


def test_envelopes_use_menu_shapes_without_schema_coercion():
    tools = [tool("exec_command", {"cmd": {"type": "string"}})]
    calls = callsyntax._envelope_calls('{"commands":[{"name":"exec_command","arguments":"  echo ok  "}]}', tools)
    assert calls == [{"id": "env_0", "type": "function", "function": {
        "name": "exec_command", "arguments": '{"cmd": "echo ok"}'}}]
    assert callsyntax._envelope_calls('{"calls":[{"name":"absent","arguments":{}}]}', tools) == []
    assert callsyntax._fenced_envelope('{"action":"read_file","parameters":{"path":"a"}}') == ("read_file", {"path": "a"})
    assert callsyntax._fenced_envelope('{"name":"read_file","arguments":{},"description":"schema"}') is None


def test_fences_paths_and_menu_derived_write_fields():
    text = 'Update `src/a.py`:\n```python\none\n```\n'
    blocks = callsyntax.fenced_file_blocks(text)
    assert blocks == [{"lang": "python", "lines": ["one"], "closed": True,
                       "start": len('Update `src/a.py`:\n'), "binding": 'Update `src/a.py`:'}]
    assert callsyntax.binding_paths(blocks[0]["binding"]) == ["src/a.py"]
    assert not callsyntax.fenced_file_blocks(text.removesuffix('```\n'))[0]["closed"]
    tools = [tool("write_file", {"file_path": {"type": "string"}, "contents": {"type": "string"}})]
    call = callsyntax.whole_file_write_call(tools, "a.py", "one\n")
    assert json.loads(call["function"]["arguments"]) == {"file_path": "a.py", "contents": "one\n"}
    tools[0]["function"]["parameters"]["properties"]["overwrite"] = {"type": "boolean"}
    assert callsyntax.whole_file_write_call(tools, "a.py", "one") is None


@pytest.mark.parametrize(("raw", "args", "discarded"), [
    ('{"cmd":"ok"}<tool_call|>tail', {"cmd": "ok"}, len('<tool_call|>tail')),
    (r'{\"cmd\":\"ok\"}<tool_call|>tail', {"cmd": "ok"}, len('<tool_call|>tail')),
    ('broken<tool_call|>tail', None, len('<tool_call|>tail')),
    ('{"cmd":"ok"}', None, None),
    ('[1]<tool_call|>tail', None, len('<tool_call|>tail')),
])
def test_fused_measurement_is_explicit_per_parse(raw, args, discarded):
    result = callliterals.recover_fused_call(raw)
    assert result.arguments == args
    assert result.discarded_chars == discarded
    with pytest.raises(FrozenInstanceError):
        result.discarded_chars = 1
    callliterals.recover_fused_call('different<tool_call|>suffix')
    assert result.arguments == args and result.discarded_chars == discarded


@pytest.mark.parametrize(("raw", "expected"), [
    ('{"path":"a.py","content":"one\ntwo\n"}', {"path": "a.py", "content": "one\ntwo\n"}),
    ('{"file_path":"a.py","contents":"one\\ntwo"}', {"path": "a.py", "content": "one\ntwo"}),
    ('{"path":"a.py","content":"unterminated', None),
    ('{"path":"a.py","content":"ok"', None),
])
def test_complete_write_recovery_never_invents_a_missing_closer(raw, expected):
    assert callliterals._recover_write_args(raw) == expected


def test_escape_and_tail_readers_preserve_real_document_content():
    assert callliterals._repair_double_escaped(r'a\nb\q') == 'a\nb\\q'
    assert callliterals._repair_double_escaped('a\n' + r'b\n') == 'a\n' + r'b\n'
    pom = '<project>\n<parameter>Main-Class=app.Main</parameter>\n</project>\n'
    assert callliterals.trim_fused_tail(pom) == pom
    assert not callliterals._protocol_debris(pom)
    assert callliterals._has_tc_debris('{"cmd":"x"}<tool_call|>')
    assert not callliterals._has_tc_debris(None)


def test_refusal_and_oversize_bytes_and_survey_placement():
    assert toolwire._oversize_command("too big") == "printf %s '⟦ctx:denied⟧ too big'"
    assert toolwire._refusal_command("no") == "printf %s '⟦ctx:denied⟧ no'; exit 1"
    survey = "python3 - <<'END'\nprint('survey')\nEND"
    assert toolwire._refusal_command("no", survey) == "printf %s '⟦ctx:denied⟧ no'\n" + survey + "\nexit 1"
    assert toolwire._refusal_command("it's blocked") == "printf %s '⟦ctx:denied⟧ it'\"'\"'s blocked'; exit 1"


def test_original_call_preserves_argument_bytes_and_shell_identity():
    arguments = ' { "content": "é\\n", "path": "a" } '
    sentinel = toolwire._sentinel("write_file", arguments)
    assert toolwire.original_call(sentinel + '\nprintf anything') == {"name": "write_file", "arguments": arguments}
    assert toolwire.original_call('# ⟦ctx:tool⟧not-base64') is None
    assert toolwire.is_crias_own(sentinel)
    import base64
    gate = '# ' + toolwire.GATE_SENTINEL + base64.b64encode(json.dumps(["rake test"]).encode()).decode()
    assert toolwire.is_crias_own(gate + '\nrake test')
    assert not toolwire.is_crias_own('# ' + toolwire.GATE_SENTINEL)             # a bare marker declares nothing
    assert not toolwire.is_crias_own('printf user')
    # THE DECLARATION IS THE LEADING LINE: a native command that merely quotes a valid header owns nothing.
    assert not toolwire.is_crias_own(f"s={shlex.quote(sentinel)}; echo hi") and toolwire.original_call(f"s={shlex.quote(sentinel)}") is None
    assert not toolwire.is_crias_own("echo " + gate) and not toolwire.is_crias_own("\n" + sentinel)
    shell = {"name": "exec_command", "schema": {"properties": {"cmd": {"type": "string"}}}}
    result = toolwire._shell_call('original-id', shell, 'printf "é"')
    assert result["id"] == 'original-id'
    assert result["function"]["name"] == "exec_command"
    assert json.loads(result["function"]["arguments"]) == {"cmd": 'printf "é"'}


@pytest.mark.parametrize(("name", "args", "fields"), [
    ('write_file', {"path": "a", "content": ""}, {"content": "", "error": ""}),
    ('write_file', {"path": "a", "content": None, "contents": 0}, {"content": "0", "error": ""}),
    ('write_file', {"path": "a", "content": False}, {"content": "False", "error": ""}),
    ('write_file', {"path": "a"}, {"error": "content"}),
    ('edit_file', {"path": "a", "old_string": "", "new_string": "x"}, {"error": "empty_old_string"}),
    ('edit_file', {"path": "a", "old_string": "x", "new_string": ""}, {"new": "", "error": ""}),
    ('edit_file', {"path": "a", "old_string": "x"}, {"error": "new_string"}),
    ('write_file', {"content": "x"}, {"error": "path"}),
])
def test_mutation_preparation_distinguishes_missing_empty_and_falsy(name, args, fields):
    prepared = filecommands._prepare_file_mutation(name, args)
    for key, expected in fields.items():
        assert getattr(prepared, key) == expected


def test_spill_paths_are_explicit_and_root_rewrite_is_narrow():
    directory = './tmp/custom-reference'
    assert filecommands._under_spill_dir('/workspace/tmp/custom-reference/a', directory)
    assert not filecommands._under_spill_dir('/workspace/tmp/other/a', directory)
    assert filecommands._spill_relpath('/tmp/custom-reference/a', directory) == './tmp/custom-reference/a'
    assert filecommands._spill_relpath('/workspace/tmp/custom-reference/a', directory) is None
    assert filecommands._respill_command('cat /tmp/custom-reference/a /workspace/tmp/custom-reference/b', directory) == 'cat ./tmp/custom-reference/a /workspace/tmp/custom-reference/b'
    assert filecommands._targets_cria_home(str(privatepaths.CRIA_HOME / 'logs/a'))
    assert not filecommands._targets_cria_home('.cria/logs/a')


def test_read_builders_preserve_quoted_paths_and_explicit_spill_guidance(tmp_path):
    assert filecommands._read_command({}) is None
    command = filecommands._read_command({"path": "a b"})
    assert "python3 - 'a b' " in command
    assert "else cat" not in command
    assert "__CRIA_READ_WINDOW__" in command
    ranged = filecommands._read_command({"path": "a b", "end_line": 2})
    assert "python3 - 'a b' 1 2 -1" in ranged
    assert callformats._read_command({"path": "a b", "start": "1", "end": "2"}) == ranged
    spill = filecommands._spill_read_command('a b', "caller supplied outline")
    assert "⟦ctx:denied⟧ caller supplied outline" in spill
    assert "python3 - 'a b' " in spill
    assert "__CRIA_RD_PY__" in spill and "else cat" not in spill
    unread = filecommands._read_in_place_of_write('a b', 'authoritative fact')
    import subprocess
    (tmp_path / 'a b').write_text('exact source bytes')
    result = subprocess.run(['bash', '-c', unread], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0 and not result.stderr
    assert '⟦ctx:read-instead⟧' in result.stdout and 'authoritative fact' in result.stdout
    assert result.stdout.endswith('exact source bytes')


def test_patch_and_command_shapes_are_literal():
    assert callformats._command_string([["bash", "-lc", "printf ok"]]) == "printf ok"
    assert callformats._command_string(["python3", "-m", "pytest"]) == "python3 -m pytest"
    assert callformats._canonical_name_map([tool("EditFile", {}), tool("edit_file", {})]) == {"editfile": None}
    assert callformats._edit_to_patch('a', 'old', 'new\n') == '*** Begin Patch\n*** Update File: a\n-old\n+new\n+\n*** End Patch'
    assert callformats._pure_add_file('*** Begin Patch\n*** Add File: a\n+x\n*** End Patch') == ('a', 'x')
    assert callformats._pure_add_file('*** Add File: a\n+x\n*** Add File: b\n+y') is None
    unified = '--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-old\n+new\n'
    assert callformats._normalize_patch_body(unified) == '*** Begin Patch\n*** Update File: a.txt\n-old\n+new\n*** End Patch'


def test_payload_boundary_is_authoritative_and_never_recounts_notes():
    message = {"role": "tool", "content": "payload é"}
    resultnotes.append_note(message, "first")
    boundary = message[bodykeys.PAYLOAD_BOUNDARY]
    assert boundary == (len("payload é"), hashlib.sha1("payload é".encode()).hexdigest())
    assert resultnotes.payload_of(message, message["content"]) == "payload é"
    resultnotes.append_note(message, "second")
    assert message[bodykeys.PAYLOAD_BOUNDARY] is boundary
    assert message["content"] == "payload é\n\nfirst\n\nsecond"
    assert resultnotes.payload_of(message, message["content"]) == "payload é"
    assert resultnotes.payload_of(message, "changed" + message["content"]) is None
    assert resultnotes.payload_of({}, "plain") == "plain"
    copied = resultnotes._noted({"content": "unmodified"}, "actual", "note")
    assert copied["content"] == "actual\n\nnote"
    assert resultnotes.payload_of(copied, copied["content"]) == "actual"


def test_execution_envelope_removal_keeps_real_payload_and_eof():
    wrapped = 'Chunk ID: abc\nWall time: 0.1 seconds\nProcess exited with code 0\nOutput:\nactual\n'
    assert resultnotes._strip_exec_envelope(wrapped) == 'actual\n'
    assert resultnotes._strip_exec_envelope(wrapped, preserve_eof=True) == 'actual\n'
    assert resultnotes._strip_exec_envelope('actual\n', preserve_eof=True) == 'actual\n'
    assert resultnotes._workspace_ecosystem(None) == ''
    assert resultnotes.probegate_marker_in('___CRIA_GATE_checks')


def test_explicit_import_closure_including_deferred_imports():
    root = Path(__file__).resolve().parents[1]
    blocked = {"cria." + name for name in (
        "massage", "writeproxy", "assistruntime", "toolstages", "config",
        "loop", "server", "upstream", "assistfamilies", "argumentconversion",
        "outputpolicies", "outboundpolicies", "returnedpolicies",
        "shrinkprotection", "historyarguments", "probegate", "selfcompact",
    )}
    pending = [("cria." + name,) for name in (
        "callsyntax", "callliterals", "toolwire", "filecommands", "callformats", "resultnotes")]
    visited = set()
    while pending:
        chain = pending.pop()
        module = chain[-1]
        assert module not in blocked, " -> ".join(chain)
        if module in visited:
            continue
        visited.add(module)
        path = root.joinpath(*module.split('.')).with_suffix('.py')
        if not path.is_file():
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            targets = []
            if isinstance(node, ast.ImportFrom):
                base = module.split('.')[:-node.level] if node.level else []
                base += node.module.split('.') if node.module else []
                targets.append('.'.join(base))
                targets.extend('.'.join(base + [alias.name]) for alias in node.names)
            elif isinstance(node, ast.Import):
                targets.extend(alias.name for alias in node.names)
            pending.extend(chain + (target,) for target in targets if target.startswith('cria.'))


def test_fused_tail_measurement_uses_first_sentinel_and_character_offsets():
    raw = '{"cmd":"é"}<tool_call|>α<|channel>β'
    result = callliterals.recover_fused_call(raw)
    assert result.arguments == {"cmd": "é"}
    assert result.discarded_chars == len('<tool_call|>α<|channel>β')
    assert result.discarded_chars != len('<tool_call|>α<|channel>β'.encode())
    assert callliterals.recover_fused_call('no sentinel').discarded_chars is None


def test_tail_trimming_cuts_only_protocol_suffix_and_keeps_existing_scan_bound():
    original = '<project>\n  <name>actual</name>\n</project>\n'
    fused = original + '</function>\n</tool_call>\n<function=exec_command>\n<parameter=cmd>\nmvn -q compile\n'
    assert callliterals.trim_fused_tail(fused) == original
    far_tag = 'start\n<function=example>\n' + 'real source\n' * 41
    assert callliterals.trim_fused_tail(far_tag) == far_tag
    assert callliterals._protocol_debris('</function>\n</tool_call>')
    assert callliterals.trim_fused_tail('</function>\n</tool_call>') == '</function>\n</tool_call>'


@pytest.mark.parametrize(("raw", "incomplete"), [
    ('{"cmd":"ok"}', False),
    ('{"cmd":"unfinished', True),
    ('{"cmd":"ok"}\ntrailing', True),
])
def test_incomplete_arguments_are_facts_not_recovery_or_execution(raw, incomplete):
    completion = {"choices": [{"message": {"tool_calls": [{"function": {
        "name": "exec_command", "arguments": raw}}]}}]}
    before = json.dumps(completion)
    assert callliterals.has_incomplete_tool_args(completion) is incomplete
    assert json.dumps(completion) == before


@pytest.mark.parametrize(("schema", "expected"), [
    ({"properties": {"cmd": {"type": "string"}}}, {"cmd": "printf ok"}),
    ({"properties": {"command": {"type": "array"}}}, {"command": ["bash", "-lc", "printf ok"]}),
    ({"properties": {"command": {}, "cmd": {}}, "required": ["cmd"]}, {"cmd": "printf ok"}),
])
def test_shell_wire_uses_exact_declared_field_and_type(schema, expected):
    call = toolwire._shell_call('id', {"name": "shell", "schema": schema}, "printf ok")
    assert json.loads(call["function"]["arguments"]) == expected
    assert toolwire._command_of(call["function"]["arguments"]) == "printf ok"


def test_tool_call_constructor_keeps_valid_raw_argument_bytes_and_generates_ids():
    raw = ' { "n": 1 } '
    first = callsyntax._toolcall('f', raw)
    second = callsyntax._toolcall('f', raw)
    assert first['function'] == {"name": "f", "arguments": raw}
    assert first['id'].startswith('call_') and len(first['id']) == 21
    assert first['id'] != second['id']


def test_completion_finish_facts_and_content_readers():
    mixed = {"choices": [{"finish_reason": "stop"}, {"finish_reason": "length"}]}
    assert callsyntax.is_truncated(mixed)
    assert not callsyntax.is_ruminating(mixed)
    assert callsyntax.is_ruminating({"choices": [{"finish_reason": "rumination"}]})
    assert callsyntax.content_text([{"type": "text", "text": "one"}, {"type": "image_url", "image_url": {}}, {"type": "text", "text": "two"}]) == 'one  two'
    assert callsyntax.turn_text({"content": "actual", "reasoning_content": "thought"}) == 'actual'
    assert callsyntax.turn_text({"content": "", "reasoning_content": " thought "}) == 'thought'


@pytest.mark.parametrize('text', ['Wrote a.py', '⟦ctx:wrote⟧', 'raw ⟦ctx:wrote⟧ anywhere', 'Wrote', ''])
def test_wording_never_lands_a_write_only_the_typed_fact_does(text):
    """The confirmation wording (rendered or raw) is text any file, command or page can quote. A write landed ONLY when its own
    program said so in its typed first record, and `represent_inbound` stamped that proven outcome on the message."""
    from cria import bodykeys, denial
    plain = {'role': 'tool', 'tool_call_id': 'c', 'content': text}
    assert not denial.landed(plain)
    assert denial.landed({**plain, bodykeys.RESULT_OUTCOME: denial.LANDED})
    assert not denial.landed({**plain, bodykeys.RESULT_OUTCOME: denial.REFUSED})
    call = {'id': 'c', 'type': 'function', 'function': {'name': 'write_file', 'arguments': '{}'}}
    assert denial.landed_call_ids([{'role': 'assistant', 'tool_calls': [call]}, plain]) == set()
    assert denial.landed_call_ids([{'role': 'assistant', 'tool_calls': [call]},
                                   {**plain, bodykeys.RESULT_OUTCOME: denial.LANDED}]) == {'c'}


def test_a_landed_fact_is_dropped_for_an_ambiguous_pairing():
    from cria import bodykeys, denial
    call = {'id': 'c', 'type': 'function', 'function': {'name': 'write_file', 'arguments': '{}'}}
    landed = {'role': 'tool', 'tool_call_id': 'c', 'content': 'x', bodykeys.RESULT_OUTCOME: denial.LANDED}
    assert denial.landed_call_ids([{'role': 'assistant', 'tool_calls': [call]}, landed, landed]) == set()


def test_new_spill_apis_require_explicit_inputs():
    for fn in (filecommands._under_spill_dir, filecommands._spill_relpath,
               filecommands._respill_command, filecommands._spill_read_command):
        with pytest.raises(TypeError):
            fn('path')
