"""Ordered outbound policy effects. Shell construction stays a harness adapter."""
from __future__ import annotations
import json

from . import content_reduce as content_reduce_mod, dirguard, prompts, webfetch, wsview
from .assistcontract import Policy, Reference
from dataclasses import replace

from .toolcontracts import (OutboundCall, OutboundDefinition, MutationDefinition, MutationPlan, ReadIntent, ReviewTerms, RewrittenCall,
                            Refusal, ProbeIntent)
from .probeops import UnreadProbe
from .shrinkprotection import DEFINITION as SHRINK_PROTECTION
from .callliterals import _has_tc_debris, _protocol_debris
from .filecommands import (
    _WRITE_NAMES, _EDIT_NAMES, _READ_NAMES, _guarded_path, _targets_cria_home,
    _prepare_file_mutation, _under_spill_dir, _spill_relpath, _respill_command,
)
from .toolwire import _refusal_command, _command_of
from .shelltool import _CMD_FIELDS, is_shell_tool_name
from .toolargs import PATH_KEYS as _PATH_KEYS, tool_path as _tool_path


def malformed_shell(source: OutboundCall) -> Refusal | None:
    name, args, fn, rlog = source.name, source.arguments, source.function, source.log
    if is_shell_tool_name(name) and _has_tc_debris(fn.get('arguments')):
        text = prompts.load('malformed_call_refusal')
        if rlog is not None:
            rlog.emit('writeproxy.blocked_malformed_call', tool=name)
        return Refusal(text)
    return None


def external_boundary(source: OutboundCall) -> Refusal | None:
    name, args, fn, rlog = source.name, source.arguments, source.function, source.log
    request = source.request
    injected, external_dir_permission = request.injected, request.external_dir_permission
    workspace_root, declared_roots = request.workspace_root, request.declared_roots
    session, pack = request.session, request.pack
    if (reason := _external_refusal(name, args, fn, injected, external_dir_permission, workspace_root, declared_roots)) is not None:
        text = reason
        if rlog is not None:
            rlog.emit('writeproxy.blocked_external', tool=name, permission=external_dir_permission)
        return Refusal(text)
    return None


def private_files(source: OutboundCall) -> Refusal | None:
    name, args, fn, rlog = source.name, source.arguments, source.function, source.log
    injected = source.request.injected
    if name in injected and (target := _guarded_path(name, args)) and _targets_cria_home(target):
        text = prompts.load('cria_home_refusal')
        if rlog is not None:
            rlog.emit('writeproxy.blocked_cria_home', tool=name, path=target)
        return Refusal(text)
    return None


def reference_files(source: OutboundCall) -> Refusal | ReadIntent | None:
    name, args, fn, rlog = source.name, source.arguments, source.function, source.log
    injected = source.request.injected
    if name in _WRITE_NAMES | _EDIT_NAMES | _READ_NAMES and name in injected and (sp := _tool_path(args)) and _under_spill_dir(str(sp), webfetch.SPILL_DIR) and (not (name in _READ_NAMES and (args.get('start_line') or args.get('end_line')))):
        if rlog is not None:
            rlog.emit('writeproxy.spill_read_gated' if name in _READ_NAMES else 'writeproxy.blocked_spill', tool=name, path=str(sp))
        return ReadIntent() if name in _READ_NAMES else Refusal(prompts.render('spill_edit_refusal', path=str(sp)))
    return None


def spill_paths(source: OutboundCall) -> RewrittenCall | None:
    args, fn, name, log = source.arguments, source.function, source.name, source.log
    changed = False
    call = source.call
    if name in source.request.injected and (path := _tool_path(args)) and (rel := _spill_relpath(str(path), webfetch.SPILL_DIR)):
        for key in _PATH_KEYS:
            if args.get(key):
                args = {**args, key: rel}
                changed = True
                break
        if log is not None:
            log.emit('writeproxy.spill_path_redirect', tool=name, to=rel)
    if is_shell_tool_name(name) and (command := _command_of(fn.get('arguments'))) and _respill_command(command, webfetch.SPILL_DIR) != command:
        args = dict(args)
        for key in (*_CMD_FIELDS, 'script'):
            value = args.get(key)
            if isinstance(value, list) and value and isinstance(value[-1], str):
                args[key] = [*value[:-1], _respill_command(value[-1], webfetch.SPILL_DIR)]
            elif isinstance(value, str) and value:
                args[key] = _respill_command(value, webfetch.SPILL_DIR)
        changed = True
        call = {**source.call, 'function': {**fn, 'arguments': json.dumps(args, ensure_ascii=False)}}
        if log is not None:
            log.emit('writeproxy.spill_command_redirect', tool=name)
    if changed:
        return RewrittenCall(call, args)
    return None


def _valid_write(source: OutboundCall):
    if source.name not in _WRITE_NAMES or source.name not in source.request.injected:
        return None
    mutation = _prepare_file_mutation(source.name, source.arguments)
    return mutation if not mutation.error else None


def fused_file(source: OutboundCall) -> Refusal | None:
    mutation = _valid_write(source)
    if mutation is None or not _protocol_debris(mutation.content):
        return None
    if source.log is not None:
        source.log.emit('writeproxy.write_fused_content', tool=source.name, path=str(mutation.path))
    return Refusal(prompts.load('write_fused_content'))


def unread_replacement(source: OutboundCall) -> ReadIntent | None:
    request = source.request
    # Selection encloses the callback: a disabled policy cannot gather or mutate its ledger.
    if request.unread_target is None:
        return None
    if source.name == 'apply_patch':
        from .toolargs import patch_paths
        paths = patch_paths(source.call)
        # A multi-target or move patch needs a multi-spec bridge, not a partial read.
        if len(paths) != 1 or '*** Move to:' in str(source.function.get('arguments') or ''):
            return None
        path = paths[0]
    elif source.name in _WRITE_NAMES | _EDIT_NAMES:
        mutation = _prepare_file_mutation(source.name, source.arguments)
        if mutation.error:
            return None
        path = str(mutation.path)
    else:
        return None
    if not (fact := request.unread_target(path)):
        return None
    if isinstance(fact, UnreadProbe):
        # Nothing known settles whether the file may be overwritten unread: the file is asked (cria.probeops) and the call lowered again with the answer.
        return ProbeIntent(path) if request.issue_probe is not None else None
    if source.log is not None:
        source.log.emit('writeproxy.write_unread_target', tool=source.name, path=path)
    return ReadIntent(fact)


def candidate_safety(source: OutboundCall, plan: MutationPlan) -> MutationPlan:
    """Only proven unsafe complete candidates are refused; unknown stays unknown. The policy's fact is its terms: cria reviews each
    complete candidate in-process (:mod:`cria.writeops`), on the exact bytes it is about to write, before anything lands."""
    request = source.request
    return replace(plan, review=ReviewTerms(request.external_dir_permission, request.workspace_root))


def _external_refusal(name, args, fn, injected, level: str, workspace: str | None, roots=()) -> str | None:
    """A refusal string when this tool call reaches outside the workspace beyond ``level``, else None.
    A synthetic file tool is checked by its explicit path + operation; a raw shell command by a
    heuristic scan. cria's OWN composed commands (the gate probe / a lowered synthetic, carrying a
    marker) are exempt — trusted and always workspace-scoped. See cria/dirguard.py."""
    if is_shell_tool_name(name):
        command = _command_of(fn.get("arguments"))
        every_level = dirguard.root_recursive_delete_refusal(command) or dirguard.machine_harm_refusal(command)
        if every_level:
            return every_level
    if not workspace:
        return None
    if level == "write":  # unrestricted external-directory permission, except root deletion and machine-wide harm
        return None
    if name in injected:  # a synthetic file tool cria advertised → explicit path + operation
        target = _guarded_path(name, args)
        if not target:
            return None
        return dirguard.path_refusal(target, name in _WRITE_NAMES or name in _EDIT_NAMES, level, workspace, roots)
    if is_shell_tool_name(name):  # the harness's raw shell → heuristic path/verb scan
        command = _command_of(fn.get("arguments"))
        # NO COMMAND TEXT EARNS AN EXEMPTION (a model-authored command that began with cria's marker used to inherit cria's trust and skip this
        # guard entirely: the security review's finding F3): what cria issues itself (its primitives, its gate) is issued after this guard and
        # never passes through it, under an id only its key makes; a model-authored command is guarded as any other, whatever its first line says.
        return dirguard.command_refusal(command, level, workspace, roots)
    return None


DEFINITIONS = tuple(OutboundDefinition(Policy(id, 'outbound-call', level, family_id=family,
    services=services, prompts=prompts,
    hooks=(Reference('cria/writeproxy.py', 'translate_outbound'),),
    regressions=(regression,), migrated=False), execute)
    for id, family, level, services, prompts, regression, execute in (
    ('spill-path-correction', 'F63', 2, (), (),
     Reference('tests-before-reset-20261031:tests/test_tool_policy_stages.py', 'test_spill_correction_changes_execution_path_not_original_call_evidence'), spill_paths),
    ('malformed-shell-refusal', 'F01', 2, (), ('malformed_call_refusal',),
     Reference('tests-before-reset-20261031:tests/test_writeproxy.py', 'MalformedFusedCallTests'), malformed_shell),
    ('workspace-boundary', 'F22', 2, ('workspace-view',), (),
     Reference('tests-before-reset-20261031:tests/test_tool_policy_stages.py', 'test_disabled_external_guard_does_not_queue_workspace_questions'), external_boundary),
    ('private-directory-protection', 'F22', 2, (), ('cria_home_refusal',),
     Reference('tests-before-reset-20261031:tests/test_writeproxy.py', 'CriaHomeGuardTests'), private_files),
    ('reference-file-protection', 'F22', 2, (), ('spill_edit_refusal',),
     Reference('tests/misc_runtime/test_misc_runtime_spill_read.py', 'test_a_missing_spilled_file_is_reported_missing_and_reference_material_is_never_editable'), reference_files),
    ('fused-file-refusal', 'F13', 2, (), ('write_fused_content',),
     Reference('tests-before-reset-20261031:tests/test_writeproxy.py', 'FusedContentRefusalTests'), fused_file),
    ('unread-file-protection', 'F15', 5, ('whole-read-ledger',), (),
     Reference('tests/write_edit/test_write_edit_assists.py',
               'test_the_bound_selection_decides_which_write_and_edit_assists_act'), unread_replacement),
))


MUTATIONS = (
    MutationDefinition(Policy('candidate-mutation-safety', 'mutation-command', 2, family_id='F28',
        services=('workspace-view', 'candidate-safety'), prompts=('cleanup_stale',),
        hooks=(Reference('cria/writeproxy.py', '_lower_synthetic'),),
        regressions=(Reference('tests/write_edit/test_write_edit_outbound.py', 'test_a_write_or_edit_whose_candidate_would_delete_outside_the_workspace_is_withheld_and_a_repair_lands'),),
        migrated=False), candidate_safety),
    SHRINK_PROTECTION,
)
