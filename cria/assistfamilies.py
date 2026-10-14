"""Canonical assist-family identities and implementation ownership.

This is a navigation/maintenance registry, not runtime dispatch or a plugin list.
A family groups related policies and adapters; it is not an endorsement of every
variant or evidence of isolated usefulness. Planning remains explicitly opt-in.
Historical detail IDs are stable contract identities, not independent features.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class SourceOwner:
    path: str
    symbol: str = ""  # empty means a module or a non-Python artifact


@dataclass(frozen=True)
class AssistFamily:
    id: str
    title: str
    category: str
    contract: str
    details: tuple[str, ...]
    owners: tuple[SourceOwner, ...]
    scope: str = "gated_runtime"  # navigation classification, never an enable switch


FAMILIES: tuple[AssistFamily, ...] = (
    AssistFamily(
        'F01', 'Recover text-encoded tool calls',
        'Recovery and file safety',
        'One recovery family with dialect/channel adapters and explicit admissibility rules; not permission to promote every apparent call.',
        ('A01', 'A02', 'A03', 'A04', 'A05', 'A06', 'A07', 'A09', 'A10', 'A11', 'A12', 'A13'),
        (
            SourceOwner('cria/massage.py', 'recover_leaked_tool_calls'),
            SourceOwner('cria/massage.py', 'recover_reasoning_tool_calls'),
        ),
    ),
    AssistFamily(
        'F02', 'Clean leaked protocol text',
        'Recovery and file safety',
        'Related protocol contamination repair; channel-prefix, fused-argument-tail and opener handling retain distinct loss risks.',
        ('A08', 'A30', 'context-30'),
        (
            SourceOwner('cria/massage.py', '_strip_channel'),
            SourceOwner('cria/massage.py', '_recover_fused_call'),
            SourceOwner('cria/writeproxy.py', 'trim_fused_tail'),
        ),
    ),
    AssistFamily(
        'F03', 'Convert arguments to declared tool types',
        'Recovery and file safety',
        'Already one implementation with numeric, boolean and structured-value policies.',
        ('A14', 'A15', 'A16'),
        (
            SourceOwner('cria/massage.py', 'coerce_args'),
        ),
    ),
    AssistFamily(
        'F04', 'Normalize tool names and argument shapes',
        'Recovery and file safety',
        'One tool-interface adaptation family; menu matching, shell/read conventions and envelope decoding are strategies, not independent features.',
        ('A17', 'A18', 'A19', 'A20', 'A21', 'A118', 'A120', 'A123'),
        (
            SourceOwner('cria/massage.py', 'normalize_tool_calls'),
            SourceOwner('cria/toolargs.py', 'parse_args'),
            SourceOwner('cria/shelltool.py', 'shell_args'),
        ),
    ),
    AssistFamily(
        'F05', 'Repair and translate patch formats',
        'Recovery and file safety',
        'One patch adaptation pipeline with format-specific stages; retain exact-edit semantics and risky inferred additions as separate historical contracts.',
        ('A22', 'A23', 'A24', 'A25', 'A26', 'A27', 'A28', 'A29'),
        (
            SourceOwner('cria/massage.py', '_normalize_patch_body'),
            SourceOwner('cria/massage.py', 'lower_edit_file'),
            SourceOwner('cria/massage.py', 'add_file_to_write_file'),
        ),
    ),
    AssistFamily(
        'F06', 'Read imperfect JSON arguments',
        'Recovery and file safety',
        'One shared model-JSON parser and wrapper reader. Complete object literal bytes are protected from protocol/fence stripping; malformed-string recovery and first-nonempty duplicate-key policy remain distinct strategies with their own risks.',
        ('A31', 'A32', 'A119', 'A121'),
        (
            SourceOwner('cria/jsontext.py', 'extract_json_object'),
            SourceOwner('cria/jsontext.py', 'loads'),
            SourceOwner('cria/massage.py', 'repair_tool_args'),
        ),
    ),
    AssistFamily(
        'F07', 'Make historical tool calls wire-compatible',
        'Recovery and file safety',
        'One historical-call integrity family, NOT one policy: lossless malformed-byte wrapping, inferred repair, orphan-result preservation and unanswered-call deletion must keep separate risk histories.',
        ('A33', 'A34', 'context-15', 'parent-wire-unanswered'),
        (
            SourceOwner('cria/massage.py', 'repair_history_tool_args'),
            SourceOwner('cria/contextfloor.py', 'ensure_tool_integrity'),
            SourceOwner('cria/upstream.py', 'Upstream._prep'),
        ),
    ),
    AssistFamily(
        'F08', 'Recover tool-free answer text',
        'Recovery and file safety',
        'One answer-recovery family with finished-reasoning, simpler-answer and longest-payload strategies. Deliberation is not automatically an intended answer.',
        ('A35', 'A36', 'A37'),
        (
            SourceOwner('cria/massage.py', 'recover_reasoning_text'),
            SourceOwner('cria/massage.py', 'coerce_text_answer'),
        ),
    ),
    AssistFamily(
        'F09', 'Keep incomplete actions from executing',
        'Recovery and file safety',
        'One action-safety capability across streamed/buffered consumers and driven recovery. Withholding, error identity and deciding to retry remain separate control stages.',
        ('A38', 'A72', 'A73', 'T25', 'T26', 'T27', 'T28'),
        (
            SourceOwner('cria/generation.py', 'incomplete'),
            SourceOwner('cria/generation.py', 'quarantine_stream'),
            SourceOwner('cria/loop.py', 'guard_truncation'),
            SourceOwner('cria/server.py', 'CriaHandler._translate_out'),
        ),
    ),
    AssistFamily(
        'F10', 'Expose and explain lean tools',
        'Protocol and routing',
        'One model-facing tool-menu family: advertise, select and explain. Menu omission remains visible as a separate risk.',
        ('A39', 'T38', 'T39'),
        (
            SourceOwner('cria/writeproxy.py', 'advertise'),
            SourceOwner('cria/toolmenu.py', 'cheatsheet'),
            SourceOwner('cria/server.py', 'CriaHandler._setup_translation'),
        ),
    ),
    AssistFamily(
        'F11', 'Execute synthetic tools through the harness',
        'Recovery and file safety',
        'One lowering/round-trip family with write/edit/list/web adapters. Atomicity, metadata, matching and native-tool delegation remain explicit contracts.',
        ('A40', 'A41', 'A42', 'A43', 'A44', 'A66', 'A116-fetch', 'A116-search'),
        (
            SourceOwner('cria/writeproxy.py', 'translate_outbound'),
            SourceOwner('cria/writeproxy.py', 'represent_inbound'),
        ),
    ),
    AssistFamily(
        'F12', 'Reject syntax-breaking file replacements',
        'Recovery and file safety',
        'Already a shared regression guard with language parsers and real-error feedback, not eight independent guards. Unknown-before caveats remain.',
        ('A45', 'A46', 'A47', 'A48', 'A49', 'A50', 'A51', 'A52', 'A53'),
        (
            SourceOwner('cria/writeproxy.py', '_VALIDATE_FN'),
            SourceOwner('cria/writeproxy.py', '_write_command'),
            SourceOwner('cria/writeproxy.py', '_edit_command'),
        ),
    ),
    AssistFamily(
        'F13', 'Prepare and validate file-mutation arguments',
        'Recovery and file safety',
        'One shared file-argument preparation and refusal path, with separate whole-write and exact-edit contracts. Absent/null values are not intentional empty strings; real falsy values retain their text. Decoding, protocol debris and candidate safety keep separate policies.',
        ('A54', 'A55', 'A56', 'A57', 'A58', 'A60', 'A61'),
        (
            SourceOwner('cria/writeproxy.py', '_prepare_file_mutation'),
            SourceOwner('cria/writeproxy.py', '_file_mutation_refusal'),
            SourceOwner('cria/writeproxy.py', '_repair_double_escaped'),
            SourceOwner('cria/writeproxy.py', '_protocol_debris'),
            SourceOwner('cria/writeproxy.py', 'translate_outbound'),
        ),
    ),
    AssistFamily(
        'F14', 'Report file I/O and read coverage honestly',
        'Recovery and file safety',
        'One file-read/result contract family: actual bytes/ranges, refusals, cuts and whole-read credit. File conflict explanation is a sibling result policy.',
        ('A59', 'A62', 'A63', 'A64', 'A65', 'A86', 'A87'),
        (
            SourceOwner('cria/writeproxy.py', '_read_command'),
            SourceOwner('cria/writeproxy.py', 'note_harness_cuts'),
            SourceOwner('cria/writeproxy.py', 'represent_inbound'),
            SourceOwner('cria/denial.py', 'read_instead_payload'),
        ),
    ),
    AssistFamily(
        'F15', 'Protect existing content from destructive whole writes',
        'Recovery and file safety',
        'One existing-content protection family with unread-target substitution, fragment hold, landed-removal disclosure and rejected-draft provenance. A useful disclosure does not endorse blocking a first fix.',
        ('A67', 'A68', 'A69', 'A85'),
        (
            SourceOwner('cria/loop.py', 'Loop.shrinking_write_check'),
            SourceOwner('cria/loop.py', 'Loop.unread_target_check'),
            SourceOwner('cria/writeproxy.py', '_held_shrinking_write'),
            SourceOwner('cria/writeproxy.py', '_read_in_place_of_write'),
        ),
    ),
    AssistFamily(
        'F16', 'Turn pasted file text into executed work',
        'Recovery and file safety',
        'One pasted-file/call-less redrive capability. Whole-file recovery, truthful did-not-run feedback and re-driving are distinct stages.',
        ('A70', 'A71', 'J28'),
        (
            SourceOwner('cria/loop.py', 'Loop._recover_text_write'),
            SourceOwner('cria/loop.py', 'unexecuted_write'),
        ),
    ),
    AssistFamily(
        'F17', 'Apply edits in order and report landed changes',
        'Recovery and file safety',
        'One edit execution/feedback family with locking, ordering, exact echo, anchor-miss diagnostics and recovery choices. Aggressive rewrite escalation is a risky policy, not an endorsed default.',
        ('A74', 'A75', 'A76', 'A77', 'A78', 'A79', 'A80', 'A81', 'A82', 'A83', 'A84'),
        (
            SourceOwner('cria/writeproxy.py', '_edit_command'),
            SourceOwner('cria/writeproxy.py', '_edit_sequence'),
            SourceOwner('cria/writeproxy.py', 'render_edit_echo'),
            SourceOwner('cria/editrecovery.py', 'recover'),
        ),
    ),
    AssistFamily(
        'F18', 'Interpret raw tool output',
        'Recovery and file safety',
        'One output interpretation family: color stripping, binary treatment and empty-result explanations have separate loss/attribution risks.',
        ('A88', 'A89', 'A92', 'A93'),
        (
            SourceOwner('cria/writeproxy.py', 'represent_inbound'),
            SourceOwner('cria/writeproxy.py', '_debinarized'),
            SourceOwner('cria/writeproxy.py', '_found_nothing'),
        ),
    ),
    AssistFamily(
        'F19', 'Redact known credentials',
        'Recovery and file safety',
        'Keep separate: confidential payload handling is not generic output cleanup.',
        ('A90',),
        (
            SourceOwner('cria/writeproxy.py', '_scrub'),
        ),
    ),
    AssistFamily(
        'F20', 'Explain dependency and environment failures',
        'Dependencies and research',
        'One grounded dependency/environment advice family with package-resolution and source-search adapters; authoritative tool facts and prescriptions remain distinguishable.',
        ('A91', 'A94', 'A95', 'J56'),
        (
            SourceOwner('cria/writeproxy.py', '_note_missing_dependency'),
            SourceOwner('cria/writeproxy.py', '_note_dependency_search'),
            SourceOwner('cria/loop.py', '_unresolved_deps'),
        ),
    ),
    AssistFamily(
        'F21', 'Gather and retain dependency API evidence',
        'Dependencies and research',
        "One dependency-evidence lifecycle: gather, select, replay/reanchor and permanently withhold. Keep each stage's information/freshness risk, rather than four top-level assists.",
        ('coverage-assist-13', 'A96', 'A97', 'coverage-assist-16'),
        (
            SourceOwner('cria/depsurface.py', 'anchor_state'),
            SourceOwner('cria/depsurface.py', 'is_withheld'),
            SourceOwner('cria/writeproxy.py', '_note_dependency_surface'),
            SourceOwner('cria/writeproxy.py', '_render_dependency_surface'),
        ),
    ),
    AssistFamily(
        'F22', 'Constrain filesystem access',
        'Recovery and file safety',
        'One access-boundary family across explicit tools, shell paths, dependency roots and protected spill/service paths. These adapters are not a containment guarantee.',
        ('A98', 'A99', 'A104', 'A105', 'A106'),
        (
            SourceOwner('cria/dirguard.py', 'path_refusal'),
            SourceOwner('cria/dirguard.py', 'command_refusal'),
            SourceOwner('cria/writeproxy.py', '_external_refusal'),
            SourceOwner('cria/writeproxy.py', '_targets_cria_home'),
            SourceOwner('cria/writeproxy.py', '_under_spill_dir'),
        ),
    ),
    AssistFamily(
        'F23', 'Reject direct root deletion',
        'Recovery and file safety',
        'One narrowly recognized root-deletion protection with direct-command and candidate-source entry points; no claim of computed-target containment.',
        ('A100', 'A115'),
        (
            SourceOwner('cria/dirguard.py', 'root_recursive_delete_refusal'),
            SourceOwner('cria/cleanupsafety.py', 'analyze'),
        ),
    ),
    AssistFamily(
        'F24', 'Keep package installs project-local',
        'Recovery and file safety',
        'One install-boundary capability: refuse shared destinations and offer only grounded local routes.',
        ('A101', 'A102'),
        (
            SourceOwner('cria/dirguard.py', 'install_refusal'),
            SourceOwner('cria/writeproxy.py', '_external_refusal'),
        ),
    ),
    AssistFamily(
        'F25', 'Reject broad process-kill selectors',
        'Recovery and file safety',
        'Different protected resource and proof contract from filesystem deletion; retain as its own capability.',
        ('A103',),
        (
            SourceOwner('cria/dirguard.py', 'kill_refusal'),
        ),
    ),
    AssistFamily(
        'F26', 'Carry workspace surveys through harness tools',
        'Verification and guidance',
        'One workspace observation lifecycle: carrier, survey ingestion, body reconciliation and deferred harness questions. L2+ producer and L4/L5 consumers retain their gates.',
        ('A107', 'J59', 'J61-body', 'J61-demand', 'coverage-assist-18'),
        (
            SourceOwner('cria/wsview.py', 'View.program'),
            SourceOwner('cria/wsview.py', 'strip_survey'),
            SourceOwner('cria/wsview.py', 'View.note_written'),
            SourceOwner('cria/writeproxy.py', 'represent_inbound'),
        ),
    ),
    AssistFamily(
        'F27', 'Clean up owned probe artifacts',
        'Verification and guidance',
        'One owned-artifact cleanup family with workspace litter and external spool adapters. Ownership, location and permission constraints must remain distinct.',
        ('A108', 'J58'),
        (
            SourceOwner('cria/probegate.py', 'sweep_litter'),
            SourceOwner('cria/probegate.py', '_queue_spool_cleanup'),
            SourceOwner('cria/writeproxy.py', '_litter_leg'),
        ),
    ),
    AssistFamily(
        'F28', 'Review source for unsafe filesystem mutations',
        'Recovery and file safety',
        'Already shared analysis/refusal policy with language adapters. Adapter reach and binding an edit refusal to reviewed bytes are details, not independent top-level assists.',
        ('A109', 'A110', 'A111', 'A112-csharp', 'A112-elixir', 'A112-go', 'A112-java', 'A112-js', 'A112-kotlin', 'A112-php', 'A112-ruby', 'A112-rust', 'A112-ts', 'A113-c', 'A113-cpp', 'A113-dart', 'A113-julia', 'A113-lua', 'A113-objc', 'A113-perl', 'A113-ps', 'A113-r', 'A113-swift'),
        (
            SourceOwner('cria/cleanupsafety.py', 'analyze'),
            SourceOwner('cria/cleanupsafety.py', 'review'),
            SourceOwner('cria/cleanup_python.py', ''),
            SourceOwner('cria/cleanup_languages.py', ''),
            SourceOwner('cria/cleanup_extra.py', ''),
        ),
    ),
    AssistFamily(
        'F29', 'Adapt strict role alternation',
        'Recovery and file safety',
        'One model-template role adaptation family; adjacent-item coalescing and system collapse are separate provenance risks and gates, not universally interchangeable.',
        ('A117', 'T12', 'T20'),
        (
            SourceOwner('cria/config.py', 'Role.apply'),
            SourceOwner('cria/massage.py', 'merge_for_alternation'),
            SourceOwner('cria/upstream.py', 'Upstream._prep'),
        ),
    ),
    AssistFamily(
        'F30', 'Track actions that may change files',
        'Verification and guidance',
        'Shared mutation provenance feeds several consumers; distinguish observation from an independent intervention at each consumer.',
        ('A124',),
        (
            SourceOwner('cria/shelltool.py', 'writes_something'),
            SourceOwner('cria/writeproxy.py', 'represent_inbound'),
        ),
    ),
    AssistFamily(
        'F31', 'Keep guard state task-scoped',
        'Verification and guidance',
        'Supporting safety foundation with direct guard-state effects; not another repetition intervention.',
        ('J01',),
        (
            SourceOwner('cria/loop.py', 'LoopStore'),
            SourceOwner('cria/loop.py', 'session_key'),
        ),
    ),
    AssistFamily(
        'F32', 'Require explicit experimental planning consent',
        'Verification and guidance',
        'One opt-in control, separate from planner capabilities and retired mechanisms.',
        ('J02',),
        (
            SourceOwner('cria/config.py', 'PlannerConfig'),
            SourceOwner('cria/server.py', 'CriaServer.__init__'),
        ),
    ),
    AssistFamily(
        'F33', 'Give judges truthful read-only evidence',
        'Verification and guidance',
        'One judge inspection/evidence capability: truth of existence/reach, read tools, seeding, role verdict and bounded closure. No merging unknown existence into absence or forced closure into sufficient inspection.',
        ('J03', 'J04-closure', 'J04-recovery', 'J05', 'J06', 'J07', 'J60', 'coverage-assist-17'),
        (
            SourceOwner('cria/loop.py', '_judge_completion'),
            SourceOwner('cria/groundtruth.py', 'files_for_a_judge'),
            SourceOwner('cria/verifytools.py', 'verdict_tool'),
            SourceOwner('cria/wsview.py', 'View'),
        ),
    ),
    AssistFamily(
        'F34', 'Verify whole-task completion',
        'Verification and guidance',
        'One completion-review lifecycle with primary critic, approval confirmation, scheduled checks, release-state ownership and truthful closing. Stages remain independently inspectable.',
        ('J08', 'J09', 'J10', 'J22', 'J23', 'J26', 'J27', 'J110'),
        (
            SourceOwner('cria/loop.py', 'judge_satisfaction'),
            SourceOwner('cria/loop.py', '_confirm_completion'),
            SourceOwner('cria/loop.py', 'Loop._gate_single_done'),
            SourceOwner('cria/loop.py', 'Loop._periodic_satisfaction'),
            SourceOwner('cria/loop.py', 'satisfaction_done_note'),
        ),
    ),
    AssistFamily(
        'F35', 'Check exact file form',
        'Verification and guidance',
        'One exact-form capability: measure actual bytes and independently extract/check required size and final line break.',
        ('J11', 'J12', 'J13'),
        (
            SourceOwner('cria/loop.py', '_written_file_facts'),
            SourceOwner('cria/loop.py', '_exact_form_blocks_completion'),
            SourceOwner('cria/filefacts.py', 'render'),
        ),
    ),
    AssistFamily(
        'F36', 'Ground completion diagnoses in the original task',
        'Verification and guidance',
        'One missing-output/negative-diagnosis capability with exact quotes, narrow observation and persistent remediation state. These questions are not one interchangeable yes/no verdict.',
        ('J14', 'J15', 'J16', 'J17'),
        (
            SourceOwner('cria/loop.py', 'observe_task_missing_file'),
            SourceOwner('cria/loop.py', '_negative_diagnosis_nudge'),
            SourceOwner('cria/loop.py', 'Loop._observe_missing_file_on_done'),
        ),
    ),
    AssistFamily(
        'F37', 'Recover unreadable judge verdicts without approving',
        'Verification and guidance',
        'One shared critic response pipeline: effective-role cleanup with JSON-literal-safe framing, truncation rejection, public-answer parsing, then negative-only recovery. Preserve distinct verdict keys, inspection reach, raw text, events and caller-owned retries; never salvage a private approval.',
        ('J18', 'J19', 'J20', 'J21'),
        (
            SourceOwner('cria/loop.py', '_critic_verdict'),
            SourceOwner('cria/loop.py', '_satisfaction_verdict'),
            SourceOwner('cria/loop.py', 'Loop._verdict'),
            SourceOwner('cria/loop.py', 'verdict_from_unclosed'),
            SourceOwner('cria/loop.py', 'verdict_from_reasoning'),
            SourceOwner('cria/loop.py', '_fill_missing_verdict_flag'),
            SourceOwner('cria/jsontext.py', 'close_unclosed_object'),
            SourceOwner('cria/jsontext.py', 'strip_reasoning_prefix'),
            SourceOwner('cria/config.py', 'Role.clean_content'),
        ),
    ),
    AssistFamily(
        'F38', 'Bound completion when verification cannot finish',
        'Verification and guidance',
        'One completion-exit family with separately disclosed bounds, absent-route and partial/nonrunning-gate cases; grouping does not endorse every fail-open policy.',
        ('J24', 'J25', 'J43'),
        (
            SourceOwner('cria/loop.py', 'Loop._gate_single_done'),
            SourceOwner('cria/loop.py', 'Loop._reopen_if_unsatisfied'),
            SourceOwner('cria/loop.py', '_satisfaction_blocks_completion'),
        ),
    ),
    AssistFamily(
        'F39', 'Verify optional planner steps',
        'Experimental planning',
        'One experimental step/research-verification capability with probe attribution and web/file evidence adapters; own-write exclusion remains its separate risky policy.',
        ('J30', 'J31', 'J32', 'J105', 'J106-disk', 'J106-web', 'J106-own-write'),
        (
            SourceOwner('cria/loop.py', 'Loop._verify'),
            SourceOwner('cria/loop.py', 'Loop._periodic_step_check'),
            SourceOwner('cria/loop.py', 'Loop._verify_after_probe'),
        ),
        scope='experimental_planning',
    ),
    AssistFamily(
        'F40', 'Select safe language-aware repository checks',
        'Verification and guidance',
        'One discovery/check-selection family with command safety, ranking, syntax/config and name-resolution adapters. Completion probes remain distinct from prewrite regression refusal.',
        ('J33', 'J34', 'J35', 'J36', 'J37'),
        (
            SourceOwner('cria/probediscovery.py', 'discover'),
            SourceOwner('cria/probeclassify.py', ''),
            SourceOwner('cria/proberun.py', 'select_probes'),
            SourceOwner('cria/linterprobe.py', 'py_compile_argv'),
        ),
    ),
    AssistFamily(
        'F41', 'Transport complete probe evidence',
        'Verification and guidance',
        'One probe execution/transport lifecycle: budgets, spool hash/paging, polling/resume and legacy format admission. Unknown/incomplete is never clean.',
        ('J38', 'J39', 'J40', 'J41', 'A125'),
        (
            SourceOwner('cria/proberun.py', 'compose_probe_command'),
            SourceOwner('cria/probegate.py', 'ingest_transport'),
            SourceOwner('cria/probegate.py', 'fail_transport'),
            SourceOwner('cria/loop.py', 'guard_gate_transport'),
        ),
    ),
    AssistFamily(
        'F42', 'Interpret repository check results',
        'Verification and guidance',
        'One check-evidence interpretation/freshness family: authoritative event state, diagnostic adapters, exact-line selection, digest, ages and newer-run precedence. Distinct carriers keep their provenance.',
        ('J42', 'J44', 'J45', 'J46', 'J47', 'J48', 'J62', 'context-53'),
        (
            SourceOwner('cria/probegate.py', 'interpret_gate'),
            SourceOwner('cria/probeparse.py', ''),
            SourceOwner('cria/proberun.py', 'completion_probe_digest'),
            SourceOwner('cria/loop.py', 'record_gate_state'),
            SourceOwner('cria/loop.py', '_checks_superseded_by_coder_run'),
        ),
    ),
    AssistFamily(
        'F43', 'Require task-relevant test participation',
        'Verification and guidance',
        'One participation capability with phase/source/executable-boundary evidence, task-required brake and factual regression/network disclosures. A mapping is not execution.',
        ('J49', 'J50', 'J51', 'J52', 'J53', 'J54', 'J55'),
        (
            SourceOwner('cria/participation.py', ''),
            SourceOwner('cria/loop.py', '_test_participation_blocks_completion'),
            SourceOwner('cria/probegate.py', 'gate_passing_tests'),
            SourceOwner('cria/probediscovery.py', 'declared_test_source_paths'),
        ),
    ),
    AssistFamily(
        'F44', 'Detect stalled or repeated work',
        'Verification and guidance',
        'One stuck-work intervention family with repetition/refusal/rewrite/stall observations and fresh-probe-before-steer ordering. Preserve landed-write correction and each trigger.',
        ('J63', 'J64', 'J65', 'J66', 'J67'),
        (
            SourceOwner('cria/loop.py', 'guard_intervene'),
            SourceOwner('cria/loop.py', 'guard_track_write_streak'),
            SourceOwner('cria/loop.py', '_note_write_results'),
            SourceOwner('cria/loop.py', 'track_gate_progress'),
        ),
    ),
    AssistFamily(
        'F45', 'Author a grounded next action',
        'Verification and guidance',
        'One next-action authoring lifecycle with actual checker facts, second look, answer recovery and absent/declined-reasoner policy. Canned fallback remains a historically lower-rated policy.',
        ('J68', 'J69', 'J70', 'J71'),
        (
            SourceOwner('cria/loop.py', 'author_steer'),
            SourceOwner('cria/loop.py', 'author_redirect'),
            SourceOwner('cria/loop.py', 'guard_probe_steer'),
        ),
    ),
    AssistFamily(
        'F46', 'Vet proposed next actions against evidence',
        'Verification and guidance',
        'One whole-action vetting capability with claim-specific provenance checks; path/symbol/version/URL/field/line/auth claims are criteria, not ten independent top-level assists.',
        ('J72', 'J73', 'J74', 'J75', 'J76', 'J77', 'J78', 'J79', 'J80', 'J81'),
        (
            SourceOwner('cria/loop.py', '_vet_steer'),
            SourceOwner('cria/loop.py', '_diagnostic_action_verdict'),
            SourceOwner('cria/urlgrounding.py', ''),
        ),
    ),
    AssistFamily(
        'F47', 'Reanchor declared dependency test contracts',
        'Verification and guidance',
        'One grounded environment/runner reset family with JavaScript runner and Go module-state adapters; preserve exact ecosystem gates and independent judgments.',
        ('J83', 'J84'),
        (
            SourceOwner('cria/loop.py', '_configured_js_test_failure'),
            SourceOwner('cria/loop.py', 'module_state_steer'),
            SourceOwner('cria/prompts/runner_reset.txt', ''),
            SourceOwner('cria/prompts/module_state_reset.txt', ''),
        ),
    ),
    AssistFamily(
        'F48', 'Stop degenerate or empty generation',
        'Verification and guidance',
        'One generation backstop/recovery family with reasoning/repetition/empty/near-window detectors. Readable-frame callbacks and truly silent HTTP sockets remain different observable paths.',
        ('J85', 'J86', 'J87', 'J88', 'J89', 'J90', 'J91', 'T24'),
        (
            SourceOwner('cria/rumination.py', 'Detector'),
            SourceOwner('cria/rumination.py', 'degenerate_wide'),
            SourceOwner('cria/upstream.py', 'Upstream.chat_watched'),
            SourceOwner('cria/loop.py', 'grounded_rumination_step'),
        ),
    ),
    AssistFamily(
        'F49', 'Resume after context loss',
        'Context and memory',
        'One handoff-continuation capability: writer/retry, attribution, rejected-prose ledger, truthful canned and reasoned continuation. Generated claims are not verified work.',
        ('J93', 'J94', 'context-31', 'context-51', 'context-52'),
        (
            SourceOwner('cria/server.py', '_compaction_body'),
            SourceOwner('cria/server.py', '_harden_compaction_reply'),
            SourceOwner('cria/loop.py', 'Loop._reasoned_reanchor'),
            SourceOwner('cria/selfcompact.py', 'work_ledger'),
        ),
    ),
    AssistFamily(
        'F50', 'Gather and maintain optional plans',
        'Experimental planning',
        'One explicitly enabled planning lifecycle with gather, coverage/readiness, path/tool validation, tail revision and boundary context. Grouping does not implicitly enable it.',
        ('J95', 'J96', 'J97', 'J98', 'J99', 'J100', 'J101-path', 'J101-tool', 'J102', 'J103', 'context-26', 'context-38', 'T93', 'T94'),
        (
            SourceOwner('cria/planner.py', 'Planner.plan_for'),
            SourceOwner('cria/planner.py', 'Planner._gather_and_plan'),
            SourceOwner('cria/planner_tools.py', 'execute_tool'),
            SourceOwner('cria/loop.py', 'Loop._replan_tail'),
        ),
        scope='experimental_planning',
    ),
    AssistFamily(
        'F51', 'Guide and limit repeated web research',
        'Dependencies and research',
        'One research-steering family: exact/near repeat policy, URL substitution, preserved-query advice, semantic release, failures and spilled-read poisoning. Denial and persistent poisoning remain separately visible risks; planner path stays opt-in.',
        ('J104', 'J111', 'J112', 'J113', 'J114', 'T64', 'T66', 'T67', 'T68', 'T69', 'T70', 'T79'),
        (
            SourceOwner('cria/webfetch.py', 'gate_search'),
            SourceOwner('cria/webfetch.py', 'fetch_nav'),
            SourceOwner('cria/loop.py', 'guard_search_query'),
            SourceOwner('cria/loop.py', 'judge_rehunt'),
            SourceOwner('cria/loop.py', 'judge_search'),
            SourceOwner('cria/planner_tools.py', 'gate_search'),
        ),
    ),
    AssistFamily(
        'F52', 'Present earlier work as completion evidence',
        'Context and memory',
        'One action/memory provenance family. Structured did-not-run facts and unverified summary claims must not be promoted to the same authority merely by grouping them.',
        ('J107', 'context-49', 'context-61'),
        (
            SourceOwner('cria/loop.py', '_satisfaction_evidence'),
            SourceOwner('cria/loop.py', '_work_log'),
            SourceOwner('cria/loop.py', '_mark_own_notes'),
        ),
    ),
    AssistFamily(
        'F53', 'Carry durable dependency refusal and success observations',
        'Verification and guidance',
        'One ordered resolver-observation lifecycle: refusal history plus exact later-success supersession. History is not deleted when current state changes.',
        ('reconcile-M09', 'reconcile-M10'),
        (
            SourceOwner('cria/refusalledger.py', 'refusal_events'),
            SourceOwner('cria/refusalledger.py', '_supersedes'),
            SourceOwner('cria/loop.py', '_session_refusals'),
        ),
    ),
    AssistFamily(
        'F54', 'Classify and route a task',
        'Protocol and routing',
        'One classification/routing lifecycle with task selection, cache, enum handling, retry/fallback, auxiliary bypass and configured route admission. Defaults and fallback risks remain explicit.',
        ('parent-classify-task', 'parent-classify-selection', 'parent-classify-cache', 'parent-classify-enums', 'coverage-assist-01', 'coverage-assist-02', 'coverage-assist-03', 'T21'),
        (
            SourceOwner('cria/classify.py', 'Classifier.classify'),
            SourceOwner('cria/routing.py', 'Router'),
            SourceOwner('cria/server.py', 'CriaHandler._classify'),
        ),
    ),
    AssistFamily(
        'F55', 'Measure context capacity and reserve answer room',
        'Context and memory',
        'One context sizing/refit/retry lifecycle with identity discovery, authoritative window/density, input-aware reserve and original-input fit. Retrying is allowed only by its own byte-change/provenance contracts.',
        ('T01', 'T02', 'T03', 'T04', 'T05', 'T06', 'T07', 'context-02', 'context-06'),
        (
            SourceOwner('cria/upstream.py', 'Upstream._prep'),
            SourceOwner('cria/upstream.py', 'Upstream._overflow_refit'),
            SourceOwner('cria/upstream.py', 'Upstream._open_with_refit'),
            SourceOwner('cria/contextfloor.py', 'fit'),
            SourceOwner('cria/tokenratio.py', 'record'),
        ),
    ),
    AssistFamily(
        'F56', 'Prepare private wire metadata and prompt substitutions',
        'Context and memory',
        'One wire-envelope hygiene family with private-hint removal, producer-owned plumbing removal, inert substitutions and uncapped evidence naming. Each producer boundary remains explicit.',
        ('T08', 'T15', 'coverage-assist-33', 'reconcile-M11', 'context-33'),
        (
            SourceOwner('cria/modelview.py', 'wire_messages'),
            SourceOwner('cria/upstream.py', 'Upstream._prep'),
            SourceOwner('cria/bodykeys.py', ''),
            SourceOwner('cria/prompts/__init__.py', 'fill'),
        ),
    ),
    AssistFamily(
        'F57', 'Translate configured reasoning conventions',
        'Context and memory',
        'One served-template/role reasoning adaptation family; sampling and no-think directive do not demonstrate better reasoning.',
        ('T17', 'T18', 'T19'),
        (
            SourceOwner('cria/config.py', 'Role.apply'),
            SourceOwner('cria/reasoning.py', 'detect_served_style'),
            SourceOwner('cria/upstream.py', 'Upstream._reconcile_reasoning_convention'),
        ),
    ),
    AssistFamily(
        'F58', 'Retry transient upstream failures',
        'Protocol and routing',
        'Separate from known context-overflow resend controls: different failure authority and retry permission.',
        ('T22',),
        (
            SourceOwner('cria/upstream.py', 'Upstream.chat'),
            SourceOwner('cria/failover.py', 'Failure'),
        ),
    ),
    AssistFamily(
        'F59', 'Translate the Responses API without losing intent',
        'Protocol and routing',
        'One API bridge with message/control/argument/event adapters. Unsupported-item and capability omissions remain historically lower-rated policies, not hidden by byte-exact paths.',
        ('T29', 'T30', 'T31', 'T32', 'T33', 'T34'),
        (
            SourceOwner('cria/responses.py', 'to_chat_body'),
            SourceOwner('cria/responses.py', 'body_events'),
            SourceOwner('cria/server.py', 'CriaHandler._handle_responses'),
            SourceOwner('cria/server.py', 'CriaHandler._respond_responses_stream'),
        ),
    ),
    AssistFamily(
        'F60', 'Keep streams alive and drain shutdown',
        'Protocol and routing',
        'One stream lifecycle infrastructure family with human/client keepalive and shutdown drain; not coding-usefulness evidence.',
        ('T36', 'T37'),
        (
            SourceOwner('cria/heartbeat.py', 'Heartbeat'),
            SourceOwner('cria/server.py', 'CriaServer.drain_streams'),
            SourceOwner('cria/__main__.py', 'main'),
        ),
    ),
    AssistFamily(
        'F61', 'Fetch and reduce external documents',
        'Dependencies and research',
        'One fetch/document representation lifecycle with transport, binary, HTML/JSON/YAML, raw-source and cache adapters. Lossy caps and structural transformation remain separately documented.',
        ('T42', 'T43', 'T44', 'T45', 'T46', 'T47', 'T48', 'T50', 'T51', 'context-10'),
        (
            SourceOwner('cria/webfetch.py', 'fetch'),
            SourceOwner('cria/webfetch.py', 'reduce_for_cache'),
            SourceOwner('cria/content_reduce.py', 'content_reduce'),
        ),
    ),
    AssistFamily(
        'F62', 'Navigate documents and expose API facts',
        'Dependencies and research',
        'One document navigation/API-discovery family with text/JSON find, paging, route/schema extraction and MCP/GraphQL adapters. Extra requests and synthesized schema claims remain explicit.',
        ('T52', 'T53', 'T54', 'T55', 'T56', 'T57', 'T58', 'T75', 'T76', 'T77'),
        (
            SourceOwner('cria/webfetch.py', 'find_json'),
            SourceOwner('cria/webfetch.py', 'outline_for_url'),
            SourceOwner('cria/webfetch.py', '_ref_map'),
            SourceOwner('cria/apidiscovery.py', 'discover'),
        ),
    ),
    AssistFamily(
        'F63', 'Spill oversized research for harness reads',
        'Dependencies and research',
        'One spill/read-navigation capability with fetch/search/planner adapters, filenames/view gating, refusal outlines and reach disclosure. Command-size clipping remains a historically lower-rated policy.',
        ('T59', 'T60', 'T61', 'T62', 'T63', 'T65', 'T73', 'T78', 'T92', 'context-62'),
        (
            SourceOwner('cria/webfetch.py', 'note_fetch_spill'),
            SourceOwner('cria/webfetch.py', 'search_spill_name'),
            SourceOwner('cria/writeproxy.py', '_spill_command'),
            SourceOwner('cria/loop.py', '_label_spill_entries'),
            SourceOwner('cria/planner_tools.py', '_web_fetch'),
        ),
    ),
    AssistFamily(
        'F64', 'Adapt native search tool aliases',
        'Dependencies and research',
        'A native search interface adapter, separate from synthetic search execution and semantic research steering.',
        ('T74',),
        (
            SourceOwner('cria/writeproxy.py', 'native_search_name'),
            SourceOwner('cria/server.py', 'CriaHandler._setup_translation'),
        ),
    ),
    AssistFamily(
        'F65', 'Produce backend-valid tool turns',
        'Protocol and routing',
        'One native integration family with template dialect, serial grammar, named choice, backend no-action carrier and stop-cause evidence. Source artifacts are not proof of current deployment.',
        ('T80', 'T81', 'T82', 'T83', 'T84'),
        (
            SourceOwner('cria/prompts/localai_functioncall_chat.jinja.txt', ''),
            SourceOwner('cria/prompts/localai_functioncall_answer_tool.txt', ''),
            SourceOwner('scripts/backend-patches/8345-serial-tool-call.patch', ''),
            SourceOwner('scripts/backend-patches/8345-named-tool-choice.patch', ''),
            SourceOwner('scripts/backend-patches/8345-no-action-tool.patch', ''),
            SourceOwner('scripts/backend-patches/8345-generation-stop.patch', ''),
        ),
        scope='native_artifacts',
    ),
    AssistFamily(
        'F66', 'Bridge CLI providers',
        'Protocol and routing',
        'One optional CLI-provider bridge with execution ownership, prompt selection, resume and malformed-result policy. These are architectural boundary risks, not four separately useful assists.',
        ('T88', 'T89', 'T90', 'T91'),
        (
            SourceOwner('cria/claude_cli.py', 'ClaudeCliProvider._invoke'),
            SourceOwner('cria/claude_cli.py', '_parse_claude_json'),
            SourceOwner('cria/routing.py', 'Router._build_cli'),
        ),
        scope='configured_cli_provider',
    ),
    AssistFamily(
        'F67', 'Protect task authority during context shaping',
        'Context and memory',
        'One authority-preservation/frame-shaping family. Protected original task/current question and risky caller/tool-instruction shedding retain separate risk histories; grouping does not justify destroying authority.',
        ('context-07', 'context-08', 'context-11', 'context-13', 'context-25', 'context-27', 'context-28', 'context-60', 'context-63'),
        (
            SourceOwner('cria/contextfloor.py', '_protected_mask'),
            SourceOwner('cria/contextfloor.py', '_reduce_caller_spans'),
            SourceOwner('cria/contextfloor.py', '_compress_tools'),
            SourceOwner('cria/loop.py', '_frame_for_item'),
            SourceOwner('cria/loop.py', 'reframe_preamble'),
        ),
    ),
    AssistFamily(
        'F68', 'Reduce old history with truthful state',
        'Context and memory',
        'One history-floor lifecycle: remove droppable history, maintain labelled state and handle floor-created orphan pairs/repeated digest cycles. Distinct from fitting-body wire repair.',
        ('context-12', 'context-14', 'context-16'),
        (
            SourceOwner('cria/contextfloor.py', '_drop_oldest'),
            SourceOwner('cria/contextfloor.py', '_compacted_note'),
            SourceOwner('cria/contextfloor.py', 'fit'),
        ),
    ),
    AssistFamily(
        'F69', 'Fold repeated context evidence',
        'Context and memory',
        'One deduplication family with whole-message, checker, fetch, read-only-call and action-log adapters. Normalization and latest-repeat suppression remain risky distinct policies.',
        ('context-17', 'context-18', 'context-19', 'context-20', 'context-21', 'context-22', 'context-46'),
        (
            SourceOwner('cria/dedup.py', 'fold_repeated_runs'),
            SourceOwner('cria/dedup.py', 'fold_repeated_actions'),
            SourceOwner('cria/focustrim.py', '_collapse_duplicates'),
            SourceOwner('cria/modelview.py', 'fold_evidence'),
            SourceOwner('cria/upstream.py', 'Upstream._prep'),
        ),
    ),
    AssistFamily(
        'F70', 'Compact conversation memory without changing task or facts',
        'Context and memory',
        'One compaction lifecycle: composition, write/refold, independent retrospective/scope/fidelity validation, echo rejection and retry throttle. Preserve three independent questions rather than merging verdict criteria.',
        ('context-35', 'context-36', 'context-37', 'context-39', 'context-40', 'context-41', 'context-42', 'context-43'),
        (
            SourceOwner('cria/selfcompact.py', 'compact'),
            SourceOwner('cria/selfcompact.py', 'compaction_request_parts'),
            SourceOwner('cria/loop.py', 'Loop._self_compact'),
            SourceOwner('cria/server.py', '_harden_compaction_reply'),
        ),
    ),
    AssistFamily(
        'F71', 'Prepare reducible judge evidence',
        'Context and memory',
        'One judge-evidence framing family with whole-line composition, transcript defanging and oversized summarization. Summary judgments and loss limits remain distinct.',
        ('context-45', 'context-47', 'context-48'),
        (
            SourceOwner('cria/loop.py', '_evidence_blocks'),
            SourceOwner('cria/loop.py', '_judge_completion'),
            SourceOwner('cria/loop.py', 'summarize'),
            SourceOwner('cria/selfcompact.py', 'serialize'),
        ),
    ),
    AssistFamily(
        'F72', 'Restore current workspace facts after context loss',
        'Context and memory',
        'One restoration/provenance capability: fresh inventory/current text, named reduction stand-in, sent-body read credit, paired-result footer and dated ledger. Sent credit is not a durable ledger or a footer.',
        ('context-09', 'context-32', 'context-54', 'context-55', 'context-56', 'context-57', 'context-58'),
        (
            SourceOwner('cria/loop.py', '_restored_text_message'),
            SourceOwner('cria/groundtruth.py', 'workspace_inventory'),
            SourceOwner('cria/modelview.py', 'settle_restored_text'),
            SourceOwner('cria/modelview.py', 'retained_results_truth'),
            SourceOwner('cria/upstream.py', 'Upstream._prep'),
        ),
    ),
    AssistFamily(
        'F73', 'Suppress or substitute historical tool payloads',
        'Context and memory',
        'One lossy history-substitution family. Keep failure squashing, superseded writes and landed-payload substitution explicitly historically lower-rated, rather than endorsing them as harmless compression.',
        ('context-23', 'context-24', 'context-44'),
        (
            SourceOwner('cria/focustrim.py', '_drop_superseded_writes'),
            SourceOwner('cria/focustrim.py', '_repeat_failed'),
            SourceOwner('cria/modelview.py', 'superseded_writes_truth'),
            SourceOwner('cria/selfcompact.py', '_last_write_index_by_path'),
        ),
    ),
    AssistFamily(
        'F74', 'Sanitize replayed internal transcripts',
        'Context and memory',
        'One inbound transcript-hygiene family with marker/fence/artifact rules. Plan-artifact deletion is not the same as removing a human display annotation.',
        ('context-29-status', 'context-29-reasoning', 'context-29-plan'),
        (
            SourceOwner('cria/indicators.py', 'strip_history'),
            SourceOwner('cria/loop.py', '_strip_cria_file_ops'),
            SourceOwner('cria/server.py', 'CriaHandler._strip_and_reframe_inbound'),
        ),
    ),
    AssistFamily(
        'F75', 'Report model-visible usage',
        'Context and memory',
        'A harness-facing usage boundary, not another context-fitting policy.',
        ('context-34',),
        (
            SourceOwner('cria/modelview.py', 'visible_tokens'),
            SourceOwner('cria/loop.py', 'Loop.visible_context_tokens'),
            SourceOwner('cria/server.py', '_incoming_ctx_tokens'),
        ),
    ),
    AssistFamily(
        'F76', 'Carry finished-work briefings into follow-ups',
        'Context and memory',
        'Separate from rejected-handoff recovery: closing-time generated memory with its own validation/provenance limits.',
        ('context-59',),
        (
            SourceOwner('cria/loop.py', 'Loop._compact_done'),
            SourceOwner('cria/loop.py', '_briefing_from_history'),
        ),
    ),
)

BY_ID = MappingProxyType({family.id: family for family in FAMILIES})
DETAIL_TO_FAMILY = MappingProxyType({detail: family.id for family in FAMILIES for detail in family.details})
