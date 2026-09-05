# Dependency refusal events

The dependency refusal ledger is session-scoped structured provenance, not a permanent set of
strings. It exists so a resolver rejection can survive transcript compaction without losing the
facts needed to interpret it later.

Each event records:

- the ecosystem;
- the resolver's raw coordinate, including a version/range when it printed one;
- separately parsed package and version fields used only for exact comparison;
- the exact matching tool-output text;
- the tool-call id and command when the harness exposes them; and
- a session sequence number and outcome (`refused` or `succeeded`).

Only real tool results enter the ledger. Assistant prose never does. Repeated request bodies are
deduplicated by tool-call provenance, so transcript replay does not make an old event fresh. When a
harness omits the call id, byte-identical anonymous evidence is conservatively treated as the same
observation because its freshness cannot be established.

## Ecosystem coverage

One unit covers the nine dependency ecosystems cria supports:

| ecosystem | manager output recognised |
|---|---|
| JavaScript / TypeScript | npm, pnpm, Yarn, and Bun, including bare package names |
| Python | pip, uv, and Poetry, including bare distribution names |
| Rust | Cargo packages, requirements, and bare crate names |
| Go | package paths, repository URLs, and module-version coordinates |
| JVM | Maven artifacts, Gradle coordinates, and rejected Java packages |
| .NET | NuGet package ids and versioned package coordinates |
| PHP | Composer package names and versions |
| Ruby | RubyGems and Bundler gem names and requirements |
| Elixir | Hex/Mix package names and versions |

The compatibility functions `refused_names`, `scan_messages`, and `prescribed` remain available.
They now expose the ledger's current coordinate set, including bare names. URL-form Go repository
coordinates retain their historical normalized comparison spelling while the structured event keeps
the raw URL the tool printed.

## Freshness and supersession

The current view is derived by replaying ordered events. A later successful event supersedes a
refusal only for the same ecosystem and exact package. If the refusal names a concrete version, the
success must name that same concrete version; resolving a different version does not erase the
rejection. A bare-name refusal may be superseded by an explicit successful version of that package.

Success is admitted only where it is observable: an explicit successful-coordinate line from the
manager, or an unambiguous manager success marker from a later rerun of the exact command that
produced the refusal. The full event history remains available as provenance even after its current
refusal is superseded.

## Judgment boundary

Deterministic code gathers and dates these facts. Exact coordinate matching may trigger a question,
but it never interprets verbs such as “add,” “remove,” or “replace” and never vetoes a directive.
The existing whole-action reasoner receives the current checker output, current refusal events, and
the task/workspace grounding, then returns the single semantic verdict. There is no second
per-provider or per-token veto.
