"""Returned-tool interventions; correlation and workspace facts stay in writeproxy."""
from __future__ import annotations
import json
import re

from . import denial, depsurface, dirguard, probeparse, proberun, prompts
from .resultnotes import (append_note, probegate_marker_in, _strip_exec_envelope,
                          _workspace_ecosystem, _noted, exec_envelope)
from .toolargs import parse_args as _parse
from .assistcontract import Policy, Reference
from .toolcontracts import (ReturnedResult, ReturnedHistory, ReturnedDefinition, HistoryDefinition,
                            DraftDefinition, RejectedDraft)

_REJECTED_PAYLOAD_CHARS = 400
_SURFACE_INLINE_BUDGET = 6000
_MAX_NOTES_PER_REQUEST = 3
_MAX_ANCHOR_RENDERS_PER_REQUEST = 12
_MAX_TOTAL_NOTE_BYTES_PER_REQUEST = 24_000

def _rejected_payload_note(tc: dict, path: str) -> str:
    """Lossless, explicitly provenanced copy of large bytes removed from a rejected tool argument."""
    fn = tc.get("function") or {}
    args = _parse(fn.get("arguments"))
    if not isinstance(args, dict):
        return ""
    blocks = []
    for key in ("old_string", "new_string", "content"):
        val = args.get(key)
        if isinstance(val, str) and len(val) > _REJECTED_PAYLOAD_CHARS:
            blocks.append(prompts.render("rejected_candidate", tool=fn.get("name") or "write",
                                         key=key, path=path, body=val).strip())
    return "\n\n".join(blocks)


def _collapse_rejected_payload(tc: dict, path: str, rlog=None) -> dict:
    """Take a REJECTED edit's verbatim payload OUT of the call, rather than replacing it with prose.

    The model no longer sees its own invented file text rendered as though it were the file. What it
    still sees is the call it made, the path it aimed at, and — in the tool RESULT, which is cria's
    own marked refusal — that nothing was written. None of that lives in an argument slot.

    NO SENTENCE GOES IN THE CONTENT SLOT. This used to write
    `[985 characters — this edit was REJECTED, nothing was written to <path>]` into `content`, which
    is the exact position a file body occupies, and the model read it as one. In the captures:
    `20260819T063347` calls 0046 and 0047 emitted `write_file {"content": "[2254 characters — this
    edit was REJECTED…]"}` twice in a row — cria's sentence WAS the file it wrote;
    `20260817T020431/0012` reasoned *"The current pom.xml is: ```[1107 characters — this edit was
    REJECTED…]```"*; `20260822T001226/0078` attributed the same sentence to a read_file result. The
    stub's em dash is the documented cause of `Importer.java:[1,20] illegal character: '\u2014'`.
    It shipped in 858 prompt files, 1,770 times, including 85 coder prompts on 2026-08-22/23.

    `focustrim` reached the same place from the other side and the operator ruled on it,
    2026-08-19: *"There is not supposed to be any elision. It's all or nothing."* There the whole
    call could go, because a superseded write loses nothing. Here the failure is information the
    coder needs, so the CALL stays and only the payload leaves — which is the same rule applied to
    the only part of it that can be misread."""
    fn = tc.get("function") or {}
    args = _parse(fn.get("arguments"))
    if not isinstance(args, dict):
        return tc
    dropped = []
    for key in ("old_string", "new_string", "content"):
        val = args.get(key)
        if isinstance(val, str) and len(val) > _REJECTED_PAYLOAD_CHARS:
            del args[key]
            dropped.append((key, len(val)))
    if not dropped:
        return tc
    if rlog is not None:
        rlog.emit("writeproxy.rejected_payload_dropped", level="info", path=path,
                  keys=[k for k, _ in dropped], chars=sum(n for _, n in dropped))
    return {**tc, "function": {**fn, "arguments": json.dumps(args)}}


def _note_dependency_surface(source: ReturnedHistory) -> None:
    """Candidate C40. See cria/depsurface.py's module docstring for the full redesign history.

    TWO PHASES, ANCHORED FIRST (independent review round 4, R3 regression fix #1). The round-3 shape
    processed every declared coordinate in ONE pass, in manifest order -- so a coordinate that had
    never been anchored yet, but happened to be listed before an already-anchored one, could consume
    budget a stable, already-delivered note needed, displacing it for that request (breaking the very
    stability the durable-anchor design exists for). This function now runs two full passes: PHASE 1
    re-renders every ALREADY-ANCHORED coordinate first (bounded by `_MAX_ANCHOR_RENDERS_PER_REQUEST`
    and the byte budget) -- no disk read, no `gather()` call, `gather()` still runs AT MOST ONCE per
    coordinate per session. Only once phase 1 is done does PHASE 2 consider coordinates never anchored
    this session, bounded by `_MAX_NOTES_PER_REQUEST` new `gather()` calls.

    ANCHOR LOSS (a harness compaction folds the anchor's message out of history): re-anchored once on
    the newest qualifying tool result within phase 1, replaying the SAME cached text -- see the
    C37/compaction rationale in this module's git history for why re-anchoring is preferred over
    staying silent.

    TIMELESS WORDING. `cria/prompts/dependency_surface_*.txt` says "THE VERSION ... DECLARED IN
    <manifest>", never "JUST RESOLVED" -- true no matter how many times the identical text repeats.

    PERMANENT WITHHOLDING, NEVER RE-GATHERED, NO FALSE PROMISE (independent review round 4, R3
    regression fixes #2 and #3). A coordinate whose real surface does not fit the remaining byte
    budget the FIRST time it is gathered is recorded in `depsurface._WITHHELD` -- permanently for the
    session, so it is NEVER handed to `gather()` again (round 3's bug: a withheld coordinate was
    silently re-gathered on every later request, which for JVM meant a fresh `javap` subprocess every
    single turn). Only three small pointer fields are kept (the coordinate label, its real local path,
    and the real command to read it), never the full surface. The combined withheld note names every
    withheld coordinate's real read command directly (`go doc -all <coord>` / `jar tf <jar>` / a real
    grep-able path) and explicitly says it will NOT appear automatically -- round 3's wording promised
    "they will appear on a later turn," which was false (#5b): nothing in this design ever revisits a
    withheld coordinate, so nothing could have made that promise true.

    Without a `sess_key` (no identity to remember anchors/withholds against) this abstains entirely."""
    messages, workspace_root, rlog = source.messages, source.workspace_root, source.log
    sess_key = source.session
    if not source.tools_present:
        return
    if not workspace_root or not sess_key:
        return
    by_call_id: dict[str, dict] = {}
    newest_tool = None
    for m in messages:
        if m.get("role") == "tool" and isinstance(m.get("content"), str) and m["content"]:
            newest_tool = m   # keep walking -- the LAST qualifying tool result in this batch wins
            cid = m.get("tool_call_id")
            if cid:
                by_call_id[cid] = m
    if newest_tool is None:
        return
    declared = depsurface.declared_coordinates(workspace_root)
    build_roots = dirguard.dependency_roots(messages, workspace_root)   # where THIS run's build keeps its dependencies
    declared_keys = {(eco, package, version) for eco, package, version in declared}

    total_bytes = 0
    anchor_renders = 0

    # PHASE 1 -- every already-anchored coordinate, priority, before anything new is even considered.
    for eco, package, version in declared:
        if anchor_renders >= _MAX_ANCHOR_RENDERS_PER_REQUEST:
            break
        coordinate_key = (eco, package, version)
        state = depsurface.anchor_state(sess_key, coordinate_key)
        if state is None:
            continue   # never anchored -- phase 2's job
        anchor_id, note_text = state
        note_bytes = len(note_text.encode("utf-8", "replace"))
        if total_bytes + note_bytes > _MAX_TOTAL_NOTE_BYTES_PER_REQUEST:
            break   # anchored notes have priority; if even one cannot fit, stop -- phase 2 won't fit either
        anchor_msg = by_call_id.get(anchor_id)
        if anchor_msg is not None:
            append_note(anchor_msg, note_text)
            total_bytes += note_bytes
            anchor_renders += 1
            continue
        # Anchor lost (compaction) -- re-anchor once on the newest tool result, same cached text.
        new_cid = newest_tool.get("tool_call_id")
        if new_cid:
            append_note(newest_tool, note_text)
            depsurface.set_anchor_state(sess_key, coordinate_key, new_cid, note_text)
            total_bytes += note_bytes
            anchor_renders += 1
            if rlog is not None:
                rlog.emit("writeproxy.dependency_surface_reanchored", level="info", ecosystem=eco,
                          coordinate=coordinate_key)

    # PHASE 2 -- coordinates never anchored: a bounded new gather(), or (if already withheld) nothing
    # at all -- the combined pointer note below is the only thing a withheld coordinate ever costs.
    new_gathers = 0
    for eco, package, version in declared:
        coordinate_key = (eco, package, version)
        if depsurface.anchor_state(sess_key, coordinate_key) is not None:
            continue   # phase 1 already handled it
        if depsurface.is_withheld(sess_key, coordinate_key):
            continue   # permanently withheld -- NEVER gathered again
        if new_gathers >= _MAX_NOTES_PER_REQUEST:
            continue
        if not depsurface.source_located(eco, package, version, workspace_root, build_roots):
            continue   # declared but not on disk YET (the build resolves after the manifest is written):
            #            ask again next request, for stat calls only -- no abstain back-off, no decode
        if not depsurface.should_retry_gather(sess_key, coordinate_key):
            continue   # abstained recently (cache absent / go doc/javap failed) -- not retried yet
        cid = newest_tool.get("tool_call_id")
        if not cid:
            continue   # no stable id to anchor to -- skip rather than anchor to nothing
        surface = depsurface.gather(eco, package, version, workspace_root, cache_roots=build_roots)
        new_gathers += 1   # gather() ran -- counts here whether or not it fit the budget below
        if surface is None:
            depsurface.record_abstain(sess_key, coordinate_key)
            continue   # abstain silently -- manifest declares it, but the local cache does not
        note = _render_dependency_surface(surface, eco)
        if not note:
            depsurface.record_abstain(sess_key, coordinate_key)
            continue
        note_bytes = len(note.encode("utf-8", "replace"))
        if total_bytes + note_bytes > _MAX_TOTAL_NOTE_BYTES_PER_REQUEST:
            # A REAL surface that simply does not fit -- withheld PERMANENTLY, never gathered again.
            depsurface.record_withheld(sess_key, coordinate_key, surface.coordinate, surface.root,
                                       surface.read_hint)
            if rlog is not None:
                rlog.emit("writeproxy.dependency_surface_withheld_new", level="info", ecosystem=eco,
                          coordinate=coordinate_key)
            continue
        append_note(newest_tool, note)
        depsurface.set_anchor_state(sess_key, coordinate_key, cid, note)
        depsurface.clear_abstain(sess_key, coordinate_key)
        total_bytes += note_bytes
        anchor_renders += 1
        if rlog is not None:
            rlog.emit("writeproxy.dependency_surface", level="info", ecosystem=eco,
                      coordinate=surface.coordinate, members=len(surface.lines),
                      complete=surface.complete)

    # Independent review round 5: `withheld_pointers` is filtered against `declared_keys` -- the SAME
    # filter the anchor phases use -- so a superseded version (a bump replaced p6 v1.0.0 with p6
    # v1.1.0) or a removed dependency (p5 dropped from go.mod) stops being named the moment it leaves
    # the manifest, instead of being listed forever as a false present-tense fact about the project.
    pointers = depsurface.withheld_pointers(sess_key, declared_keys)
    if pointers:
        all_lines = [f"- {label}: {read_hint}" for label, _root, read_hint in pointers]
        # The pointer BLOCK itself counts against the same total-byte budget as every other note
        # (independent review round 5) -- bounded, never a silent unbounded addition once several
        # coordinates are withheld. A pointer line that does not fit is simply not shown; the COUNT
        # in the label is always the real total, so an incomplete pointer list never claims to be
        # the whole one.
        shown_lines: list[str] = []
        budget_left = _MAX_TOTAL_NOTE_BYTES_PER_REQUEST - total_bytes
        used = 0
        for line in all_lines:
            cost = len(line.encode("utf-8", "replace")) + 1
            if used + cost > max(budget_left, 0):
                break
            shown_lines.append(line)
            used += cost
        if shown_lines:
            block = prompts.render("dependency_surface_withheld", count=str(len(pointers)),
                                   pointers="\n".join(shown_lines))
            append_note(newest_tool, block)
            total_bytes += len(block.encode("utf-8", "replace"))


def _render_dependency_surface(surface, ecosystem: str) -> str:
    """The model-facing note for one real DependencySurface -- every line in it is byte-identical to a
    line :func:`cria.depsurface.gather` read from disk (#5b: never a cria paraphrase of what a real
    tool said). Uses the COMPLETE template ONLY when ``surface.complete`` is True (a real,
    authoritative tool enumerated the package's whole exported surface, e.g. ``go doc -all``) AND the
    complete selection fits the inline budget -- otherwise ALWAYS the partial template, which never
    claims a missing member does not exist (independent review B3). ``ecosystem`` selects the
    TIMELESS manifest label ("the version declared in go.mod") -- this text is re-rendered verbatim on
    every later turn, so it must never say anything that is only true at the moment of first
    delivery."""
    manifest = depsurface.MANIFEST_LABEL.get(ecosystem, "the project's dependency manifest")
    joined = "\n".join(surface.lines)
    fits = len(joined.encode("utf-8", "replace")) <= _SURFACE_INLINE_BUDGET
    if surface.complete and fits:
        return prompts.render("dependency_surface_complete", coordinate=surface.coordinate,
                              manifest=manifest, root=surface.root, lines=joined)
    shown: list[str] = list(surface.lines) if fits else []
    if not fits:
        budget = _SURFACE_INLINE_BUDGET
        for line in surface.lines:
            cost = len(line.encode("utf-8", "replace")) + 1
            if cost > budget:
                break
            shown.append(line)
            budget -= cost
        if not shown:
            shown = list(surface.lines[:1])
    return prompts.render("dependency_surface_partial", coordinate=surface.coordinate,
                          manifest=manifest, root=surface.root, total=str(len(surface.lines)),
                          shown=str(len(shown)), lines="\n".join(shown), read_hint=surface.read_hint)


def _note_missing_dependency(source: ReturnedHistory) -> None:
    """Label the MOST RECENT command result whose own output says a dependency will not load.

    The note existed already and fired only on cria's gate probes — so it never saw the model's own
    `ruby -Ilib …`, which is where this actually happens. Measured on the p3 arm: nemotron-elastic's
    ruby run carried `cannot load such file` 39 times and the note appeared zero times, and all five
    of that cell's checks died on that one unloadable gem. Same mistake as the read guard: the door
    cria watches was not the door the failure comes through.

    ONLY THE LAST ONE. Annotating all 39 would put the same paragraph in the window 39 times, which
    is noise on a signal the model has already seen (#3). The most recent occurrence is the turn it
    can act on.

    Silent when the name resolves to the project's own file — telling a coder its own module is a
    missing dependency sends it after a package that should not exist (#8: ask the disk)."""
    messages, workspace_root, rlog = source.messages, source.workspace_root, source.log
    last = None
    for m in messages:
        if m.get("role") != "tool":
            continue
        c = m.get("content")
        if not isinstance(c, str) or probegate_marker_in(c):
            continue          # a gate result already carries the note from proberun
        if probeparse.dependency_missing(c):
            last = m
    if last is None:
        return
    eco, name = probeparse.dependency_missing(last["content"])
    if workspace_root and probeparse.names_a_workspace_file(name, workspace_root):
        return
    note = prompts.fill(proberun.dependency_line(eco, workspace_root or ""), name=name)
    if note in last["content"]:
        return
    append_note(last, note)
    if rlog is not None:
        rlog.emit("writeproxy.dependency_note", level="info", ecosystem=eco, name=name)


def _note_dependency_search(source: ReturnedHistory) -> None:
    """Answer a search for dependency SOURCE that came back empty, by naming where it really lives.

    `probeparse.searched_for_dependency_source` and `probeparse.dependency_source_root` were written
    for this on 2026-08-19 and NOTHING EVER CALLED THEM. The prompt file existed, the table of
    per-ecosystem roots existed, the tests passed against the functions directly — and the whole
    thing sat outside the loop for a day (#11b, again: a mechanism that reaches nothing). Its sibling
    from the same walk, the 4xx note in `webfetch.render_page`, did land, so half that fix has been
    live and half has been dead.

    The incident it was built for, walked on `rust-toml-cli x ternary-bonsai` 2026-08-19: the coder
    ran `find <WORKSPACE>/.cargo/registry/src/... -name value.rs` twice, got nothing both times, and
    concluded the source was unavailable. It was on the box the whole run under `~/.cargo/registry/src`
    — one directory root away — and the model spent the next twenty calls guessing TOML syntax from
    memory instead.

    THE TRIGGER IS THE SEARCH, NOT THE FAILURE THAT PROMPTED IT, and that bounds what this can do:
    a model that never goes looking is never answered. `feed-pipeline-java x nemotron-elastic`
    1787247514 died believing `com.opencsv.CSVRecord` exists, with the jar sitting in `~/.m2` that
    would have disproved it in one command — and searched no package directory in 74 calls, so this
    note could not have fired. Pointing a model at the source it did not ask for is a different
    mechanism and a much higher bar (#1); this one only answers a question already asked.

    ONLY THE LAST ONE, like its sibling above: repeating the same paragraph for every empty search is
    noise on a signal the model has already read (#3). Silent when the search found something, when
    the path searched is already the home root (`searched_for_dependency_source` handles that), and
    when no root for this ecosystem is on disk in the `found` wording — that case gets the `absent`
    wording instead, which tells the model to stop searching the same way rather than sending it to a
    directory cria cannot see."""
    messages, workspace_root, rlog = source.messages, source.workspace_root, source.log
    own_cmds = source.own_commands
    if not messages:
        return
    last, searched = None, ""
    for m in messages:
        if m.get("role") != "tool":
            continue
        c = m.get("content")
        if not isinstance(c, str) or probegate_marker_in(c):
            continue
        tok = probeparse.searched_for_dependency_source(own_cmds.get(m.get("tool_call_id"), ""))
        if not tok:
            continue
        if _strip_exec_envelope(c).strip():
            continue                     # it FOUND something — nothing to answer (#3)
        last, searched = m, tok
    if last is None:
        return
    eco = _workspace_ecosystem(workspace_root)
    root = probeparse.dependency_source_root(eco, workspace_root or "") if eco else ""
    if root is None:
        # cria has not been told where this ecosystem keeps its source yet — the candidates are
        # queued for the next survey. Saying "no installed source root can be found on this machine"
        # from an unasked question is the false fact the `absent` wording is built on, and its remedy
        # sends the coder away from source that may be one directory over (#23c, #3).
        return
    words = prompts.load_map("dependency_source_root")
    # …AND NOT A PARENT OF WHERE IT JUST LOOKED. The `found` wording says "you looked in the wrong
    # root; the real one is <root>" — false when the token is already inside that root, and its
    # remedy names a directory the search was already under. Walked on shipping-rates-rb x
    # nemotron-elastic 1787432916: cria answered a search of the installed gem's own lib/ with "this
    # project keeps no vendored copy there … Search there instead", naming the parent (#5b).
    if root and probeparse.searched_under(searched, root):
        return
    note = (prompts.fill(words["found"], searched=searched, root=root) if root
            else prompts.fill(words["absent"], searched=searched))
    if note in last["content"]:
        return
    append_note(last, note)
    if rlog is not None:
        rlog.emit("writeproxy.dependency_source_note", level="info",
                  ecosystem=eco or "", root=root, searched=searched)


def preserve_rejected_draft(call: dict, path: str, log=None) -> RejectedDraft:
    note = _rejected_payload_note(call, path)
    return RejectedDraft(_collapse_rejected_payload(call, path, log), note)


def edit_failure(source: ReturnedResult) -> dict | None:
    if not source.mutation_failure or denial.outcome(source.message) != denial.UNAPPLIED:
        return None                  # unproven: the tool's own bytes stay (never an invented cut/mismatch)
    from . import editrecovery
    return {**source.message, 'content': editrecovery.recover(source.content, source.prior, source.log)}


def environment_advice(source: ReturnedResult) -> dict | None:
    if source.mutation_failure or 'externally-managed-environment' not in source.content:
        return None
    return _noted(source.message, source.content, prompts.load('pep668_remedy'))


# Shape-only facts, not semantic advice classifiers. A pipe is handled separately
# because it can hide another command's failure rather than answer a search.
_SEARCH_CMD = re.compile(r"(?:^|[;&|(]\s*)\s*(?:grep|egrep|fgrep|rg|ag|ack)\b")
_FILTER_PIPE = re.compile(r"\|\s*(?:grep|egrep|fgrep|rg|head|tail|sed|awk)\b")


def _found_nothing(command: str, content: str) -> bool:
    cmd = command or ''
    if not cmd or not _SEARCH_CMD.search(cmd) or _FILTER_PIPE.search(cmd):
        return False
    envelope = exec_envelope(content or '')
    if envelope is None or envelope.exit_code != 1:
        return False
    return not _strip_exec_envelope(content or '').strip()


def _blind_pipe_failure(command: str, content: str) -> bool:
    if not command or not _FILTER_PIPE.search(command):
        return False
    envelope = exec_envelope(content)
    if envelope is None or envelope.exit_code in (None, 0):
        return False
    return _strip_exec_envelope(content).strip() == ''


def empty_search(source: ReturnedResult) -> dict | None:
    if source.mutation_failure:
        return None
    if _found_nothing(source.own_command, source.content):
        return _noted(source.message, source.content, prompts.load('search_found_nothing'))
    return None


def filtered_failure(source: ReturnedResult) -> dict | None:
    if source.mutation_failure:
        return None
    if _blind_pipe_failure(source.own_command, source.content):
        return _noted(source.message, source.content, prompts.load('filtered_failure_note'))
    return None


RESULTS = (
    ReturnedDefinition(Policy('edit-failure-recovery', 'returned-result', 2, family_id='F17',
        services=('prior-edit-results',), hooks=(Reference('cria/writeproxy.py', 'represent_inbound'),),
        regressions=(Reference('tests/test_writeproxy.py', 'EditRecoveryTests'),), migrated=False), edit_failure),
    ReturnedDefinition(Policy('environment-failure-advice', 'returned-result', 2, family_id='F20',
        prompts=('pep668_remedy',), hooks=(Reference('cria/writeproxy.py', 'represent_inbound'),),
        regressions=(Reference('tests/test_o15r_the_ledger_never_invents_a_count.py',
                               'test_the_represent_inbound_appenders_record_the_boundary'),), migrated=False), environment_advice),
    ReturnedDefinition(Policy('empty-search-note', 'returned-result', 2, family_id='F14',
        prompts=('search_found_nothing',), hooks=(Reference('cria/writeproxy.py', 'represent_inbound'),),
        regressions=(Reference('tests/test_an_empty_search_is_an_answer.py', 'AnEmptyResultSpeaksTests'),),
        migrated=False), empty_search),
    ReturnedDefinition(Policy('filtered-failure-note', 'returned-result', 2, family_id='F14',
        prompts=('filtered_failure_note',), hooks=(Reference('cria/writeproxy.py', 'represent_inbound'),),
        regressions=(Reference('tests/test_writeproxy.py', 'BlindPipeNoteTests'),), migrated=False), filtered_failure),
)
HISTORY = (
    HistoryDefinition(Policy('missing-dependency-note', 'returned-history', 2, family_id='F20',
        services=('workspace-view',), hooks=(Reference('cria/writeproxy.py', 'represent_inbound'),),
        regressions=(Reference('tests/test_the_dependency_note_asks_the_disk.py',
                               'TheWorldIsAskedBeforeItIsDescribedTests'),), migrated=False), _note_missing_dependency),
    HistoryDefinition(Policy('dependency-source-note', 'returned-history', 2, family_id='F20',
        services=('workspace-view',), prompts=('dependency_source_root',),
        hooks=(Reference('cria/writeproxy.py', 'represent_inbound'),),
        regressions=(Reference('tests/test_the_dependency_source_note_reaches_the_loop.py',
                               'TheNoteIsActuallyDeliveredTests'),), migrated=False), _note_dependency_search),
    HistoryDefinition(Policy('dependency-api-evidence', 'returned-history', 2, family_id='F20',
        state='depsurface session anchors, abstentions and withheld coordinates; reanchor after context loss',
        services=('declared-coordinates', 'dependency-surface'),
        prompts=('dependency_surface_complete', 'dependency_surface_partial', 'dependency_surface_withheld'),
        hooks=(Reference('cria/writeproxy.py', 'represent_inbound'),),
        regressions=(Reference('tests/test_dependency_surface_note.py', 'MultiRequestReplayTests'),
                     Reference('tests/test_tool_policy_stages.py',
                               'test_dependency_anchor_settlement_and_abstention_counters_stop_when_deselected')),
        migrated=False), _note_dependency_surface),
)
REJECTED_DRAFT = DraftDefinition(Policy('rejected-draft-provenance', 'rejected-draft', 2,
    family_id='F15', services=('paired-refusal',), prompts=('rejected_candidate',),
    hooks=(Reference('cria/writeproxy.py', 'represent_inbound'),),
    regressions=(Reference('tests/test_tool_policy_stages.py',
                           'test_rejected_draft_switch_controls_both_payload_movement_and_note'),), migrated=False),
    preserve_rejected_draft)
