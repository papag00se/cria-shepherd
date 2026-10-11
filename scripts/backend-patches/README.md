# Private native tool-protocol patches

Both patches target llama.cpp revision
`8345f333951c661d166b00e6f9362e553768f292`. Apply them in order:

1. `8345-serial-tool-call.patch` repairs unconditional repetition in the native
   JSON per-call envelope. Serial requests allow one real call; parallel requests
   retain repetition. The serial-only deployment and its original before/after
   receipts remain historical evidence.
2. `8345-no-action-tool.patch` adds the disabled-by-default, generic server option
   `--no-action-tool FILE`. It loads a complete OpenAI function definition from
   JSON, including its name, description and required `message:string` schema.
   It contains no model identity or model-facing description.

These are private deployment artifacts. No upstream checkout, commit, push or
PR is part of their development.

## Protocol and ownership

Only automatic choice with nonempty caller tools and no JSON response schema
activates the setting. The backend builds one effective menu by appending the
loaded definition; that same menu drives rendering, grammar and parsing. The
caller menu is unchanged. Active name collisions fail with a request error.
Required, named, none, no-tools and schema requests retain their previous menus,
rendering, grammar and interpretation of caller-owned tools.

The pinned server already treats a named-choice object as its default automatic
choice. This patch preserves that existing behavior while explicitly excluding
named-choice objects from no-action activation; it does not add named-choice
support. A schema request also keeps caller ownership on a colliding name.

The grammar separates a single no-action envelope from a serial/parallel batch
of real actions. Its no-action branch is atomic: incomplete arguments or closing
markers cannot publish a name, ID, tool delta or content. The native mapper skips
its tool subtree and appends the exact JSON-decoded message to any earlier
content, retaining reasoning. No tool ID or result is created. Native response
formatting then finishes with `stop`, in buffered and streamed responses.
Real calls retain their existing argument streaming and `tool_calls` finish.

Completed active replies are parsed strictly. Malformed envelopes, missing or
non-string messages, off-menu names and mixed answer/action batches are errors.
Their evidence contains the entire raw reply as hex, including NUL or invalid
UTF-8 bytes, plus a JSON text representation. Partial parsing stays lenient for
unfinished JSON escapes and UTF-8 sequences; answer publication still requires
the entire atomic envelope. Native argument brace completion cannot complete it.

The opt-in requires a template that the native analyzer identifies as JSON tool
syntax; unsupported syntax and forced pure-content parsing fail closed. It
never silently exposes the backend-owned function as a harness tool.

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
mkdir /tmp/phi4-no-action-source
git -C ~/src/llama.cpp-cuda archive 8345f333951c661d166b00e6f9362e553768f292 \
  | tar -x -C /tmp/phi4-no-action-source
patch -d /tmp/phi4-no-action-source -p1 \
  < scripts/backend-patches/8345-serial-tool-call.patch
patch -d /tmp/phi4-no-action-source -p1 \
  < scripts/backend-patches/8345-no-action-tool.patch
cmake -S /tmp/phi4-no-action-source -B /tmp/phi4-no-action-build \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=ON -DCMAKE_BUILD_RPATH_USE_ORIGIN=ON \
  -DGGML_CUDA=OFF -DGGML_NATIVE=OFF -DLLAMA_CURL=OFF \
  -DLLAMA_BUILD_TESTS=ON -DLLAMA_BUILD_SERVER=ON
cmake --build /tmp/phi4-no-action-build --target llama-server \
  test-chat-auto-parser test-chat-template test-chat-peg-parser -j 8
cd /tmp/phi4-no-action-source
/tmp/phi4-no-action-build/bin/test-chat-auto-parser
/tmp/phi4-no-action-build/bin/test-chat-template
/tmp/phi4-no-action-build/bin/test-chat-peg-parser
```

From the cria checkout:

```sh
LOCALAI_PROBE_SOURCE=/tmp/phi4-no-action-source \
LOCALAI_PROBE_LIBRARY=/tmp/phi4-no-action-build/bin \
  python -m pytest -q tests/test_localai_tool_template.py
LOCALAI_PROBE_SOURCE=/tmp/phi4-no-action-source \
LOCALAI_PROBE_LIBRARY=/tmp/phi4-no-action-build/bin \
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
layouts of common/server parameters. An old server is incompatible with the new
common library despite unchanged shared-library version numbers. This revision
also builds `libllama-server-impl.so`; deploy that newly built library together
with `llama-server` and `libllama-common.so`, preserving their matching hashes. The CPU build uses `$ORIGIN` library search paths so a copied server does not silently load core libraries from its temporary build directory.
Do not repeat the serial-only deployment's common-library-only replacement.

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
`~/.cria/validation/localai-phi4-install/no-action-native/`. The original raw
controls, rejected prototype and prior installation state remain preserved in
the parent validation directory. Parent must verify real execution, exact file
bytes, final delivery, truthful checks and runtime/GPU restrictions before
issuing readiness.
