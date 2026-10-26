"""Ordered outbound policy effects. Shell construction stays a harness adapter."""
from __future__ import annotations
import json
from shlex import quote as _qbash

from . import content_reduce as content_reduce_mod, dirguard, prompts, resultpacket, webfetch, wsview
from .assistcontract import Policy, Reference
from .toolcontracts import OutboundCall, OutboundDefinition, MutationDefinition, RewrittenCall, ShellCommand
from .shrinkprotection import DEFINITION as SHRINK_PROTECTION
from .callliterals import _has_tc_debris, _protocol_debris, _repair_double_escaped
from .filecommands import (
    _WRITE_NAMES, _EDIT_NAMES, _READ_NAMES, _guarded_path, _targets_cria_home,
    _prepare_file_mutation, _under_spill_dir, _spill_relpath, _respill_command,
    _read_in_place_of_write, _spill_read_command as _format_spill_read,
)
from .toolwire import (
    _b64, _refusal_command, _command_of, GATE_SENTINEL, _SENTINEL,
    _RIDE_ALONG_COMMAND_RESERVE, _RIDE_ALONG_HOST_RESERVE,
)
from .shelltool import _CMD_FIELDS, is_shell_tool_name
from .toolargs import PATH_KEYS as _PATH_KEYS, tool_path as _tool_path


def _spill_read_command(path: str) -> str:
    """Gather cached spill facts and render guidance above pure command formatting."""
    fmt = webfetch.format_for_spill_path(path)
    extent = webfetch.spill_reading_hint(path, content_reduce_mod.INLINE_RESULT_MAX_BYTES)
    fmt_clause = f' It is {fmt}.' if fmt else ''
    if webfetch.page_not_file_for_spill_path(path):
        fmt_clause += ' ' + prompts.load_map('webfetch_guards')['spill_is_the_page_not_the_file']
    steer = prompts.render('spill_read_steer', path=path, format=fmt_clause,
                           extent=(f' {extent}\n' if extent else ''),
                           outline=webfetch.outline_for_spill_path(path))
    return _format_spill_read(path, steer)

def malformed_shell(source: OutboundCall) -> ShellCommand | None:
    name, args, fn, rlog = source.name, source.arguments, source.function, source.log
    if is_shell_tool_name(name) and _has_tc_debris(fn.get('arguments')):
        cmd = _refusal_command(prompts.load('malformed_call_refusal'))
        if rlog is not None:
            rlog.emit('writeproxy.blocked_malformed_call', tool=name)
        return ShellCommand(cmd)
    return None


def external_boundary(source: OutboundCall) -> ShellCommand | None:
    name, args, fn, rlog = source.name, source.arguments, source.function, source.log
    request = source.request
    injected, external_dir_permission = request.injected, request.external_dir_permission
    workspace_root, declared_roots = request.workspace_root, request.declared_roots
    session, pack = request.session, request.pack
    if (reason := _external_refusal(name, args, fn, injected, external_dir_permission, workspace_root, declared_roots)) is not None:
        ride = ''
        if wsview.pending(session or '')[1]:
            room = resultpacket.max_text_for_wire(     # the survey travels as an encoded record: budget its worst-case wire cost
                content_reduce_mod.INLINE_RESULT_MAX_BYTES - _RIDE_ALONG_HOST_RESERVE - _RIDE_ALONG_COMMAND_RESERVE - len(reason))
            if room >= wsview.TREE_MIN_BYTES:
                ride = wsview.survey_command(session or '', cd=workspace_root or '', budget=room, pack=pack)
            elif rlog is not None:
                rlog.emit('wsview.survey_not_carried', level='info', left=room, carrier=name)
        cmd = _refusal_command(reason, ride)
        if rlog is not None:
            rlog.emit('writeproxy.blocked_external', tool=name, permission=external_dir_permission, carried_survey=bool(ride))
        return ShellCommand(cmd)
    return None


def private_files(source: OutboundCall) -> ShellCommand | None:
    name, args, fn, rlog = source.name, source.arguments, source.function, source.log
    injected = source.request.injected
    if name in injected and (target := _guarded_path(name, args)) and _targets_cria_home(target):
        cmd = _refusal_command(prompts.load('cria_home_refusal'))
        if rlog is not None:
            rlog.emit('writeproxy.blocked_cria_home', tool=name, path=target)
        return ShellCommand(cmd)
    return None


def reference_files(source: OutboundCall) -> ShellCommand | None:
    name, args, fn, rlog = source.name, source.arguments, source.function, source.log
    injected = source.request.injected
    if name in _WRITE_NAMES | _EDIT_NAMES | _READ_NAMES and name in injected and (sp := _tool_path(args)) and _under_spill_dir(str(sp), webfetch.SPILL_DIR) and (not (name in _READ_NAMES and (args.get('start_line') or args.get('end_line')))):
        cmd = _spill_read_command(str(sp)) if name in _READ_NAMES else _refusal_command(prompts.render('spill_edit_refusal', path=str(sp)))
        if rlog is not None:
            rlog.emit('writeproxy.spill_read_gated' if name in _READ_NAMES else 'writeproxy.blocked_spill', tool=name, path=str(sp))
        return ShellCommand(cmd)
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


def fused_file(source: OutboundCall) -> ShellCommand | None:
    mutation = _valid_write(source)
    if mutation is None or not _protocol_debris(mutation.content):
        return None
    if source.log is not None:
        source.log.emit('writeproxy.write_fused_content', tool=source.name, path=str(mutation.path))
    return ShellCommand(_refusal_command(prompts.load('write_fused_content')))


def unread_replacement(source: OutboundCall) -> ShellCommand | None:
    request = source.request
    # Selection encloses the callback: a disabled policy cannot gather or mutate its ledger.
    if request.unread_target is None:
        return None
    mutation = _valid_write(source)
    if mutation is None or not (fact := request.unread_target(str(mutation.path))):
        return None
    if source.log is not None:
        source.log.emit('writeproxy.write_unread_target', tool=source.name, path=str(mutation.path))
    return ShellCommand(_read_in_place_of_write(str(mutation.path), fact), read_in_place=True)


def candidate_safety(source: OutboundCall, command: str) -> str:
    """Only proven unsafe complete candidates are refused; unknown stays unknown."""
    from . import cleanupsafety, wsview, prompts
    request, name, log = source.request, source.name, source.log
    mutation = _prepare_file_mutation(name, source.arguments)
    path = str(mutation.path)
    if name in _WRITE_NAMES:
        candidate = _repair_double_escaped(mutation.content)
        refusal = cleanupsafety.review(path, candidate, None, request.workspace_root, log,
                                       permission=request.external_dir_permission)
        return _refusal_command(refusal) if refusal else command
    raw = wsview.current().read_bytes(path)
    try:
        previous = raw.decode() if raw is not None else None
    except UnicodeError:
        previous = None
    old, new = mutation.old, mutation.new
    if previous is not None and old and previous.count(old) == 1:
        refusal = cleanupsafety.review(path, previous.replace(old, new, 1), previous,
            request.workspace_root, log, permission=request.external_dir_permission)
        if refusal:
            check = ('import base64,pathlib,sys; p=pathlib.Path(base64.b64decode('
                     + repr(_b64(path)) + ').decode()); sys.exit(0 if p.read_bytes()==base64.b64decode('
                     + repr(_b64(previous)) + ') else 1)')
            stale = _refusal_command(prompts.load('cleanup_stale'))
            return f'if python3 -c {_qbash(check)}; then\n{_refusal_command(refusal)}\nelse\n{stale}\nfi'
    elif log is not None:
        log.emit('safety.cleanup_review', path=path, verdict='UNKNOWN', reason='complete exact edit candidate unavailable')
    return command


def _external_refusal(name, args, fn, injected, level: str, workspace: str | None, roots=()) -> str | None:
    """A refusal string when this tool call reaches outside the workspace beyond ``level``, else None.
    A synthetic file tool is checked by its explicit path + operation; a raw shell command by a
    heuristic scan. cria's OWN composed commands (the gate probe / a lowered synthetic, carrying a
    marker) are exempt — trusted and always workspace-scoped. See cria/dirguard.py."""
    if is_shell_tool_name(name):
        command = _command_of(fn.get("arguments"))
        root_delete = dirguard.root_recursive_delete_refusal(command)
        if root_delete:
            return root_delete
    if not workspace:
        return None
    if level == "write":  # unrestricted external-directory permission, except root-wide recursive deletion
        return None
    if name in injected:  # a synthetic file tool cria advertised → explicit path + operation
        target = _guarded_path(name, args)
        if not target:
            return None
        return dirguard.path_refusal(target, name in _WRITE_NAMES or name in _EDIT_NAMES, level, workspace, roots)
    if is_shell_tool_name(name):  # the harness's raw shell → heuristic path/verb scan
        command = _command_of(fn.get("arguments"))
        # cria's own composed command → trust. ANCHORED, not a substring scan anywhere in the text: a
        # model-authored command that merely mentions either literal used to inherit cria's trust and
        # skip the guard entirely. cria always writes the sentinel as the FIRST line (`# ⟦ctx:tool⟧<b64>`)
        # and always opens the gate script with `cd <workspace> || exit 97` followed by the section
        # echo — so requiring the marker in the first two lines authenticates the shape cria emits
        # rather than any text containing the token.
        head = "\n".join(command.lstrip().splitlines()[:2])
        # BOTH cria command sentinels earn the exemption: `# ⟦ctx:tool⟧` leads a lowered synthetic
        # tool call, `# ⟦ctx:gate⟧` (probegate.GATE_SENTINEL) leads the gate script AND its transport
        # continuation. The continuation is a `python3 - <spool> <<HEREDOC` reader that NAMES the
        # /tmp/.cria-gate-* spool; recognising only the tool sentinel made cria refuse its own
        # multi-page gate as "outside the working directory", so every large gate read UNKNOWN and the
        # completion path could never verify (cart-billing-go, session 20260906T124743).
        if (head.startswith("# " + _SENTINEL) or head.startswith("# " + GATE_SENTINEL)
                or (head.startswith("cd ") and "___CRIA_GATE_" in head)):
            return None
        return dirguard.command_refusal(command, level, workspace, roots)
    return None


DEFINITIONS = tuple(OutboundDefinition(Policy(id, 'outbound-call', level, family_id=family,
    services=services, prompts=prompts,
    hooks=(Reference('cria/writeproxy.py', 'translate_outbound'),),
    regressions=(regression,), migrated=False), execute)
    for id, family, level, services, prompts, regression, execute in (
    ('spill-path-correction', 'F63', 2, (), (),
     Reference('tests/test_tool_policy_stages.py', 'test_spill_correction_changes_execution_path_not_original_call_evidence'), spill_paths),
    ('malformed-shell-refusal', 'F01', 2, (), ('malformed_call_refusal',),
     Reference('tests/test_writeproxy.py', 'MalformedFusedCallTests'), malformed_shell),
    ('workspace-boundary', 'F22', 2, ('workspace-view',), (),
     Reference('tests/test_tool_policy_stages.py', 'test_disabled_external_guard_does_not_queue_workspace_questions'), external_boundary),
    ('private-directory-protection', 'F22', 2, (), ('cria_home_refusal',),
     Reference('tests/test_writeproxy.py', 'CriaHomeGuardTests'), private_files),
    ('reference-file-protection', 'F22', 2, (), ('spill_edit_refusal',),
     Reference('tests/test_tool_policy_stages.py', 'test_spill_correction_changes_execution_path_not_original_call_evidence'), reference_files),
    ('fused-file-refusal', 'F13', 2, (), ('write_fused_content',),
     Reference('tests/test_writeproxy.py', 'FusedContentRefusalTests'), fused_file),
    ('unread-file-protection', 'F15', 5, ('whole-read-ledger',), (),
     Reference('tests/test_a_write_to_a_file_never_seen_says_what_cria_measured.py',
               'test_the_answer_is_represented_as_the_coders_write_call_and_records_the_read'), unread_replacement),
))


MUTATIONS = (
    MutationDefinition(Policy('candidate-mutation-safety', 'mutation-command', 2, family_id='F28',
        services=('workspace-view', 'candidate-safety'), prompts=('cleanup_stale',),
        hooks=(Reference('cria/writeproxy.py', '_lower_synthetic'),),
        regressions=(Reference('tests/test_cleanup_safety.py', 'test_stale_source_cannot_bypass_a_known_unsafe_finding'),),
        migrated=False), candidate_safety),
    SHRINK_PROTECTION,
)
