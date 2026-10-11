# Independent native named-tool contract

`8345-named-tool-choice.patch` fixes producer normalization and selection at
llama.cpp `8345f333951c661d166b00e6f9362e553768f292`. It is independent of the
no-action protocol: its enforcement applies with that option disabled too.
It also applies with zero fuzz to the frozen V1 patched source.

The actual Chat Completions input uses
`{"type":"function","function":{"name":"read_file"}}`; Responses uses
`{"type":"function","name":"read_file"}`; Anthropic uses
`{"type":"tool","name":"read_file"}`. Each producer retains that identity,
then the shared native preparation validates the exact Chat shape, requires one
matching caller function, and renders/builds grammar over only that function.
It requires a call, rather than normalizing the name to automatic choice. The
caller menu and history are preserved; previous calls to other functions remain
in history but do not re-enter the current generation menu.

Unknown, missing, malformed or ambiguous names give request errors (400).
Named selection combined with a standalone response schema also gives 400 before
generation: that combination is unsupported by this serving path. Neither caller
instruction is silently discarded. Chat/Responses schema requests are exercised
through their actual producers; the Anthropic producer does not forward those
OpenAI-specific schema fields.
Reserved `tools` template overrides are rejected for named choice. Automatic,
required and none retain their meanings, including Anthropic's `any` and `none`
producer conversion. Null remains automatic at the shared preparation owner.
The Anthropic boolean `disable_parallel_tool_use` is validated and propagated;
parallel requests can repeat the selected function without admitting others.

The differential fixture compiles against matching V1 or V2 headers/libraries,
uses real API converters and native preparation/grammar/parser/result classes,
and never loads weights. `tests/test_native_named_tool_choice.py` verifies actual
wrong-function output is rejected by grammar and parser, selected output is
accepted, caller/history immutability, malformed requests and protocol gating.
Before/after logs and isolated named-only build receipts are retained in
`~/.cria/validation/localai-phi4-install/no-action-native-v2/`.

This contract repair does not deploy a runtime, resume a campaign, establish
coding usefulness or satisfy the separate no-action acceptance gaps. Final
readiness remains NOT_READY pending parent verification. The parent assembled
runtime must omit old ABI helper executables and contain only the matching server,
common/server implementation libraries and original same-revision CUDA core and
backend libraries.
