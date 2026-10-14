# The 76 assist families

**Canonical implementation map:** [`cria/assistfamilies.py`](../../cria/assistfamilies.py). This generated view names capabilities and their principal code owners, not every conditional branch, parser adapter, caller or safety criterion as another assist.

- **76 families, not 409 independent features.** The 409 original detail identities remain a historical contract map in [`detail-history.json`](detail-history.json). Each belongs to one family.
- **Grouping is not permission to collapse policies.** Keep different authority boundaries, gates, refusal rules and information risks separate inside a family. Principal owners are navigation bindings, not an exhaustive call graph or proof of necessity/usefulness.
- **No family score ranges.** Historical detail scores describe the frozen 53d9d541c0999bcca31b4a02fb0ae8c20589ea28 review only. They are not ratings of today's code, averages, confidence ranges or measured usefulness. Historical risks remain in the detail map.
- **No deployment claim.** This is the checked-in implementation taxonomy; an installed service, native artifact or inherited pending source package needs its own acceptance.
- **Planning remains OFF.** F32 owns explicit consent; F39 and F50 describe experimental planner capabilities. Metadata does not enable an assist, select a model, run a tool or create a wrapper.

## Browse by capability

### Recovery and file safety

| ID | Family |
|---|---|
| F01 | [Recover text-encoded tool calls](#f01) |
| F02 | [Clean leaked protocol text](#f02) |
| F03 | [Convert arguments to declared tool types](#f03) |
| F04 | [Normalize tool names and argument shapes](#f04) |
| F05 | [Repair and translate patch formats](#f05) |
| F06 | [Read imperfect JSON arguments](#f06) |
| F07 | [Make historical tool calls wire-compatible](#f07) |
| F08 | [Recover tool-free answer text](#f08) |
| F09 | [Keep incomplete actions from executing](#f09) |
| F11 | [Execute synthetic tools through the harness](#f11) |
| F12 | [Reject syntax-breaking file replacements](#f12) |
| F13 | [Prepare and validate file-mutation arguments](#f13) |
| F14 | [Report file I/O and read coverage honestly](#f14) |
| F15 | [Protect existing content from destructive whole writes](#f15) |
| F16 | [Turn pasted file text into executed work](#f16) |
| F17 | [Apply edits in order and report landed changes](#f17) |
| F18 | [Interpret raw tool output](#f18) |
| F19 | [Redact known credentials](#f19) |
| F22 | [Constrain filesystem access](#f22) |
| F23 | [Reject direct root deletion](#f23) |
| F24 | [Keep package installs project-local](#f24) |
| F25 | [Reject broad process-kill selectors](#f25) |
| F28 | [Review source for unsafe filesystem mutations](#f28) |
| F29 | [Adapt strict role alternation](#f29) |

### Protocol and routing

| ID | Family |
|---|---|
| F10 | [Expose and explain lean tools](#f10) |
| F54 | [Classify and route a task](#f54) |
| F58 | [Retry transient upstream failures](#f58) |
| F59 | [Translate the Responses API without losing intent](#f59) |
| F60 | [Keep streams alive and drain shutdown](#f60) |
| F65 | [Produce backend-valid tool turns](#f65) |
| F66 | [Bridge CLI providers](#f66) |

### Dependencies and research

| ID | Family |
|---|---|
| F20 | [Explain dependency and environment failures](#f20) |
| F21 | [Gather and retain dependency API evidence](#f21) |
| F51 | [Guide and limit repeated web research](#f51) |
| F61 | [Fetch and reduce external documents](#f61) |
| F62 | [Navigate documents and expose API facts](#f62) |
| F63 | [Spill oversized research for harness reads](#f63) |
| F64 | [Adapt native search tool aliases](#f64) |

### Verification and guidance

| ID | Family |
|---|---|
| F26 | [Carry workspace surveys through harness tools](#f26) |
| F27 | [Clean up owned probe artifacts](#f27) |
| F30 | [Track actions that may change files](#f30) |
| F31 | [Keep guard state task-scoped](#f31) |
| F32 | [Require explicit experimental planning consent](#f32) |
| F33 | [Give judges truthful read-only evidence](#f33) |
| F34 | [Verify whole-task completion](#f34) |
| F35 | [Check exact file form](#f35) |
| F36 | [Ground completion diagnoses in the original task](#f36) |
| F37 | [Recover unreadable judge verdicts without approving](#f37) |
| F38 | [Bound completion when verification cannot finish](#f38) |
| F40 | [Select safe language-aware repository checks](#f40) |
| F41 | [Transport complete probe evidence](#f41) |
| F42 | [Interpret repository check results](#f42) |
| F43 | [Require task-relevant test participation](#f43) |
| F44 | [Detect stalled or repeated work](#f44) |
| F45 | [Author a grounded next action](#f45) |
| F46 | [Vet proposed next actions against evidence](#f46) |
| F47 | [Reanchor declared dependency test contracts](#f47) |
| F48 | [Stop degenerate or empty generation](#f48) |
| F53 | [Carry durable dependency refusal and success observations](#f53) |

### Experimental planning

| ID | Family |
|---|---|
| F39 | [Verify optional planner steps](#f39) |
| F50 | [Gather and maintain optional plans](#f50) |

### Context and memory

| ID | Family |
|---|---|
| F49 | [Resume after context loss](#f49) |
| F52 | [Present earlier work as completion evidence](#f52) |
| F55 | [Measure context capacity and reserve answer room](#f55) |
| F56 | [Prepare private wire metadata and prompt substitutions](#f56) |
| F57 | [Translate configured reasoning conventions](#f57) |
| F67 | [Protect task authority during context shaping](#f67) |
| F68 | [Reduce old history with truthful state](#f68) |
| F69 | [Fold repeated context evidence](#f69) |
| F70 | [Compact conversation memory without changing task or facts](#f70) |
| F71 | [Prepare reducible judge evidence](#f71) |
| F72 | [Restore current workspace facts after context loss](#f72) |
| F73 | [Suppress or substitute historical tool payloads](#f73) |
| F74 | [Sanitize replayed internal transcripts](#f74) |
| F75 | [Report model-visible usage](#f75) |
| F76 | [Carry finished-work briefings into follow-ups](#f76) |

## Contracts and principal owners

<a id="f01"></a>
### F01 — Recover text-encoded tool calls

One recovery family with dialect/channel adapters and explicit admissibility rules; not permission to promote every apparent call.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/massage.py:recover_leaked_tool_calls`](../../cria/massage.py#L1225)
- [`cria/massage.py:recover_reasoning_tool_calls`](../../cria/massage.py#L1688)

**Historical contract IDs:** `A01`, `A02`, `A03`, `A04`, `A05`, `A06`, `A07`, `A09`, `A10`, `A11`, `A12`, `A13`.

<a id="f02"></a>
### F02 — Clean leaked protocol text

Related protocol contamination repair; channel-prefix, fused-argument-tail and opener handling retain distinct loss risks.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/massage.py:_strip_channel`](../../cria/massage.py#L1796)
- [`cria/massage.py:_recover_fused_call`](../../cria/massage.py#L128)
- [`cria/writeproxy.py:trim_fused_tail`](../../cria/writeproxy.py#L86)

**Historical contract IDs:** `A08`, `A30`, `context-30`.

<a id="f03"></a>
### F03 — Convert arguments to declared tool types

Already one implementation with numeric, boolean and structured-value policies.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/massage.py:coerce_args`](../../cria/massage.py#L626)

**Historical contract IDs:** `A14`, `A15`, `A16`.

<a id="f04"></a>
### F04 — Normalize tool names and argument shapes

One tool-interface adaptation family; menu matching, shell/read conventions and envelope decoding are strategies, not independent features.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/massage.py:normalize_tool_calls`](../../cria/massage.py#L399)
- [`cria/toolargs.py:parse_args`](../../cria/toolargs.py#L20)
- [`cria/shelltool.py:shell_args`](../../cria/shelltool.py#L54)

**Historical contract IDs:** `A17`, `A18`, `A19`, `A20`, `A21`, `A118`, `A120`, `A123`.

<a id="f05"></a>
### F05 — Repair and translate patch formats

One patch adaptation pipeline with format-specific stages; retain exact-edit semantics and risky inferred additions as separate historical contracts.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/massage.py:_normalize_patch_body`](../../cria/massage.py#L2455)
- [`cria/massage.py:lower_edit_file`](../../cria/massage.py#L343)
- [`cria/massage.py:add_file_to_write_file`](../../cria/massage.py#L564)

**Historical contract IDs:** `A22`, `A23`, `A24`, `A25`, `A26`, `A27`, `A28`, `A29`.

<a id="f06"></a>
### F06 — Read imperfect JSON arguments

One shared model-JSON parser and wrapper reader. Complete object literal bytes are protected from protocol/fence stripping; malformed-string recovery and first-nonempty duplicate-key policy remain distinct strategies with their own risks.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/jsontext.py:extract_json_object`](../../cria/jsontext.py#L73)
- [`cria/jsontext.py:loads`](../../cria/jsontext.py#L238)
- [`cria/massage.py:repair_tool_args`](../../cria/massage.py#L2132)

**Historical contract IDs:** `A31`, `A32`, `A119`, `A121`.

<a id="f07"></a>
### F07 — Make historical tool calls wire-compatible

One historical-call integrity family, NOT one policy: lossless malformed-byte wrapping, inferred repair, orphan-result preservation and unanswered-call deletion must keep separate risk histories.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/massage.py:repair_history_tool_args`](../../cria/massage.py#L2192)
- [`cria/contextfloor.py:ensure_tool_integrity`](../../cria/contextfloor.py#L494)
- [`cria/upstream.py:Upstream._prep`](../../cria/upstream.py#L373)

**Historical contract IDs:** `A33`, `A34`, `context-15`, `parent-wire-unanswered`.

<a id="f08"></a>
### F08 — Recover tool-free answer text

One answer-recovery family with finished-reasoning, simpler-answer and longest-payload strategies. Deliberation is not automatically an intended answer.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/massage.py:recover_reasoning_text`](../../cria/massage.py#L250)
- [`cria/massage.py:coerce_text_answer`](../../cria/massage.py#L298)

**Historical contract IDs:** `A35`, `A36`, `A37`.

<a id="f09"></a>
### F09 — Keep incomplete actions from executing

One action-safety capability across streamed/buffered consumers and driven recovery. Withholding, error identity and deciding to retry remain separate control stages.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/generation.py:incomplete`](../../cria/generation.py#L24)
- [`cria/generation.py:quarantine_stream`](../../cria/generation.py#L75)
- [`cria/loop.py:guard_truncation`](../../cria/loop.py#L13198)
- [`cria/server.py:CriaHandler._translate_out`](../../cria/server.py#L1342)

**Historical contract IDs:** `A38`, `A72`, `A73`, `T25`, `T26`, `T27`, `T28`.

<a id="f10"></a>
### F10 — Expose and explain lean tools

One model-facing tool-menu family: advertise, select and explain. Menu omission remains visible as a separate risk.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/writeproxy.py:advertise`](../../cria/writeproxy.py#L436)
- [`cria/toolmenu.py:cheatsheet`](../../cria/toolmenu.py#L123)
- [`cria/server.py:CriaHandler._setup_translation`](../../cria/server.py#L1251)

**Historical contract IDs:** `A39`, `T38`, `T39`.

<a id="f11"></a>
### F11 — Execute synthetic tools through the harness

One lowering/round-trip family with write/edit/list/web adapters. Atomicity, metadata, matching and native-tool delegation remain explicit contracts.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/writeproxy.py:translate_outbound`](../../cria/writeproxy.py#L1690)
- [`cria/writeproxy.py:represent_inbound`](../../cria/writeproxy.py#L2347)

**Historical contract IDs:** `A40`, `A41`, `A42`, `A43`, `A44`, `A66`, `A116-fetch`, `A116-search`.

<a id="f12"></a>
### F12 — Reject syntax-breaking file replacements

Already a shared regression guard with language parsers and real-error feedback, not eight independent guards. Unknown-before caveats remain.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/writeproxy.py:_VALIDATE_FN`](../../cria/writeproxy.py#L521)
- [`cria/writeproxy.py:_write_command`](../../cria/writeproxy.py#L667)
- [`cria/writeproxy.py:_edit_command`](../../cria/writeproxy.py#L1007)

**Historical contract IDs:** `A45`, `A46`, `A47`, `A48`, `A49`, `A50`, `A51`, `A52`, `A53`.

<a id="f13"></a>
### F13 — Prepare and validate file-mutation arguments

One shared file-argument preparation and refusal path, with separate whole-write and exact-edit contracts. Absent/null values are not intentional empty strings; real falsy values retain their text. Decoding, protocol debris and candidate safety keep separate policies.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/writeproxy.py:_prepare_file_mutation`](../../cria/writeproxy.py#L171)
- [`cria/writeproxy.py:_file_mutation_refusal`](../../cria/writeproxy.py#L198)
- [`cria/writeproxy.py:_repair_double_escaped`](../../cria/writeproxy.py#L2961)
- [`cria/writeproxy.py:_protocol_debris`](../../cria/writeproxy.py#L72)
- [`cria/writeproxy.py:translate_outbound`](../../cria/writeproxy.py#L1690)

**Historical contract IDs:** `A54`, `A55`, `A56`, `A57`, `A58`, `A60`, `A61`.

<a id="f14"></a>
### F14 — Report file I/O and read coverage honestly

One file-read/result contract family: actual bytes/ranges, refusals, cuts and whole-read credit. File conflict explanation is a sibling result policy.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/writeproxy.py:_read_command`](../../cria/writeproxy.py#L1168)
- [`cria/writeproxy.py:note_harness_cuts`](../../cria/writeproxy.py#L2310)
- [`cria/writeproxy.py:represent_inbound`](../../cria/writeproxy.py#L2347)
- [`cria/denial.py:read_instead_payload`](../../cria/denial.py#L50)

**Historical contract IDs:** `A59`, `A62`, `A63`, `A64`, `A65`, `A86`, `A87`.

<a id="f15"></a>
### F15 — Protect existing content from destructive whole writes

One existing-content protection family with unread-target substitution, fragment hold, landed-removal disclosure and rejected-draft provenance. A useful disclosure does not endorse blocking a first fix.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/loop.py:Loop.shrinking_write_check`](../../cria/loop.py#L3446)
- [`cria/loop.py:Loop.unread_target_check`](../../cria/loop.py#L3432)
- [`cria/writeproxy.py:_held_shrinking_write`](../../cria/writeproxy.py#L1244)
- [`cria/writeproxy.py:_read_in_place_of_write`](../../cria/writeproxy.py#L1252)

**Historical contract IDs:** `A67`, `A68`, `A69`, `A85`.

<a id="f16"></a>
### F16 — Turn pasted file text into executed work

One pasted-file/call-less redrive capability. Whole-file recovery, truthful did-not-run feedback and re-driving are distinct stages.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/loop.py:Loop._recover_text_write`](../../cria/loop.py#L3571)
- [`cria/loop.py:unexecuted_write`](../../cria/loop.py#L7278)

**Historical contract IDs:** `A70`, `A71`, `J28`.

<a id="f17"></a>
### F17 — Apply edits in order and report landed changes

One edit execution/feedback family with locking, ordering, exact echo, anchor-miss diagnostics and recovery choices. Aggressive rewrite escalation is a risky policy, not an endorsed default.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/writeproxy.py:_edit_command`](../../cria/writeproxy.py#L1007)
- [`cria/writeproxy.py:_edit_sequence`](../../cria/writeproxy.py#L1666)
- [`cria/writeproxy.py:render_edit_echo`](../../cria/writeproxy.py#L964)
- [`cria/editrecovery.py:recover`](../../cria/editrecovery.py#L219)

**Historical contract IDs:** `A74`, `A75`, `A76`, `A77`, `A78`, `A79`, `A80`, `A81`, `A82`, `A83`, `A84`.

<a id="f18"></a>
### F18 — Interpret raw tool output

One output interpretation family: color stripping, binary treatment and empty-result explanations have separate loss/attribution risks.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/writeproxy.py:represent_inbound`](../../cria/writeproxy.py#L2347)
- [`cria/writeproxy.py:_debinarized`](../../cria/writeproxy.py#L2054)
- [`cria/writeproxy.py:_found_nothing`](../../cria/writeproxy.py#L2102)

**Historical contract IDs:** `A88`, `A89`, `A92`, `A93`.

<a id="f19"></a>
### F19 — Redact known credentials

Keep separate: confidential payload handling is not generic output cleanup.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/writeproxy.py:_scrub`](../../cria/writeproxy.py#L2148)

**Historical contract IDs:** `A90`.

<a id="f20"></a>
### F20 — Explain dependency and environment failures

One grounded dependency/environment advice family with package-resolution and source-search adapters; authoritative tool facts and prescriptions remain distinguishable.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/writeproxy.py:_note_missing_dependency`](../../cria/writeproxy.py#L2817)
- [`cria/writeproxy.py:_note_dependency_search`](../../cria/writeproxy.py#L2854)
- [`cria/loop.py:_unresolved_deps`](../../cria/loop.py#L10554)

**Historical contract IDs:** `A91`, `A94`, `A95`, `J56`.

<a id="f21"></a>
### F21 — Gather and retain dependency API evidence

One dependency-evidence lifecycle: gather, select, replay/reanchor and permanently withhold. Keep each stage's information/freshness risk, rather than four top-level assists.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/depsurface.py:anchor_state`](../../cria/depsurface.py#L800)
- [`cria/depsurface.py:is_withheld`](../../cria/depsurface.py#L877)
- [`cria/writeproxy.py:_note_dependency_surface`](../../cria/writeproxy.py#L2592)
- [`cria/writeproxy.py:_render_dependency_surface`](../../cria/writeproxy.py#L2749)

**Historical contract IDs:** `coverage-assist-13`, `A96`, `A97`, `coverage-assist-16`.

<a id="f22"></a>
### F22 — Constrain filesystem access

One access-boundary family across explicit tools, shell paths, dependency roots and protected spill/service paths. These adapters are not a containment guarantee.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/dirguard.py:path_refusal`](../../cria/dirguard.py#L1181)
- [`cria/dirguard.py:command_refusal`](../../cria/dirguard.py#L1227)
- [`cria/writeproxy.py:_external_refusal`](../../cria/writeproxy.py#L1562)
- [`cria/writeproxy.py:_targets_cria_home`](../../cria/writeproxy.py#L315)
- [`cria/writeproxy.py:_under_spill_dir`](../../cria/writeproxy.py#L1401)

**Historical contract IDs:** `A98`, `A99`, `A104`, `A105`, `A106`.

<a id="f23"></a>
### F23 — Reject direct root deletion

One narrowly recognized root-deletion protection with direct-command and candidate-source entry points; no claim of computed-target containment.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/dirguard.py:root_recursive_delete_refusal`](../../cria/dirguard.py#L1195)
- [`cria/cleanupsafety.py:analyze`](../../cria/cleanupsafety.py#L12)

**Historical contract IDs:** `A100`, `A115`.

<a id="f24"></a>
### F24 — Keep package installs project-local

One install-boundary capability: refuse shared destinations and offer only grounded local routes.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/dirguard.py:install_refusal`](../../cria/dirguard.py#L197)
- [`cria/writeproxy.py:_external_refusal`](../../cria/writeproxy.py#L1562)

**Historical contract IDs:** `A101`, `A102`.

<a id="f25"></a>
### F25 — Reject broad process-kill selectors

Different protected resource and proof contract from filesystem deletion; retain as its own capability.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/dirguard.py:kill_refusal`](../../cria/dirguard.py#L183)

**Historical contract IDs:** `A103`.

<a id="f26"></a>
### F26 — Carry workspace surveys through harness tools

One workspace observation lifecycle: carrier, survey ingestion, body reconciliation and deferred harness questions. L2+ producer and L4/L5 consumers retain their gates.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/wsview.py:View.program`](../../cria/wsview.py#L551)
- [`cria/wsview.py:strip_survey`](../../cria/wsview.py#L1537)
- [`cria/wsview.py:View.note_written`](../../cria/wsview.py#L774)
- [`cria/writeproxy.py:represent_inbound`](../../cria/writeproxy.py#L2347)

**Historical contract IDs:** `A107`, `J59`, `J61-body`, `J61-demand`, `coverage-assist-18`.

<a id="f27"></a>
### F27 — Clean up owned probe artifacts

One owned-artifact cleanup family with workspace litter and external spool adapters. Ownership, location and permission constraints must remain distinct.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/probegate.py:sweep_litter`](../../cria/probegate.py#L2381)
- [`cria/probegate.py:_queue_spool_cleanup`](../../cria/probegate.py#L2351)
- [`cria/writeproxy.py:_litter_leg`](../../cria/writeproxy.py#L1637)

**Historical contract IDs:** `A108`, `J58`.

<a id="f28"></a>
### F28 — Review source for unsafe filesystem mutations

Already shared analysis/refusal policy with language adapters. Adapter reach and binding an edit refusal to reviewed bytes are details, not independent top-level assists.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/cleanupsafety.py:analyze`](../../cria/cleanupsafety.py#L12)
- [`cria/cleanupsafety.py:review`](../../cria/cleanupsafety.py#L38)
- [`cria/cleanup_python.py`](../../cria/cleanup_python.py)
- [`cria/cleanup_languages.py`](../../cria/cleanup_languages.py)
- [`cria/cleanup_extra.py`](../../cria/cleanup_extra.py)

**Historical contract IDs:** `A109`, `A110`, `A111`, `A112-csharp`, `A112-elixir`, `A112-go`, `A112-java`, `A112-js`, `A112-kotlin`, `A112-php`, `A112-ruby`, `A112-rust`, `A112-ts`, `A113-c`, `A113-cpp`, `A113-dart`, `A113-julia`, `A113-lua`, `A113-objc`, `A113-perl`, `A113-ps`, `A113-r`, `A113-swift`.

<a id="f29"></a>
### F29 — Adapt strict role alternation

One model-template role adaptation family; adjacent-item coalescing and system collapse are separate provenance risks and gates, not universally interchangeable.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/config.py:Role.apply`](../../cria/config.py#L302)
- [`cria/massage.py:merge_for_alternation`](../../cria/massage.py#L2573)
- [`cria/upstream.py:Upstream._prep`](../../cria/upstream.py#L373)

**Historical contract IDs:** `A117`, `T12`, `T20`.

<a id="f30"></a>
### F30 — Track actions that may change files

Shared mutation provenance feeds several consumers; distinguish observation from an independent intervention at each consumer.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/shelltool.py:writes_something`](../../cria/shelltool.py#L194)
- [`cria/writeproxy.py:represent_inbound`](../../cria/writeproxy.py#L2347)

**Historical contract IDs:** `A124`.

<a id="f31"></a>
### F31 — Keep guard state task-scoped

Supporting safety foundation with direct guard-state effects; not another repetition intervention.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/loop.py:LoopStore`](../../cria/loop.py#L2710)
- [`cria/loop.py:session_key`](../../cria/loop.py#L5842)

**Historical contract IDs:** `J01`.

<a id="f32"></a>
### F32 — Require explicit experimental planning consent

One opt-in control, separate from planner capabilities and retired mechanisms.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/config.py:PlannerConfig`](../../cria/config.py#L551)
- [`cria/server.py:CriaServer.__init__`](../../cria/server.py#L818)

**Historical contract IDs:** `J02`.

<a id="f33"></a>
### F33 — Give judges truthful read-only evidence

One judge inspection/evidence capability: truth of existence/reach, read tools, seeding, role verdict and bounded closure. No merging unknown existence into absence or forced closure into sufficient inspection.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/loop.py:_judge_completion`](../../cria/loop.py#L1155)
- [`cria/groundtruth.py:files_for_a_judge`](../../cria/groundtruth.py#L300)
- [`cria/verifytools.py:verdict_tool`](../../cria/verifytools.py#L180)
- [`cria/wsview.py:View`](../../cria/wsview.py#L148)

**Historical contract IDs:** `J03`, `J04-closure`, `J04-recovery`, `J05`, `J06`, `J07`, `J60`, `coverage-assist-17`.

<a id="f34"></a>
### F34 — Verify whole-task completion

One completion-review lifecycle with primary critic, approval confirmation, scheduled checks, release-state ownership and truthful closing. Stages remain independently inspectable.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/loop.py:judge_satisfaction`](../../cria/loop.py#L2395)
- [`cria/loop.py:_confirm_completion`](../../cria/loop.py#L1998)
- [`cria/loop.py:Loop._gate_single_done`](../../cria/loop.py#L5567)
- [`cria/loop.py:Loop._periodic_satisfaction`](../../cria/loop.py#L5192)
- [`cria/loop.py:satisfaction_done_note`](../../cria/loop.py#L2553)

**Historical contract IDs:** `J08`, `J09`, `J10`, `J22`, `J23`, `J26`, `J27`, `J110`.

<a id="f35"></a>
### F35 — Check exact file form

One exact-form capability: measure actual bytes and independently extract/check required size and final line break.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/loop.py:_written_file_facts`](../../cria/loop.py#L10289)
- [`cria/loop.py:_exact_form_blocks_completion`](../../cria/loop.py#L1876)
- [`cria/filefacts.py:render`](../../cria/filefacts.py#L26)

**Historical contract IDs:** `J11`, `J12`, `J13`.

<a id="f36"></a>
### F36 — Ground completion diagnoses in the original task

One missing-output/negative-diagnosis capability with exact quotes, narrow observation and persistent remediation state. These questions are not one interchangeable yes/no verdict.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/loop.py:observe_task_missing_file`](../../cria/loop.py#L2508)
- [`cria/loop.py:_negative_diagnosis_nudge`](../../cria/loop.py#L1642)
- [`cria/loop.py:Loop._observe_missing_file_on_done`](../../cria/loop.py#L5703)

**Historical contract IDs:** `J14`, `J15`, `J16`, `J17`.

<a id="f37"></a>
### F37 — Recover unreadable judge verdicts without approving

One shared critic response pipeline: effective-role cleanup with JSON-literal-safe framing, truncation rejection, public-answer parsing, then negative-only recovery. Preserve distinct verdict keys, inspection reach, raw text, events and caller-owned retries; never salvage a private approval.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/loop.py:_critic_verdict`](../../cria/loop.py#L809)
- [`cria/loop.py:_satisfaction_verdict`](../../cria/loop.py#L864)
- [`cria/loop.py:Loop._verdict`](../../cria/loop.py#L5105)
- [`cria/loop.py:verdict_from_unclosed`](../../cria/loop.py#L2194)
- [`cria/loop.py:verdict_from_reasoning`](../../cria/loop.py#L2287)
- [`cria/loop.py:_fill_missing_verdict_flag`](../../cria/loop.py#L2336)
- [`cria/jsontext.py:close_unclosed_object`](../../cria/jsontext.py#L92)
- [`cria/jsontext.py:strip_reasoning_prefix`](../../cria/jsontext.py#L43)
- [`cria/config.py:Role.clean_content`](../../cria/config.py#L372)

**Historical contract IDs:** `J18`, `J19`, `J20`, `J21`.

<a id="f38"></a>
### F38 — Bound completion when verification cannot finish

One completion-exit family with separately disclosed bounds, absent-route and partial/nonrunning-gate cases; grouping does not endorse every fail-open policy.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/loop.py:Loop._gate_single_done`](../../cria/loop.py#L5567)
- [`cria/loop.py:Loop._reopen_if_unsatisfied`](../../cria/loop.py#L3800)
- [`cria/loop.py:_satisfaction_blocks_completion`](../../cria/loop.py#L640)

**Historical contract IDs:** `J24`, `J25`, `J43`.

<a id="f39"></a>
### F39 — Verify optional planner steps

One experimental step/research-verification capability with probe attribution and web/file evidence adapters; own-write exclusion remains its separate risky policy.

**Scope:** Experimental planning only; OFF unless explicitly enabled.

**Principal implementation owners:**
- [`cria/loop.py:Loop._verify`](../../cria/loop.py#L4939)
- [`cria/loop.py:Loop._periodic_step_check`](../../cria/loop.py#L4555)
- [`cria/loop.py:Loop._verify_after_probe`](../../cria/loop.py#L4304)

**Historical contract IDs:** `J30`, `J31`, `J32`, `J105`, `J106-disk`, `J106-web`, `J106-own-write`.

<a id="f40"></a>
### F40 — Select safe language-aware repository checks

One discovery/check-selection family with command safety, ranking, syntax/config and name-resolution adapters. Completion probes remain distinct from prewrite regression refusal.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/probediscovery.py:discover`](../../cria/probediscovery.py#L402)
- [`cria/probeclassify.py`](../../cria/probeclassify.py)
- [`cria/proberun.py:select_probes`](../../cria/proberun.py#L188)
- [`cria/linterprobe.py:py_compile_argv`](../../cria/linterprobe.py#L177)

**Historical contract IDs:** `J33`, `J34`, `J35`, `J36`, `J37`.

<a id="f41"></a>
### F41 — Transport complete probe evidence

One probe execution/transport lifecycle: budgets, spool hash/paging, polling/resume and legacy format admission. Unknown/incomplete is never clean.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/proberun.py:compose_probe_command`](../../cria/proberun.py#L755)
- [`cria/probegate.py:ingest_transport`](../../cria/probegate.py#L575)
- [`cria/probegate.py:fail_transport`](../../cria/probegate.py#L524)
- [`cria/loop.py:guard_gate_transport`](../../cria/loop.py#L7735)

**Historical contract IDs:** `J38`, `J39`, `J40`, `J41`, `A125`.

<a id="f42"></a>
### F42 — Interpret repository check results

One check-evidence interpretation/freshness family: authoritative event state, diagnostic adapters, exact-line selection, digest, ages and newer-run precedence. Distinct carriers keep their provenance.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/probegate.py:interpret_gate`](../../cria/probegate.py#L2418)
- [`cria/probeparse.py`](../../cria/probeparse.py)
- [`cria/proberun.py:completion_probe_digest`](../../cria/proberun.py#L684)
- [`cria/loop.py:record_gate_state`](../../cria/loop.py#L8598)
- [`cria/loop.py:_checks_superseded_by_coder_run`](../../cria/loop.py#L8820)

**Historical contract IDs:** `J42`, `J44`, `J45`, `J46`, `J47`, `J48`, `J62`, `context-53`.

<a id="f43"></a>
### F43 — Require task-relevant test participation

One participation capability with phase/source/executable-boundary evidence, task-required brake and factual regression/network disclosures. A mapping is not execution.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/participation.py`](../../cria/participation.py)
- [`cria/loop.py:_test_participation_blocks_completion`](../../cria/loop.py#L1947)
- [`cria/probegate.py:gate_passing_tests`](../../cria/probegate.py#L1755)
- [`cria/probediscovery.py:declared_test_source_paths`](../../cria/probediscovery.py#L698)

**Historical contract IDs:** `J49`, `J50`, `J51`, `J52`, `J53`, `J54`, `J55`.

<a id="f44"></a>
### F44 — Detect stalled or repeated work

One stuck-work intervention family with repetition/refusal/rewrite/stall observations and fresh-probe-before-steer ordering. Preserve landed-write correction and each trigger.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/loop.py:guard_intervene`](../../cria/loop.py#L8018)
- [`cria/loop.py:guard_track_write_streak`](../../cria/loop.py#L7924)
- [`cria/loop.py:_note_write_results`](../../cria/loop.py#L709)
- [`cria/loop.py:track_gate_progress`](../../cria/loop.py#L720)

**Historical contract IDs:** `J63`, `J64`, `J65`, `J66`, `J67`.

<a id="f45"></a>
### F45 — Author a grounded next action

One next-action authoring lifecycle with actual checker facts, second look, answer recovery and absent/declined-reasoner policy. Canned fallback remains a historically lower-rated policy.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/loop.py:author_steer`](../../cria/loop.py#L10790)
- [`cria/loop.py:author_redirect`](../../cria/loop.py#L12625)
- [`cria/loop.py:guard_probe_steer`](../../cria/loop.py#L12922)

**Historical contract IDs:** `J68`, `J69`, `J70`, `J71`.

<a id="f46"></a>
### F46 — Vet proposed next actions against evidence

One whole-action vetting capability with claim-specific provenance checks; path/symbol/version/URL/field/line/auth claims are criteria, not ten independent top-level assists.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/loop.py:_vet_steer`](../../cria/loop.py#L12112)
- [`cria/loop.py:_diagnostic_action_verdict`](../../cria/loop.py#L11912)
- [`cria/urlgrounding.py`](../../cria/urlgrounding.py)

**Historical contract IDs:** `J72`, `J73`, `J74`, `J75`, `J76`, `J77`, `J78`, `J79`, `J80`, `J81`.

<a id="f47"></a>
### F47 — Reanchor declared dependency test contracts

One grounded environment/runner reset family with JavaScript runner and Go module-state adapters; preserve exact ecosystem gates and independent judgments.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/loop.py:_configured_js_test_failure`](../../cria/loop.py#L8168)
- [`cria/loop.py:module_state_steer`](../../cria/loop.py#L8239)
- [`cria/prompts/runner_reset.txt`](../../cria/prompts/runner_reset.txt)
- [`cria/prompts/module_state_reset.txt`](../../cria/prompts/module_state_reset.txt)

**Historical contract IDs:** `J83`, `J84`.

<a id="f48"></a>
### F48 — Stop degenerate or empty generation

One generation backstop/recovery family with reasoning/repetition/empty/near-window detectors. Readable-frame callbacks and truly silent HTTP sockets remain different observable paths.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/rumination.py:Detector`](../../cria/rumination.py#L299)
- [`cria/rumination.py:degenerate_wide`](../../cria/rumination.py#L231)
- [`cria/upstream.py:Upstream.chat_watched`](../../cria/upstream.py#L884)
- [`cria/loop.py:grounded_rumination_step`](../../cria/loop.py#L12974)

**Historical contract IDs:** `J85`, `J86`, `J87`, `J88`, `J89`, `J90`, `J91`, `T24`.

<a id="f49"></a>
### F49 — Resume after context loss

One handoff-continuation capability: writer/retry, attribution, rejected-prose ledger, truthful canned and reasoned continuation. Generated claims are not verified work.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/server.py:_compaction_body`](../../cria/server.py#L452)
- [`cria/server.py:_harden_compaction_reply`](../../cria/server.py#L626)
- [`cria/loop.py:Loop._reasoned_reanchor`](../../cria/loop.py#L5722)
- [`cria/selfcompact.py:work_ledger`](../../cria/selfcompact.py#L967)

**Historical contract IDs:** `J93`, `J94`, `context-31`, `context-51`, `context-52`.

<a id="f50"></a>
### F50 — Gather and maintain optional plans

One explicitly enabled planning lifecycle with gather, coverage/readiness, path/tool validation, tail revision and boundary context. Grouping does not implicitly enable it.

**Scope:** Experimental planning only; OFF unless explicitly enabled.

**Principal implementation owners:**
- [`cria/planner.py:Planner.plan_for`](../../cria/planner.py#L805)
- [`cria/planner.py:Planner._gather_and_plan`](../../cria/planner.py#L1108)
- [`cria/planner_tools.py:execute_tool`](../../cria/planner_tools.py#L90)
- [`cria/loop.py:Loop._replan_tail`](../../cria/loop.py#L4714)

**Historical contract IDs:** `J95`, `J96`, `J97`, `J98`, `J99`, `J100`, `J101-path`, `J101-tool`, `J102`, `J103`, `context-26`, `context-38`, `T93`, `T94`.

<a id="f51"></a>
### F51 — Guide and limit repeated web research

One research-steering family: exact/near repeat policy, URL substitution, preserved-query advice, semantic release, failures and spilled-read poisoning. Denial and persistent poisoning remain separately visible risks; planner path stays opt-in.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/webfetch.py:gate_search`](../../cria/webfetch.py#L1389)
- [`cria/webfetch.py:fetch_nav`](../../cria/webfetch.py#L1429)
- [`cria/loop.py:guard_search_query`](../../cria/loop.py#L12773)
- [`cria/loop.py:judge_rehunt`](../../cria/loop.py#L935)
- [`cria/loop.py:judge_search`](../../cria/loop.py#L957)
- [`cria/planner_tools.py:gate_search`](../../cria/planner_tools.py#L487)

**Historical contract IDs:** `J104`, `J111`, `J112`, `J113`, `J114`, `T64`, `T66`, `T67`, `T68`, `T69`, `T70`, `T79`.

<a id="f52"></a>
### F52 — Present earlier work as completion evidence

One action/memory provenance family. Structured did-not-run facts and unverified summary claims must not be promoted to the same authority merely by grouping them.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/loop.py:_satisfaction_evidence`](../../cria/loop.py#L6158)
- [`cria/loop.py:_work_log`](../../cria/loop.py#L6045)
- [`cria/loop.py:_mark_own_notes`](../../cria/loop.py#L13684)

**Historical contract IDs:** `J107`, `context-49`, `context-61`.

<a id="f53"></a>
### F53 — Carry durable dependency refusal and success observations

One ordered resolver-observation lifecycle: refusal history plus exact later-success supersession. History is not deleted when current state changes.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/refusalledger.py:refusal_events`](../../cria/refusalledger.py#L353)
- [`cria/refusalledger.py:_supersedes`](../../cria/refusalledger.py#L430)
- [`cria/loop.py:_session_refusals`](../../cria/loop.py#L9616)

**Historical contract IDs:** `reconcile-M09`, `reconcile-M10`.

<a id="f54"></a>
### F54 — Classify and route a task

One classification/routing lifecycle with task selection, cache, enum handling, retry/fallback, auxiliary bypass and configured route admission. Defaults and fallback risks remain explicit.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/classify.py:Classifier.classify`](../../cria/classify.py#L82)
- [`cria/routing.py:Router`](../../cria/routing.py#L37)
- [`cria/server.py:CriaHandler._classify`](../../cria/server.py#L1103)

**Historical contract IDs:** `parent-classify-task`, `parent-classify-selection`, `parent-classify-cache`, `parent-classify-enums`, `coverage-assist-01`, `coverage-assist-02`, `coverage-assist-03`, `T21`.

<a id="f55"></a>
### F55 — Measure context capacity and reserve answer room

One context sizing/refit/retry lifecycle with identity discovery, authoritative window/density, input-aware reserve and original-input fit. Retrying is allowed only by its own byte-change/provenance contracts.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/upstream.py:Upstream._prep`](../../cria/upstream.py#L373)
- [`cria/upstream.py:Upstream._overflow_refit`](../../cria/upstream.py#L601)
- [`cria/upstream.py:Upstream._open_with_refit`](../../cria/upstream.py#L632)
- [`cria/contextfloor.py:fit`](../../cria/contextfloor.py#L312)
- [`cria/tokenratio.py:record`](../../cria/tokenratio.py#L49)

**Historical contract IDs:** `T01`, `T02`, `T03`, `T04`, `T05`, `T06`, `T07`, `context-02`, `context-06`.

<a id="f56"></a>
### F56 — Prepare private wire metadata and prompt substitutions

One wire-envelope hygiene family with private-hint removal, producer-owned plumbing removal, inert substitutions and uncapped evidence naming. Each producer boundary remains explicit.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/modelview.py:wire_messages`](../../cria/modelview.py#L41)
- [`cria/upstream.py:Upstream._prep`](../../cria/upstream.py#L373)
- [`cria/bodykeys.py`](../../cria/bodykeys.py)
- [`cria/prompts/__init__.py:fill`](../../cria/prompts/__init__.py#L25)

**Historical contract IDs:** `T08`, `T15`, `coverage-assist-33`, `reconcile-M11`, `context-33`.

<a id="f57"></a>
### F57 — Translate configured reasoning conventions

One served-template/role reasoning adaptation family; sampling and no-think directive do not demonstrate better reasoning.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/config.py:Role.apply`](../../cria/config.py#L302)
- [`cria/reasoning.py:detect_served_style`](../../cria/reasoning.py#L41)
- [`cria/upstream.py:Upstream._reconcile_reasoning_convention`](../../cria/upstream.py#L311)

**Historical contract IDs:** `T17`, `T18`, `T19`.

<a id="f58"></a>
### F58 — Retry transient upstream failures

Separate from known context-overflow resend controls: different failure authority and retry permission.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/upstream.py:Upstream.chat`](../../cria/upstream.py#L833)
- [`cria/failover.py:Failure`](../../cria/failover.py#L22)

**Historical contract IDs:** `T22`.

<a id="f59"></a>
### F59 — Translate the Responses API without losing intent

One API bridge with message/control/argument/event adapters. Unsupported-item and capability omissions remain historically lower-rated policies, not hidden by byte-exact paths.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/responses.py:to_chat_body`](../../cria/responses.py#L33)
- [`cria/responses.py:body_events`](../../cria/responses.py#L379)
- [`cria/server.py:CriaHandler._handle_responses`](../../cria/server.py#L1683)
- [`cria/server.py:CriaHandler._respond_responses_stream`](../../cria/server.py#L1738)

**Historical contract IDs:** `T29`, `T30`, `T31`, `T32`, `T33`, `T34`.

<a id="f60"></a>
### F60 — Keep streams alive and drain shutdown

One stream lifecycle infrastructure family with human/client keepalive and shutdown drain; not coding-usefulness evidence.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/heartbeat.py:Heartbeat`](../../cria/heartbeat.py#L23)
- [`cria/server.py:CriaServer.drain_streams`](../../cria/server.py#L972)
- [`cria/__main__.py:main`](../../cria/__main__.py#L26)

**Historical contract IDs:** `T36`, `T37`.

<a id="f61"></a>
### F61 — Fetch and reduce external documents

One fetch/document representation lifecycle with transport, binary, HTML/JSON/YAML, raw-source and cache adapters. Lossy caps and structural transformation remain separately documented.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/webfetch.py:fetch`](../../cria/webfetch.py#L92)
- [`cria/webfetch.py:reduce_for_cache`](../../cria/webfetch.py#L155)
- [`cria/content_reduce.py:content_reduce`](../../cria/content_reduce.py#L150)

**Historical contract IDs:** `T42`, `T43`, `T44`, `T45`, `T46`, `T47`, `T48`, `T50`, `T51`, `context-10`.

<a id="f62"></a>
### F62 — Navigate documents and expose API facts

One document navigation/API-discovery family with text/JSON find, paging, route/schema extraction and MCP/GraphQL adapters. Extra requests and synthesized schema claims remain explicit.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/webfetch.py:find_json`](../../cria/webfetch.py#L1894)
- [`cria/webfetch.py:outline_for_url`](../../cria/webfetch.py#L424)
- [`cria/webfetch.py:_ref_map`](../../cria/webfetch.py#L681)
- [`cria/apidiscovery.py:discover`](../../cria/apidiscovery.py#L388)

**Historical contract IDs:** `T52`, `T53`, `T54`, `T55`, `T56`, `T57`, `T58`, `T75`, `T76`, `T77`.

<a id="f63"></a>
### F63 — Spill oversized research for harness reads

One spill/read-navigation capability with fetch/search/planner adapters, filenames/view gating, refusal outlines and reach disclosure. Command-size clipping remains a historically lower-rated policy.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/webfetch.py:note_fetch_spill`](../../cria/webfetch.py#L1202)
- [`cria/webfetch.py:search_spill_name`](../../cria/webfetch.py#L387)
- [`cria/writeproxy.py:_spill_command`](../../cria/writeproxy.py#L1366)
- [`cria/loop.py:_label_spill_entries`](../../cria/loop.py#L13719)
- [`cria/planner_tools.py:_web_fetch`](../../cria/planner_tools.py#L291)

**Historical contract IDs:** `T59`, `T60`, `T61`, `T62`, `T63`, `T65`, `T73`, `T78`, `T92`, `context-62`.

<a id="f64"></a>
### F64 — Adapt native search tool aliases

A native search interface adapter, separate from synthetic search execution and semantic research steering.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/writeproxy.py:native_search_name`](../../cria/writeproxy.py#L425)
- [`cria/server.py:CriaHandler._setup_translation`](../../cria/server.py#L1251)

**Historical contract IDs:** `T74`.

<a id="f65"></a>
### F65 — Produce backend-valid tool turns

One native integration family with template dialect, serial grammar, named choice, backend no-action carrier and stop-cause evidence. Source artifacts are not proof of current deployment.

**Scope:** Checked-in native integration artifacts; no deployment/readiness claim.

**Principal implementation owners:**
- [`cria/prompts/localai_functioncall_chat.jinja.txt`](../../cria/prompts/localai_functioncall_chat.jinja.txt)
- [`cria/prompts/localai_functioncall_answer_tool.txt`](../../cria/prompts/localai_functioncall_answer_tool.txt)
- [`scripts/backend-patches/8345-serial-tool-call.patch`](../../scripts/backend-patches/8345-serial-tool-call.patch)
- [`scripts/backend-patches/8345-named-tool-choice.patch`](../../scripts/backend-patches/8345-named-tool-choice.patch)
- [`scripts/backend-patches/8345-no-action-tool.patch`](../../scripts/backend-patches/8345-no-action-tool.patch)
- [`scripts/backend-patches/8345-generation-stop.patch`](../../scripts/backend-patches/8345-generation-stop.patch)

**Historical contract IDs:** `T80`, `T81`, `T82`, `T83`, `T84`.

<a id="f66"></a>
### F66 — Bridge CLI providers

One optional CLI-provider bridge with execution ownership, prompt selection, resume and malformed-result policy. These are architectural boundary risks, not four separately useful assists.

**Scope:** Optional configured CLI-provider bridge; no execution-boundary endorsement.

**Principal implementation owners:**
- [`cria/claude_cli.py:ClaudeCliProvider._invoke`](../../cria/claude_cli.py#L68)
- [`cria/claude_cli.py:_parse_claude_json`](../../cria/claude_cli.py#L118)
- [`cria/routing.py:Router._build_cli`](../../cria/routing.py#L153)

**Historical contract IDs:** `T88`, `T89`, `T90`, `T91`.

<a id="f67"></a>
### F67 — Protect task authority during context shaping

One authority-preservation/frame-shaping family. Protected original task/current question and risky caller/tool-instruction shedding retain separate risk histories; grouping does not justify destroying authority.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/contextfloor.py:_protected_mask`](../../cria/contextfloor.py#L634)
- [`cria/contextfloor.py:_reduce_caller_spans`](../../cria/contextfloor.py#L395)
- [`cria/contextfloor.py:_compress_tools`](../../cria/contextfloor.py#L431)
- [`cria/loop.py:_frame_for_item`](../../cria/loop.py#L6685)
- [`cria/loop.py:reframe_preamble`](../../cria/loop.py#L6516)

**Historical contract IDs:** `context-07`, `context-08`, `context-11`, `context-13`, `context-25`, `context-27`, `context-28`, `context-60`, `context-63`.

<a id="f68"></a>
### F68 — Reduce old history with truthful state

One history-floor lifecycle: remove droppable history, maintain labelled state and handle floor-created orphan pairs/repeated digest cycles. Distinct from fitting-body wire repair.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/contextfloor.py:_drop_oldest`](../../cria/contextfloor.py#L762)
- [`cria/contextfloor.py:_compacted_note`](../../cria/contextfloor.py#L922)
- [`cria/contextfloor.py:fit`](../../cria/contextfloor.py#L312)

**Historical contract IDs:** `context-12`, `context-14`, `context-16`.

<a id="f69"></a>
### F69 — Fold repeated context evidence

One deduplication family with whole-message, checker, fetch, read-only-call and action-log adapters. Normalization and latest-repeat suppression remain risky distinct policies.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/dedup.py:fold_repeated_runs`](../../cria/dedup.py#L462)
- [`cria/dedup.py:fold_repeated_actions`](../../cria/dedup.py#L373)
- [`cria/focustrim.py:_collapse_duplicates`](../../cria/focustrim.py#L234)
- [`cria/modelview.py:fold_evidence`](../../cria/modelview.py#L81)
- [`cria/upstream.py:Upstream._prep`](../../cria/upstream.py#L373)

**Historical contract IDs:** `context-17`, `context-18`, `context-19`, `context-20`, `context-21`, `context-22`, `context-46`.

<a id="f70"></a>
### F70 — Compact conversation memory without changing task or facts

One compaction lifecycle: composition, write/refold, independent retrospective/scope/fidelity validation, echo rejection and retry throttle. Preserve three independent questions rather than merging verdict criteria.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/selfcompact.py:compact`](../../cria/selfcompact.py#L1030)
- [`cria/selfcompact.py:compaction_request_parts`](../../cria/selfcompact.py#L449)
- [`cria/loop.py:Loop._self_compact`](../../cria/loop.py#L4210)
- [`cria/server.py:_harden_compaction_reply`](../../cria/server.py#L626)

**Historical contract IDs:** `context-35`, `context-36`, `context-37`, `context-39`, `context-40`, `context-41`, `context-42`, `context-43`.

<a id="f71"></a>
### F71 — Prepare reducible judge evidence

One judge-evidence framing family with whole-line composition, transcript defanging and oversized summarization. Summary judgments and loss limits remain distinct.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/loop.py:_evidence_blocks`](../../cria/loop.py#L2654)
- [`cria/loop.py:_judge_completion`](../../cria/loop.py#L1155)
- [`cria/loop.py:summarize`](../../cria/loop.py#L8426)
- [`cria/selfcompact.py:serialize`](../../cria/selfcompact.py#L242)

**Historical contract IDs:** `context-45`, `context-47`, `context-48`.

<a id="f72"></a>
### F72 — Restore current workspace facts after context loss

One restoration/provenance capability: fresh inventory/current text, named reduction stand-in, sent-body read credit, paired-result footer and dated ledger. Sent credit is not a durable ledger or a footer.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/loop.py:_restored_text_message`](../../cria/loop.py#L10230)
- [`cria/groundtruth.py:workspace_inventory`](../../cria/groundtruth.py#L348)
- [`cria/modelview.py:settle_restored_text`](../../cria/modelview.py#L209)
- [`cria/modelview.py:retained_results_truth`](../../cria/modelview.py#L131)
- [`cria/upstream.py:Upstream._prep`](../../cria/upstream.py#L373)

**Historical contract IDs:** `context-09`, `context-32`, `context-54`, `context-55`, `context-56`, `context-57`, `context-58`.

<a id="f73"></a>
### F73 — Suppress or substitute historical tool payloads

One lossy history-substitution family. Keep failure squashing, superseded writes and landed-payload substitution explicitly historically lower-rated, rather than endorsing them as harmless compression.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/focustrim.py:_drop_superseded_writes`](../../cria/focustrim.py#L452)
- [`cria/focustrim.py:_repeat_failed`](../../cria/focustrim.py#L340)
- [`cria/modelview.py:superseded_writes_truth`](../../cria/modelview.py#L169)
- [`cria/selfcompact.py:_last_write_index_by_path`](../../cria/selfcompact.py#L749)

**Historical contract IDs:** `context-23`, `context-24`, `context-44`.

<a id="f74"></a>
### F74 — Sanitize replayed internal transcripts

One inbound transcript-hygiene family with marker/fence/artifact rules. Plan-artifact deletion is not the same as removing a human display annotation.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/indicators.py:strip_history`](../../cria/indicators.py#L126)
- [`cria/loop.py:_strip_cria_file_ops`](../../cria/loop.py#L6274)
- [`cria/server.py:CriaHandler._strip_and_reframe_inbound`](../../cria/server.py#L1204)

**Historical contract IDs:** `context-29-status`, `context-29-reasoning`, `context-29-plan`.

<a id="f75"></a>
### F75 — Report model-visible usage

A harness-facing usage boundary, not another context-fitting policy.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/modelview.py:visible_tokens`](../../cria/modelview.py#L99)
- [`cria/loop.py:Loop.visible_context_tokens`](../../cria/loop.py#L3031)
- [`cria/server.py:_incoming_ctx_tokens`](../../cria/server.py#L1907)

**Historical contract IDs:** `context-34`.

<a id="f76"></a>
### F76 — Carry finished-work briefings into follow-ups

Separate from rejected-handoff recovery: closing-time generated memory with its own validation/provenance limits.

**Scope:** Runtime/config gates owned by the implementation; related opt-in variants remain separate.

**Principal implementation owners:**
- [`cria/loop.py:Loop._compact_done`](../../cria/loop.py#L5144)
- [`cria/loop.py:_briefing_from_history`](../../cria/loop.py#L5873)

**Historical contract IDs:** `context-59`.

## Maintenance and boundaries

Update titles, contracts and owners in the registry, not this generated file. Keep existing family/detail identities stable; a new adapter ordinarily belongs to an existing family. Adding a genuinely different capability requires a reasoned taxonomy change, not a count target.

Regenerate with `python docs/assist-inventory/build_report.py`; check with `python docs/assist-inventory/build_report.py --check`. The builder validates identity coverage and real code owners without importing runtime/provider modules.

F03's argument conversion, F12's syntax guard and F28's language safety dispatch were already shared. F13 now shares mutation argument preparation/refusal; F37 now shares critic response reading. The remaining families are codified ownership/navigation groups—not a claim of 76 newly unified engines.

Required separations include: preserving orphan results versus deleting unanswered calls (F07); withholding versus retrying incomplete actions (F09); measured fitting versus unchanged resend suppression (F55); URL advice versus persistent research denial (F51); and independent retrospective/scope/fidelity judgments (F70). Unknown candidate/transport facts remain unknown. Context reduction stays at the single labelled floor, and irreducible protected overflow must still perform zero completion POST.

The retained history excludes supporting/retired/proposed rows from the implemented-detail map. Old procedural assignments, state files, validation/finalization receipts and incident scratch are not a second catalog and do not belong in this durable index. Actual model-call logs retain their own provenance.

Design law: [principles](../principles.md). Mechanism notes: [heuristic assists](../heuristic-assists.md). Architecture/research boundary: [Shephard](../shephard.md).
