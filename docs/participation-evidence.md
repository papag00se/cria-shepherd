# Build/source/test participation evidence

The completion gate answers two different questions that must not be collapsed:

1. Did a command exit successfully?
2. What build phase, source inputs, and tests actually participated in that event?

An exit code answers the first question. It does not, by itself, answer the second. A green test
task may collect nothing, a build may compile a different target, and a test runner may never load
the implementation named in the completion claim.

`cria/participation.py` is the single schema and orchestration layer for the second question.
`probegate.interpret_gate` gives it the command, exit status, exact section output, parsed diagnostic
paths, and the selected candidate's discovery-time ecosystem. Adapters read repository declarations
only through the harness-populated `wsview`; they never open the workspace directly.

## Schema

Every gate section produces one `ProbeParticipation` with independent `build`, `source`, and `test`
phases. Each phase carries:

- `attempted`: whether that phase was actually entered;
- `completed`: whether it returned rather than timing out or disappearing;
- `participated`: whether at least one subject in the phase is known to have participated;
- `passed`: whether that participating phase passed;
- `count`, `passed_count`, `nonpassing_count`, and `skipped_count`, only where the runner's own
  output supports those exact meanings (`nonpassing_count` includes runner-reported errors rather
  than relabelling them as assertion failures);
- `participants`, their kind (`file`, `package`, `target`, or `test`), and whether the list is
  exhaustive;
- the exact, unmodified tool-output lines supporting those facts.

Every scalar is three-valued. `None` is rendered to a judge as `"unknown"`. In particular:

- missing output is unknown, not a pass;
- an unrecognized green test summary is unknown, not “tests ran”;
- an unsupported count is unknown, not zero;
- a package, target, or source count is not a source-file identity;
- a manifest declaration is not execution.

`PhaseParticipation.support()` and `ParticipationReport.support()` are fail-closed proof
operations. Unknown never returns `proven`. Source completion support is stricter: an event must name
at least one actual file input. `supports_source_file(path)` approves only that named path; absence
from a partial list proves nothing.

## Authorities and orchestration

The layer accepts only:

- the selected `ProbeCandidate` and its discovery-time ecosystem;
- the real gate section's exit sentinel and output;
- diagnostic paths already parsed by the shared probe parser;
- exact manifest/config bodies returned through `wsview`.

It does not inspect cria's filesystem, infer from the user's task, invent a command, modify a probe,
or treat a conventional directory as proof of execution. Manifest lines containing source/test
scope declarations are retained exactly and labelled declarations only.

`record_gate_state` stores the report from every reading, including partial and missing readings, so
an older green report cannot survive a newer unknown event. The report reaches:

- the step completion critic together with that gate's digest;
- the single `judge_satisfaction` funnel, covering every satisfaction caller;
- the approve-path confirmation as a cria-measured fact.

The judge sees a structured `completion_support` value for each phase and an explicit rule: unknown
cannot be promoted to pass or zero, and a green event whose source support is unknown did not prove
that the claimed implementation participated. The report proves participation only; it never proves
behavioral correctness. Independent runtime evidence in the coder's real tool log remains available
to the judge.

## Ecosystem adapters and honest limits

| Adapter | Facts available from ordinary gate output | What remains unknown unless the event says more |
|---|---|---|
| JS/TS | Jest/Vitest/Node/Mocha tallies; explicitly named test files; per-file `node --check` and lint inputs; package/TS config declarations | Which implementation modules a passing runner imported; `tsc` inputs when it emits no file list |
| Python | pytest/unittest tallies; compileall/pyflakes inputs from the same `wsview` inventory used to compose the command; diagnostic paths; Python/test config declarations | Which implementation modules a passing pytest run executed without coverage/import output |
| Rust | Cargo tallies; `Running …` source/test targets; `Compiling`/`Checking` target lines; Cargo declarations | Source files not named by Cargo's event, including module files behind a named crate target |
| Go | `-v` test names and runner tally; participating package verdict lines; `go.mod` declarations | File identity inside a package because build tags and package selection are not emitted |
| JVM (Maven and Gradle) | JUnit/Gradle tallies, Surefire test classes, compiler-reported source counts, POM/Gradle declarations | Source-file identity when the compiler reports only a count; Gradle `UP-TO-DATE` inputs |
| .NET | test tally and built project/assembly target lines; project/solution declarations | Compile-item identity without compiler/binlog input output |
| PHP | PHPUnit tally, diagnostic paths, explicit `php -l` file inputs, Composer/PHPUnit/static-analysis declarations | Implementation files loaded by a green PHPUnit run without coverage/trace output |
| Ruby | minitest/RSpec tally, diagnostic paths, explicit `ruby -c` inputs, Gemfile/Rake declarations | Implementation files required by a green test run without coverage/trace output |
| Elixir | ExUnit tally, compiler-reported `.ex` source count, `mix.exs` declarations | File identity when Mix reports only a count or reuses compiled artifacts |

These unknowns are intentional. Normal runner output cannot provide full trustworthy file-level
participation for all nine ecosystems. The adapters therefore implement the complete shared contract
and return honest unknowns rather than inventing facts. A future probe may strengthen an adapter only
when the repository itself declares that instrumentation or the actual gate event emits the needed
provenance.
