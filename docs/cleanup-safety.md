# Inference-free filesystem-mutation review

`cleanupsafety.review` runs at synthetic `write_file` / exact `edit_file` lowering.
It analyzes source as data: no imports of candidate code, execution, network calls,
or reasoner. It uses complete candidates; edits need source bytes from `wsview`,
not reads against cria's own filesystem. Missing or ambiguous edit source is UNKNOWN.

## Confidence is evidence strength, not a probability

- **PROVEN**: all represented targets violate a supported rule under the adapter's
  API/path assumptions, conditional on the operation executing. Refuse the change.
- **POSSIBLE**: a known unsafe alternative or unresolved scope/control semantics.
  Log only; do not refuse.
- **UNKNOWN**: target, operation identity, or language semantics are unresolved.
  Log only. This is not permission or a safety certificate.
- **WITHIN_SCOPE**: the represented direct target is within the lexical permission
  boundary or a tracked temporary resource. This does not certify the whole file.

The rules live in `cleanupfacts.py`: mutations of resolved absolute external paths
respect `external_dir_permission`; recursive filesystem-root deletion and recursive
cleanup of a default shared temporary parent are refused independently. A temporary
file owns that file, not its parent. A tracked temporary directory owns its children;
cleanup of the directory itself is legitimate. Lexical containment belongs to
`dirguard`, not another boundary implementation. POSIX path semantics are used.

## Coverage today

| Adapter | What it can establish | Deliberate limits |
|---|---|---|
| Python (`.py`, `.pyw`) | AST import aliases, assignments/reassignments, literals, `os.path` parent/join/normalization, `pathlib` construction/parent/join, tempfile file/directory ownership; branch alternatives and exception-prefix state for `finally`; simple undecorated zero-argument helper return summaries | Not a complete interpreter, type checker, or interprocedural analyzer. Unsupported expressions become unknown; complex helper summaries are withheld. |
| JavaScript/TypeScript | Static default/namespace/require imports for Node fs/path; straight-line path assignments and dirname/join; fs deletion/truncation/writes and explicit recursive options; mkdtempSync ownership | No JS execution, dynamic imports, general destructuring or control-flow/type resolution. |
| Go | os mutation contracts, import aliases, filepath Dir/Join and simple assignments | Scope-dependent targets remain POSSIBLE; closed root-target proofs survive function/conditional wrappers. No error-tuple/temp-resource analysis. |
| Rust | Qualified std::fs contracts and simple std use imports, Path/PathBuf literal construction | No borrow/type/lifetime analysis, macros, general use syntax or third-party tempfile semantics. Scope-dependent findings are POSSIBLE, except independently resolved root targets. |
| JVM | Java Files/FileUtils mutation contracts and Path/Paths constructors; Kotlin imported deleteRecursively extension on a resolved variable receiver | No compiler/type resolution or general extension dispatch. Method-body dataflow remains POSSIBLE, but closed root-target proofs remain blocking. |
| .NET | System.IO File/Directory mutations, Path parent/combine, GetTempFileName ownership | POSIX targets only; scope-dependent findings are POSSIBLE except closed root-target proofs. No C# compiler or overload resolution. |
| PHP | unlink/rmdir/file_put_contents, dirname/tempnam and simple `$variable` assignment | Interpolated/dynamic paths unresolved; no namespace/function override resolution. Assumes the named builtin semantics. |
| Ruby | File/FileUtils/Dir mutation contracts, File parent/join, default mktmpdir ownership with tmpdir required; parenthesized and simple parenthesis-free calls | No metaprogramming, monkey-patching or general block semantics. Scope-dependent findings are POSSIBLE, except independently resolved root targets. |
| Elixir | File mutation contracts, Path dirname/join, parenthesized and simple parenthesis-free calls | No macro expansion, alias/rebinding or pipeline analysis. Scope-dependent findings are POSSIBLE, except independently resolved root targets. |
| C (`.c`, `.h`) | Direct standard-header `remove`, `unlink`, `rmdir`, and `fopen` with literal write modes | No preprocessor expansion, pointer/function alias analysis or variable dataflow. No recursive deletion API is implied by `remove`/`rmdir`. |
| C++ (`.cc`, `.cpp`, `.cxx`, `.hpp`, `.hh`, `.hxx`) | Standard-header `std::filesystem::remove_all`/`remove`, `path` construction, `std::remove`/`fopen`, and `std::ofstream` construction | Explicit qualified spellings, not namespace aliases or overload/type resolution. Recognized unevaluated `sizeof`/`decltype`/`noexcept`/`alignof` contexts are excluded. |
| Swift (`.swift`) | Foundation `FileManager.default.removeItem(atPath:)` / `removeItem(at:)` with `URL(fileURLWithPath:)`; `createFile(atPath:)` | Direct default-manager receiver only. No inferred instance types, Foundation aliases or general URL resolution. |
| Objective-C (`.m`, `.mm`) | Foundation-header `[[NSFileManager defaultManager] removeItemAtPath:…]` / `createFileAtPath:…` | Exact class/factory receiver, not arbitrary selectors on `id`; no swizzling/type resolution. `.m` is ambiguous with MATLAB, so the Foundation declaration is required for these proofs. |
| Dart (`.dart`) | Unaliased `dart:io` import; direct `Directory(path)` / `File(path)` receivers with `delete`/`deleteSync` and explicit recursive options; File `writeAsString`/`writeAsBytes` and Sync variants | No receiver-variable typing, import aliases, extension-method dispatch or general path-package resolution. |
| Lua (`.lua`) | Builtin `os.remove`; `io.open` with literal write modes | Read-only/default opens do not fire. No module aliases, metatables or resource ownership. |
| Perl (`.pl`, `.pm`) | Builtin/CORE `unlink`, `rmdir`, three-argument `open`; File::Path `remove_tree` with explicit module/import evidence; simple parenthesis-free removal calls | No glob/alias dispatch, two-argument open interpretation or general list/dataflow analysis. Literal variadic removal targets are checked separately. |
| R (`.r`, `.R`) | Builtin/base `unlink` with explicit `recursive=TRUE`, `file.remove`, `writeLines`; closed `dirname`/`file.path` expressions | No vector/connection-object dataflow, package masking resolution or NSE evaluation. Recognized `quote`/`expression`/`substitute` bodies are excluded. |
| Julia (`.jl`) | Builtin/Base `rm` with explicit recursion, `open` with write modes/flags, `write`; closed `dirname`/`joinpath` expressions | No multiple-dispatch or variable/type analysis. Quoted expressions and macro arguments are not presumed to execute. |
| PowerShell (`.ps1`, `.psm1`) | Case-insensitive direct `Remove-Item`, `Clear-Content`, `Set-Content`; literal `-Path`/`-LiteralPath` targets, explicit recursion and WhatIf switches | POSIX filesystem paths only, **not Windows drive/UNC roots or other providers**. No aliases, abbreviated parameters, splatting, pipeline-input paths or general argument binding. Explicit WhatIf is non-mutating; dynamic WhatIf remains unknown. |
| Shell scripts | Reuse the existing direct-shell root-deletion backstop for `.sh`/`.bash` candidates, without execution | Narrow direct commands only; no expansion, invoked-program or heredoc analysis. |
| Universal | Tokenized destructive-looking calls, with common strings/comments excluded; literal/assignment path leads | **UNKNOWN only.** A name like deleteTree might not do filesystem IO. Arbitrary languages do not get a blocking static analyzer from this scan. |

The ten added destruction-only adapters live in `cleanup_extra.py`; their future
cria-wide candidacy is tracked separately in [open threads](open-threads.md#candidate-new-cria-wide-languages).
They resolve **closed expressions only**, never a guessed cross-scope variable value.
Computed/variable targets stay UNKNOWN. Direct API/builtin identity requires the
listed declaration evidence and no detected shadowing, rebinding or escaped binding.
Unresolved lexical/preprocessor/dynamic-binding constructs can withhold proof for a
whole candidate; this is uncertainty about interpretation/identity, not a downgrade
merely because a function or `if` exists. Unsupported macros, aliases and reflection
remain gaps. None of these adapters tracks temporary-resource ownership yet.

Their lexer excludes language-specific comments, common raw/long/triple strings,
Perl POD/data sections and quote operators, and PowerShell here-strings. Interpolated,
escaped or unsupported target literals remain unresolved rather than being decoded
with another language's rules. Unterminated recognized lexical regions report
`invalid-source`; token/expression budgets report `analysis-limit`. This is not a
syntax validator. All regression candidates are inert strings; tests also exercise
actual write/edit lowering without executing the resulting candidate programs.

Non-Python adapters deliberately do **not** claim Python-equivalent analysis.
They recognize narrow contracts, not entire languages. In the original lexical
adapters (`cleanup_languages.py`), braces/control/declarations still lower confidence
in the **flat variable map**, not in an independently resolved root target. For root calls, the adapter checks a stable API identity and re-evaluates
the target without that variable map: literals and closed path expressions such as
`path.dirname("/child")` can remain PROVEN inside a function or `if`. A parameter,
rebinding, member replacement, or escaped API binding prevents this proof. Imported
bindings must be visible from the call's enclosing brace scope; default-argument
`require` expressions are not treated as fixed imports. Identity checks are deliberately
whole-candidate conservative, so an ambiguous use elsewhere can still withhold proof.
Variable-dependent target paths, mixed branches and general scope/type resolution
remain limited; this change does not pretend those were solved. Recognized plain Node
recursive-option objects are data, not control scopes. Unknown mutation names can
escape detection completely. Universal leads supplement Python findings where its
adapter cannot resolve an API.

Regression examples (inert source tests in `tests/test_cleanup_control_flow.py`):
`function cleanup() { if (enabled) fs.rmSync("/", {recursive:true}); }` blocks when
`fs` is the stable Node import; the same body with an unknown `fs` parameter or a
computed target remains unproven. Both write and edit lowering must emit refusal
rather than the original file operation. No candidate source is executed.

## Assumptions and safety boundary

- Known APIs must resolve to their ordinary library semantics. Import shadowing and
  rebinding handled by a subset of syntax are invalidated, not guessed. Custom modules,
  monkey-patching through untracked aliases/calls, FFI and reflective dispatch remain gaps.
- Relative paths, cwd changes, symlinks, mount topology, environment expansion and
  Windows path semantics are not certified. No remote filesystem observations are invented.
- Syntax-validity is established by Python's parser only. Other adapters are lexical;
  they do not establish that the source compiles or a referenced library is installed.
- Analysis limits yield an explicit `analysis-limit`, not a partial clean verdict.
- Files written through raw shell/native tools, existing unsafe files and other execution
  paths bypass this candidate hook. A file with no findings is **not** declared safe.
- Only synthetic-tool lowering uses this review. The local suite's separate Codex
  filesystem sandbox remains the independent boundary against missed behavior.

No numerical score is presented because no calibrated probability has been measured.
No broad safety or false-positive rate is inferred from the test count.

## Recovered incident and regression

`tests/fixtures/incident_parent_cleanup.py.txt` is the exact recovered orders-api-py
source from session `01a0f776-6370-7912-a47a-b050238406f5`, source read in
`inbound-03a9ae51-responses.json` input[119]. SHA-256:
`c79913cdf0fc195be9d9a1d7159d80275f01264f960da19e4f0c42c09ea78f74`.

The tempfile helper's returned file path flows into `rmtree(dirname(path))`.
The last test reuses that variable for absolute HTTP routes, including `/`.
The analyzer reports shared-parent cleanup and a route-derived root target. The
production server lowering test has no reasoner; it asserts that the result is a
refusal and contains no write command. Separate plumbing tests run only refusal/file
operations inside disposable test directories, never the recovered program.

This regression failed with the prior implementation, which emitted the write when
its judge was unavailable. The replacement blocks the same source without inference.
The old fake-judge tests were retargeted to actual analysis and preserved incident,
stale-edit, repair, missing-source, inert-text and no-inference coverage.
