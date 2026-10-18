"""Canonical pure helpers have one owner; legacy facades expose the same objects."""
import ast
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import runpy

import pytest

from cria import callformats, callliterals, callsyntax, filecommands, massage, probegate, resultnotes, toolwire, writeproxy
from cria import outputpolicies, outboundpolicies


MASSAGE_EXPORTS = {
    callsyntax: '''_SHELL_ALIASES _HERMES _XML_FN _GEMMA_TC_OPEN _GEMMA_TC_CLOSE _GEMMA_STR
        _LFM2_TC_OPEN _LFM2_TC_CLOSE _LEAK_DEBRIS has_tool_call_leak _has_tool _tool_names
        is_truncated is_ruminating _menu_schemas _sole_required _envelope_calls _CALL_SYNTAX_OPEN
        _CALL_SYNTAX_TERM _skip_between_calls _call_syntax_calls _FENCED_BLOCK _envelope_pair
        _fenced_envelope fenced_file_blocks _PATH_TOKEN _URL binding_paths has_call_envelope
        whole_file_write_call content_text turn_text _TAG_TOKEN _FENCE _is_terminal _is_quoted
        _literal_kwargs _lfm2_native_calls _WORDS_BETWEEN_CALLS _reasoning_call_spans _PARAM_OPEN
        _PARAM_CLOSE _PARAM_HARD_BOUNDARIES _bounded_xml_params _xml_args _outermost _menu_admits
        _CHANNEL _CHANNEL_FABLE _strip_channel _strip_delimited _strip_lfm2_sentinels _extract_gemma
        _parse_gemma_call _gemma_object _gemma_array _gemma_value _gemma_scalar _alias
        _LEAK_MARKERS _toolcall'''.split(),
    callformats: '''_edit_to_patch _SHELL_CMD_ALIASES _READ_NAMES _EXEC_NAMES _BASH_HEADS _canon_key
        _canonical_name_map _command_string _alias_command _read_command _pure_add_file _HUNK
        _normalize_patch_body _collapse_wrappers _strip_ab _unified_to_native _repair_hunk_headers _fix_hunk_lines'''.split(),
    callliterals: '''_FUSED_SENTINELS _PATH_RE _CONTENT_RE _json_structurally_complete _recover_write_args
        _content_value_end _unescape_once _MUTATION_TOOLS _content_truncated has_incomplete_tool_args'''.split(),
}
WRITE_EXPORTS = {
    callliterals: '''_FUSED_TAIL_MAX_LINES _PROTOCOL_TAG_LINE _protocol_debris trim_fused_tail
        _TC_DEBRIS _has_tc_debris _ESCAPES _repair_double_escaped _decode_backslash_escapes'''.split(),
    filecommands: '''_WRITE_NAMES _EDIT_NAMES _READ_NAMES _LIST_NAMES _FileMutation _prepare_file_mutation
        _targets_cria_home _guarded_path READ_INLINE_MAX _ranged_read _read_failure_branches
        _read_command _read_in_place_of_write'''.split(),
    toolwire: '''REFUSED_EXIT_CODE _oversize_command _refusal_command _SENTINEL _SENTINEL_LINE
        _WROTE _sentinel _shell_call _b64 REMOVAL_FACTS _RIDE_ALONG_HOST_RESERVE
        _RIDE_ALONG_COMMAND_RESERVE _command_of is_crias_own original_call _read_sentinel GATE_SENTINEL'''.split(),
    resultnotes: '''_ENVELOPE_OUTPUT_LINE _ENVELOPE_ADVISORY _ENVELOPE_CUT_WARNING _EXIT_CODE
        _strip_exec_envelope _noted _digest append_note payload_of _workspace_ecosystem probegate_marker_in'''.split(),
}
SOURCE_ALIASES = [(massage, outputpolicies, name) for name in (
    '_extract_leaked', '_fenced_envelope_call', '_echoes_a_draft', '_to_shell', '_reshape_shell', '_log',
    '_TEXT_FENCE_TAGS', '_ECHO_FLOOR')] + [(writeproxy, outboundpolicies, '_spill_read_command')]


@pytest.mark.parametrize('facade,owner,name', SOURCE_ALIASES)
def test_source_orchestration_has_one_canonical_owner(facade, owner, name):
    assert getattr(facade, name) is getattr(owner, name)
    declarations = ast.parse(Path(facade.__file__).read_text()).body
    assert not any((isinstance(n, ast.FunctionDef) and n.name == name) or
                   (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))
                   for n in declarations)


def test_public_json_reader_is_the_canonical_helper_and_preserves_literal_values():
    from cria import jsontext
    assert massage.extract_json_object is jsontext.extract_json_object
    assert massage.extract_json_object('before {"text":"雪\\\\n","nested":{"n":7}} after') == {
        'text': '雪\\n', 'nested': {'n': 7}}
    assert massage.extract_json_object('no object here') is None


def test_legacy_fused_view_delegates_once_without_shared_measurement_state(monkeypatch):
    calls = []
    def parser(raw):
        calls.append(raw)
        return callliterals.FusedCall({'actual': raw}, 42)
    monkeypatch.setattr(callliterals, 'recover_fused_call', parser)
    assert massage._recover_fused_call('raw') == {'actual': 'raw'}
    assert calls == ['raw']
    assert not hasattr(massage, '_LAST_FUSED_TAIL')


@pytest.mark.parametrize('mode', ['replacement', 'disabled', 'empty'])
def test_legacy_promotion_bridge_runs_only_actual_selected_repairs_and_preserves_choices(mode):
    from cria import assistruntime
    calls = []
    original = outputpolicies.REPAIR[0]
    def repair_stage(completion, log=None):
        calls.append(completion['choices'][0]['message']['tool_calls'][0])
        return completion
    replacement = replace(original, execute=repair_stage)
    registry = tuple(replacement if d.policy.id == original.policy.id else d
                     for d in assistruntime.DEFINITIONS)
    disabled = ((original.policy.id,) if mode == 'disabled' else
                tuple(d.policy.id for d in registry if d.policy.default_level == 0) if mode == 'empty' else ())
    selected = assistruntime.AssistRuntime.select(registrations=registry,
        level=0 if mode == 'empty' else 5, disabled=disabled)
    untouched = {'index': 1, 'message': {'role': 'assistant', 'content': 'unchanged second choice'}, 'finish_reason': 'stop'}
    completion = {'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': 'file prose'},
                               'finish_reason': 'stop'}, untouched]}
    call = callsyntax._toolcall('sample', {'value': 7})
    with assistruntime.bound(selected):
        result = massage.promote_call(completion, call, 'keep', [])
        assert result['choices'][0]['message']['tool_calls'] == [call]
        assert result['choices'][0]['message']['content'] == 'keep'
        assert result['choices'][0]['finish_reason'] == 'tool_calls'
        assert result['choices'][1] == untouched
        assert calls == ([call] if mode == 'replacement' else [])
        cut = {'choices': [{'message': {'content': 'partial'}, 'finish_reason': 'length'}]}
        assert massage.promote_call(cut, call, '', []) is cut
        assert cut['choices'][0]['message'] == {'content': 'partial'}
        assert calls == ([call] if mode == 'replacement' else [])


CASES = [(facade, owner, name) for facade, groups in ((massage, MASSAGE_EXPORTS), (writeproxy, WRITE_EXPORTS))
         for owner, names in groups.items() for name in names]


@pytest.mark.parametrize('facade,owner,name', CASES, ids=[f'{f.__name__}.{n}' for f, _, n in CASES])
def test_public_compatibility_names_are_canonical_objects(facade, owner, name):
    assert getattr(facade, name) is getattr(owner, name)


def test_no_moved_body_or_constant_is_redeclared_in_either_facade():
    for facade, groups in ((massage, MASSAGE_EXPORTS), (writeproxy, WRITE_EXPORTS)):
        names = {name for group in groups.values() for name in group}
        redeclared = set()
        for node in ast.parse(Path(facade.__file__).read_text()).body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                redeclared.add(node.name)
            elif isinstance(node, ast.Assign):
                redeclared.update(target.id for target in node.targets if isinstance(target, ast.Name))
        assert not names & redeclared, (facade.__name__, sorted(names & redeclared))


def test_whole_graph_also_counts_absolute_package_imports_at_every_depth():
    # The authoritative collector includes absolute imports; no parallel scorer here.
    guard = runpy.run_path(str(Path(__file__).with_name('test_the_import_graph_has_no_cycles.py')))
    assert guard['cycles'](guard['import_graph']()) == []


def test_gate_producer_uses_canonical_wire_markers():
    assert probegate.GATE_SENTINEL is toolwire.GATE_SENTINEL
    assert probegate.SECTION_PREFIX is toolwire.SECTION_PREFIX
    tree = ast.parse(Path(probegate.__file__).read_text())
    assert not any(isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in
        ('GATE_SENTINEL', 'SECTION_PREFIX') for t in n.targets) for n in tree.body)


def test_paired_write_confirmation_has_one_lower_owner_and_gate_keeps_pairing():
    from cria import selfcompact
    assert selfcompact.write_landed is toolwire.write_landed
    assert probegate.write_landed is toolwire.write_landed
    messages = [
        {'role': 'assistant', 'tool_calls': [
            {'id': 'yes', 'function': {'name': 'write_file', 'arguments': '{"path":"src/landed.py"}'}},
            {'id': 'no', 'function': {'name': 'edit_file', 'arguments': '{"path":"src/refused.py"}'}}]},
        {'role': 'tool', 'tool_call_id': 'yes', 'content': 'Wrote src/landed.py'},
        {'role': 'tool', 'tool_call_id': 'no', 'content': 'Nothing was run'},
        {'role': 'tool', 'tool_call_id': 'unknown', 'content': toolwire._WROTE},
    ]
    assert probegate._paths_written_after(messages, -1) == frozenset({'landed.py'})
    assert probegate._paths_written_after(messages, 0) == frozenset()


def test_read_alias_and_synthetic_read_sets_remain_distinct():
    assert massage._READ_NAMES == {'read_file', 'cat_file', 'view_file'}
    assert writeproxy._READ_NAMES == {'read_file'}
    assert massage._READ_NAMES is not writeproxy._READ_NAMES


def test_legacy_spill_adapters_pass_real_context_and_preserve_command_bytes(monkeypatch):
    from cria import webfetch, prompts
    monkeypatch.setattr(webfetch, 'SPILL_DIR', './tmp/custom-read-only')
    assert writeproxy._under_spill_dir('./tmp/custom-read-only/a') is True
    assert writeproxy._under_spill_dir('./tmp/read-only/a') is False
    assert writeproxy._spill_relpath('/tmp/custom-read-only/a') == './tmp/custom-read-only/a'
    assert writeproxy._respill_command('cat /tmp/custom-read-only/a') == 'cat ./tmp/custom-read-only/a'
    monkeypatch.setattr(webfetch, 'format_for_spill_path', lambda path: 'JSON')
    monkeypatch.setattr(webfetch, 'spill_reading_hint', lambda path, budget: f'extent {budget}')
    monkeypatch.setattr(webfetch, 'page_not_file_for_spill_path', lambda path: False)
    monkeypatch.setattr(webfetch, 'outline_for_spill_path', lambda path: 'actual outline')
    path = './tmp/custom-read-only/a'
    steer = prompts.render('spill_read_steer', path=path, format=' It is JSON.',
        extent=f' extent {filecommands.READ_INLINE_MAX}\n', outline='actual outline')
    assert writeproxy._spill_read_command(path) == filecommands._spill_read_command(path, steer)


@pytest.mark.parametrize('module', ['discoverypolicy', 'documentguidance', 'externalization'])
def test_catalog_free_projection_keeps_bound_identity_absence_and_nested_restore(module):
    import importlib
    from types import SimpleNamespace
    from cria import assistbinding
    standalone = importlib.import_module('cria.' + module).DEFINITION
    chosen, nested = replace(standalone), replace(standalone)
    assert chosen is not standalone and nested is not chosen
    assert assistbinding.current() is assistbinding.UNBOUND
    assert assistbinding.selected_definition(standalone) is standalone
    with assistbinding.bound(SimpleNamespace(definitions=(chosen,), engagement_level=5)):
        assert assistbinding.selected_definition(standalone) is chosen
        with assistbinding.bound(SimpleNamespace(definitions=(), engagement_level=5)):
            assert assistbinding.selected_definition(standalone) is None
        assert assistbinding.selected_definition(standalone) is chosen
        with assistbinding.bound(SimpleNamespace(definitions=(nested,), engagement_level=5)):
            assert assistbinding.selected_definition(standalone) is nested
        assert assistbinding.selected_definition(standalone) is chosen
    assert assistbinding.current() is assistbinding.UNBOUND
    assert assistbinding.selected_definition(standalone) is standalone


@pytest.mark.parametrize('order', [('massage', 'writeproxy', 'probegate', 'toolstages'),
                                 ('writeproxy', 'toolstages', 'probegate', 'massage'),
                                 ('probegate', 'massage', 'toolstages', 'writeproxy')])
def test_facade_import_orders_keep_real_composition_available(order):
    imports = '\n'.join(f'import cria.{name}' for name in order)
    script = imports + '''\nfrom cria import massage, writeproxy, callsyntax, filecommands
assert massage._menu_schemas is callsyntax._menu_schemas
assert writeproxy._read_command is filecommands._read_command
'''
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
