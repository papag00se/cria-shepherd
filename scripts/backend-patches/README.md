# Private native tool-protocol patches

All patches target llama.cpp revision
`8345f333951c661d166b00e6f9362e553768f292`. Apply them in order:

1. `8345-serial-tool-call.patch` repairs unconditional repetition in the native
   JSON per-call envelope. Serial requests allow one real call; parallel requests
   retain repetition. The serial-only deployment and its original before/after
   receipts remain historical evidence.
2. `8345-named-tool-choice.patch` independently validates named requests at each
   API producer and restricts generation to the selected caller tool. See
   [named-tool-choice.md](named-tool-choice.md).
3. `8345-no-action-tool.patch` adds the disabled-by-default, generic server option
   `--no-action-tool FILE`. It loads a complete OpenAI function definition from
   JSON, including its name, description and required `message:string` schema.
   It contains no model identity or model-facing description.

These are private deployment artifacts. No upstream checkout, commit, push or
PR is part of their development.

## Protocol and ownership

Only automatic choice (omitted, null or explicit auto) with nonempty caller tools and no JSON response schema
activates the setting. The backend builds one effective menu by appending the
loaded definition; that same menu drives rendering, grammar and parsing. The
caller menu is unchanged. Active name collisions fail with a request error.
Required, none, no-tools and schema requests retain their previous menus,
rendering, grammar and interpretation of caller-owned tools. Named requests are
excluded from no-action activation and now intentionally enforce the selected
caller function through the independent contract patch. Named choice plus a
standalone response schema is rejected as unsupported by this serving path.
Neither caller instruction is silently discarded. A schema request also
keeps caller ownership on a colliding name.

Active `chat_template_kwargs.tools` overrides fail with a request error rather
than replacing the authoritative menu. Preparation returns a typed C++ result
carrying the generated parser and activation together. All chat inference routes
copy that private state into task parameters; apply-template and count routes use
the same prepared prompt. Activation is absent from the public JSON schema. Raw
completion controls cannot enable it, and any untrusted NO_ACTION parser tag is
rejected before mapping, regardless of the selected mapper format.

The grammar separates a single no-action envelope from a serial/parallel batch
of real actions. Its no-action branch is atomic: incomplete arguments or closing
markers cannot publish a name, ID, tool delta or content. The native mapper skips
its tool subtree and appends the exact JSON-decoded message to any earlier
content, retaining reasoning. No tool ID or result is created. Native response
formatting then finishes with `stop`, in buffered and streamed responses.
Real calls retain their existing argument streaming and `tool_calls` finish.

Completed active replies are parsed strictly. Malformed envelopes, missing or
non-string messages, extra payload keys, off-menu names and mixed answer/action
batches are errors. Definitions must have exactly one plain string message
property and exactly that required key. Extra schema facets and true/schema-valued
additionalProperties are rejected. Omission preserves the measured definition;
the supported protocol is closed to other payload keys.
Their evidence contains the entire raw reply as hex, including NUL or invalid
UTF-8 bytes, plus a JSON text representation. Partial parsing stays lenient for
unfinished JSON escapes and UTF-8 sequences; answer publication still requires
the entire atomic envelope. Native argument brace completion cannot complete it.

The opt-in is restricted to the grounded analyzer shape: native JSON, flat
name/arguments in that order, complete per-call opening/closing markers, no section,
array, name-as-key, nested, ID or OpenAI wrappers, and plain surrounding content.
Unsupported shapes and forced pure-content parsing fail closed before returning
prepared state. Wider generic format support is not claimed.

Reasoning delimiters come from the analyzer. A mandatory reasoning alternative
and a content parser that stops at those delimiters prevent an unfinished block
from falling back to final prose, including whitespace/preamble and incomplete
closing prefixes. Closed reasoning and earlier content remain lossless. Tests use
the actual STOP_TYPE_LIMIT/length response formatting and actual partial result
class for every prefix; the adapter is not changed to compensate.

For phi4, the definition is
[`localai_functioncall_answer_tool.txt`](../../cria/prompts/localai_functioncall_answer_tool.txt).
Its descriptions come from LocalAI's
[`chat.go`](https://github.com/mudler/LocalAI/blob/master/core/http/endpoints/openai/chat.go),
with the required string made explicit as in the captured manual-menu probe.
The measured
[`chat adapter`](../../cria/prompts/localai_functioncall_chat.jinja.txt)
remains byte-identical, including its ordinary-text guidance. Native menu
injection exactly matches the captured manual-menu rendering golden. Ordinary
bare text remains content. Spontaneous prose or result JSON inside the Output
wrapper is a preserved rejected characterization, not a promised final format;
the supported wrapped final is the canonical function's `message` string.

## CPU reproduction

From the cria checkout, export pinned source into a **new private directory**.
The following commands assume the directories do not already exist:

```sh
mkdir /tmp/phi4-no-action-source-v2
git -C ~/src/llama.cpp-cuda archive 8345f333951c661d166b00e6f9362e553768f292 \
  | tar -x -C /tmp/phi4-no-action-source-v2
patch -d /tmp/phi4-no-action-source-v2 -p1 \
  < scripts/backend-patches/8345-serial-tool-call.patch
patch --fuzz=0 -d /tmp/phi4-no-action-source-v2 -p1 \
  < scripts/backend-patches/8345-named-tool-choice.patch
patch --fuzz=0 -d /tmp/phi4-no-action-source-v2 -p1 \
  < scripts/backend-patches/8345-no-action-tool.patch
cmake -S /tmp/phi4-no-action-source-v2 -B /tmp/phi4-no-action-build-v2 \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=ON -DCMAKE_BUILD_RPATH_USE_ORIGIN=ON \
  -DGGML_CUDA=OFF -DGGML_NATIVE=OFF -DLLAMA_CURL=OFF \
  -DLLAMA_BUILD_TESTS=ON -DLLAMA_BUILD_SERVER=ON
cmake --build /tmp/phi4-no-action-build-v2 --target llama-server \
  test-chat-auto-parser test-chat-template test-chat-peg-parser -j 8
cd /tmp/phi4-no-action-source-v2
/tmp/phi4-no-action-build-v2/bin/test-chat-auto-parser
/tmp/phi4-no-action-build-v2/bin/test-chat-template
/tmp/phi4-no-action-build-v2/bin/test-chat-peg-parser
```

From the cria checkout:

```sh
LOCALAI_PROBE_SOURCE=/tmp/phi4-no-action-source-v2 \
LOCALAI_PROBE_LIBRARY=/tmp/phi4-no-action-build-v2/bin \
  python -m pytest -q tests/test_localai_tool_template.py \
    tests/test_native_named_tool_choice.py tests/test_native_protocol_error_propagation.py
LOCALAI_PROBE_SOURCE=/tmp/phi4-no-action-source-v2 \
LOCALAI_PROBE_LIBRARY=/tmp/phi4-no-action-build-v2/bin \
  python -m pytest
```

Both environment selections are required for the optional integration tests.
Never compile new headers against an old library. The fixture uses the actual
server request preparation, parser-parameter transfer, result state, native
`common_chat_msg_diff::compute_diffs` and response serialization. It loads no
weights and uses no inference, network or GPU. Vocabulary-dependent metadata is
excluded from schema evaluation because these tests operate on bytes; the
rendered grammar is independently evaluated by the native grammar engine.
Every byte prefix exercises native diffs, append-only content, nondecreasing
real calls and zero synthetic answer deltas. Pinned serial-only golden fixtures
also compare disabled rendering, grammar and parser bytes.

## ABI and parent deployment

**Rebuild and deploy a matching server/common pair.** New fields change the C++
layouts and prepared return type of common/server parameters. An old server is incompatible with the new
common library despite unchanged shared-library version numbers. This revision
also builds `libllama-server-impl.so`; deploy that newly built library together
with `llama-server` and `libllama-common.so`, preserving their matching hashes. The CPU build uses `$ORIGIN` library search paths so a copied server does not silently load core libraries from its temporary build directory.
Do not repeat the serial-only deployment's common-library-only replacement.
The parent runtime must contain only the matching server executable, matching
common/server implementation libraries and original same-revision CUDA core and
backend dependencies. Exclude old helper executables and their ABI-dependent
implementations; rebuilding the server does not make old helpers compatible.

The private CPU build proves the matching server/common implementation compiles
and its parser tests pass. It does **not** authorize copying CPU core libraries
into the GPU runtime. Parent deployment must assemble a separate phi4 runtime,
retain the original same-revision CUDA `libllama`/`libggml` core libraries,
backend libraries and kernels, check dependencies and symbol compatibility,
and validate the assembled server before opt-in. Do not change any library
under a running process. Other model runtimes remain outside this opt-in.

Parent should install the JSON file with its exact bytes and add
`--no-action-tool <installed-JSON-file>` only to phi4's launch. Menu injection,
grammar and conversion must go live together. The template does not gain a
second variable, and cria has no wire rewrite or regex fallback for this path.

**Status: NOT_READY pending parent live verification.** CPU protocol correctness
is not coding usefulness or truthful completion. No inference, benchmark replay,
campaign resume, service restart, config change or merge was performed for this
unit. Full build/source/probe/test receipts are under
`~/.cria/validation/localai-phi4-install/no-action-native-v2/`. V1 source, build,
receipts and the parent hybrid remain frozen. The original raw
controls, rejected prototype and prior installation state remain preserved in
the parent validation directory. Parent must verify real execution, exact file
bytes, final delivery, truthful checks and runtime/GPU restrictions before
issuing readiness.

## Existing error/retry boundary

A length-clipped reasoning block or action now produces a native protocol error,
not a successful partial final/action. Native buffered error formatting reports
500; an established stream terminates with an error event. The existing watched
stream client discards partial call/content bytes and re-asks once buffered. A
buffered 500 is classified as unavailable; the one-endpoint policy is exhausted
and does not retry it as a transient timeout. The upstream error then propagates.
`tests/test_native_protocol_error_propagation.py` proves this with fake upstream
responses. No new retry policy was added, and automatic continued work is not
claimed. Parent must verify actual error propagation during live validation.
