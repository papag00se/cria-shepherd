#!/usr/bin/env python3
"""Generate the single taxonomy view; never execute a registered policy."""
from __future__ import annotations

import argparse
import ast
import inspect
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from cria.assistfamilies import (  # noqa: E402
    ALIASES, FAMILIES, HISTORICAL_DETAIL_TO_FAMILY, AssistFamily,
    executable_definitions,
)

HISTORY = Path(__file__).with_name("detail-history.json")
REPORT = Path(__file__).with_name("REPORT.md")
LEVELS = Path(__file__).with_name("LEVELS.md")
SCOPES = {
    "gated_runtime": "Existing runtime/config gates; navigation coverage is pending migration.",
    "experimental_planning": "Explicit experimental planning only; OFF by default.",
    "native_artifacts": "Native artifacts only; no runtime registration or deployment claim.",
    "configured_cli_provider": "Optional configured provider; not an ordinary runtime assist.",
}
from cria.assistcontract import Reference  # noqa: E402
from cria import config  # noqa: E402

LEVEL_TITLES = {
    config.PURE_PROXY: "Pure proxy",
    config.TOOL_CALL_FIXES: "Tool-call fixes",
    config.SIMPLE_TOOLS: "Simple tools",
    config.CONTEXT_FIXES: "Context fixes",
    config.DONE_REFUSALS_ENABLED: "Completion refusals",
    config.ASSISTS_ENABLED: "Assists",
}

# Executable Policy scope -> maintenance-family applicability. Artifacts and
# configured providers have no ordinary executable-policy scope here.
POLICY_FAMILY_SCOPES = {"runtime": "gated_runtime", "experimental": "experimental_planning"}

KINDS = {"intervention", "foundation", "support", "artifact", "provider"}
COVERAGE = {"navigation_only_pending", "external_artifact", "required_wire_contract"}


def declarations(path: Path) -> dict[str, int]:
    """Find declarations without importing their implementations."""
    found = {}
    def visit(node, prefix=""):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = prefix + child.name
                found[name] = child.lineno
                if isinstance(child, ast.ClassDef):
                    visit(child, name + ".")
            elif isinstance(child, (ast.Assign, ast.AnnAssign)) and not prefix:
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        found[target.id] = child.lineno
    visit(ast.parse(path.read_text()))
    return found


def source_path(path: str) -> Path:
    result = ROOT / path
    if Path(path).is_absolute() or not result.resolve().is_relative_to(ROOT):
        raise ValueError("Implementation owner must be repository-relative " + path)
    if not result.is_file():
        raise ValueError("Missing implementation owner " + path)
    return result


def reference_line(reference: Reference) -> int:
    """Validate a source-declared hook/regression reference, not its execution."""
    if (not isinstance(reference, Reference) or not isinstance(reference.path, str)
            or not isinstance(reference.symbol, str) or not reference.path or not reference.symbol):
        raise ValueError("Invalid policy source reference")
    path = source_path(reference.path)
    if path.suffix != ".py" or reference.symbol not in declarations(path):
        raise ValueError("Missing policy source reference: " + reference.path + ":" + reference.symbol)
    return declarations(path)[reference.symbol]


def executable_owner(definition):
    """Locate an explicit source-owned binding in its implementation module.

    Inspect only the registered callable's module and its top-level assignments.
    A binding may be a definition or an immutable tuple of definitions. Identity,
    not metadata equality, rejects copied records. This is not plugin discovery.
    """
    module = inspect.getmodule(definition.execute)
    path = inspect.getsourcefile(definition.execute)
    if module is None or not path:
        raise ValueError("Missing executable implementation")
    rel = Path(path).resolve().relative_to(ROOT).as_posix()
    source = source_path(rel)
    if definition.execute.__qualname__ not in declarations(source):
        raise ValueError("Missing executable declaration")
    bindings = []
    for node in ast.parse(source.read_text()).body:
        targets = (node.targets if isinstance(node, ast.Assign) else
                   [node.target] if isinstance(node, ast.AnnAssign) else [])
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            value = getattr(module, target.id, None)
            if value is definition:
                bindings.append((target.id, None))
            elif isinstance(value, tuple):
                bindings.extend((target.id, index) for index, member in enumerate(value)
                                if member is definition)
    if not bindings:
        raise ValueError("Executable ownership must reference an authoritative source definition")
    symbol, index = bindings[0]
    label = symbol + (f"[{index}]" if index is not None else "")
    return rel, symbol, label


def validate(families: tuple[AssistFamily, ...], history: dict, *, aliases=None,
             definitions=None) -> dict[tuple[str, str], int]:
    aliases = ALIASES if aliases is None else aliases
    definitions = executable_definitions() if definitions is None else definitions
    ids = [f.id for f in families]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate family ID")
    if len({f.title for f in families}) != len(families):
        raise ValueError("Family titles must be unique")
    by_id = {f.id: f for f in families}
    for old, target in aliases.items():
        if (not old or old in by_id or old == target or target in aliases
                or target not in by_id):
            raise ValueError("Invalid direct family alias: " + old)
    lineage = [old for f in families for old in f.lineage]
    if len(set(lineage)) != len(lineage):
        raise ValueError("Duplicate historical family ownership")
    if set(lineage) != set(ids) | set(aliases):
        raise ValueError("Family lineage must cover current identities and aliases")
    for f in families:
        if any(aliases.get(old, old) != f.id for old in f.lineage):
            raise ValueError("Family lineage disagrees with aliases")
    historical = history["entries"]
    if len({row["id"] for row in historical}) != len(historical):
        raise ValueError("Duplicate historical identity")
    if {row["id"]: row["family_id"] for row in historical} != dict(HISTORICAL_DETAIL_TO_FAMILY):
        raise ValueError("Frozen historical family assignment drift")
    details = [d for f in families for d in f.details]
    if len(set(details)) != len(details):
        raise ValueError("A historical detail belongs to more than one family")
    if set(details) != {row["id"] for row in historical}:
        raise ValueError("Family map must cover every retained historical detail exactly once")
    assigned = {d: f.id for f in families for d in f.details}
    if any(assigned[row["id"]] != aliases.get(row["family_id"], row["family_id"])
           for row in historical):
        raise ValueError("Current ownership disagrees with historical aliases")
    excluded = {row["id"] for row in history["excluded_details"]}
    if excluded & set(details):
        raise ValueError("Excluded historical details cannot become active members")
    composites = history["composite_dispositions"]
    if len({row["source_id"] for row in composites}) != len(composites):
        raise ValueError("Duplicate historical composite identity")
    if any(not row["canonical_ids"] or not set(row["canonical_ids"]) <= set(details) | excluded
           for row in composites):
        raise ValueError("Historical composites must resolve to retained identities")
    owner_lines = {}
    declared = {}
    for f in families:
        if (not all((f.id, f.title, f.category, f.contract, f.purpose, f.boundary,
                     f.details, f.lineage))
                or not (f.owners or any(d.policy.family_id == f.id for d in definitions))
                or f.scope not in SCOPES
                or f.kind not in KINDS or f.coverage not in COVERAGE):
            raise ValueError("Incomplete family " + f.id)
        if ((f.scope == "native_artifacts") != (f.kind == "artifact")
                or (f.scope == "configured_cli_provider") != (f.kind == "provider")
                or (f.coverage == "external_artifact") != (f.kind == "artifact")):
            raise ValueError("Invalid family scope/coverage " + f.id)
        if f.coverage == "required_wire_contract" and (f.kind != "foundation"
                or any(d.policy.family_id == f.id for d in definitions)):
            raise ValueError("Required wire contract is not a removable atomic policy " + f.id)
        for owner in f.owners:
            path = source_path(owner.path)
            if owner.symbol:
                if path.suffix != ".py":
                    raise ValueError("Named Python owner in non-Python artifact " + owner.path)
                if owner.path not in declared:
                    declared[owner.path] = declarations(path)
                if owner.symbol not in declared[owner.path]:
                    raise ValueError("Missing named implementation owner " + owner.path + ":" + owner.symbol)
                owner_lines[owner.path, owner.symbol] = declared[owner.path][owner.symbol]
    atomic_ids = [d.policy.id for d in definitions]
    if len(set(atomic_ids)) != len(atomic_ids):
        raise ValueError("Duplicate atomic ID or multiply owned atomic assist")
    seen = set()
    for d in definitions:
        p = d.policy
        if (not all((p.id, p.family_id, p.stage, p.state))
                or not callable(d.execute) or not isinstance(p.scope, str)
                or p.scope not in POLICY_FAMILY_SCOPES
                or isinstance(p.default_level, bool) or not isinstance(p.default_level, int)
                or not 0 <= p.default_level <= 5):
            raise ValueError("Incomplete or invalid executable definition")
        if p.family_id not in by_id or by_id[p.family_id].scope != POLICY_FAMILY_SCOPES[p.scope]:
            raise ValueError("Unresolved or incompatible atomic family")
        if len(set(p.dependencies)) != len(p.dependencies) or not set(p.dependencies) <= seen:
            raise ValueError("Invalid atomic dependency/order")
        if (not isinstance(p.migrated, bool) or not isinstance(p.hooks, tuple)
                or not isinstance(p.regressions, tuple)):
            raise ValueError("Invalid policy migration metadata")
        if p.migrated and (not p.hooks or not p.regressions):
            raise ValueError("Migrated policy must declare hooks and regressions")
        for references in (p.hooks, p.regressions):
            for reference in references:
                reference_line(reference)
            if len(set(references)) != len(references):
                raise ValueError("Duplicate policy source reference")
        if len(set(p.prompts)) != len(p.prompts):
            raise ValueError("Duplicate atomic prompt")
        for prompt in p.prompts:
            source_path("cria/prompts/" + prompt + ".txt")
        executable_owner(d)
        seen.add(p.id)
    return owner_lines


def render(families: tuple[AssistFamily, ...] = FAMILIES, history: dict | None = None) -> str:
    history = json.loads(HISTORY.read_text()) if history is None else history
    definitions = executable_definitions()
    owner_lines = validate(families, history, definitions=definitions)
    lines = [
        "# Assist families and executable migration", "",
        f"**{len(families)} current maintenance families; {len(definitions)} registered atomic definitions.** "
        "The remaining navigation map is pending R1/R7 migration, not accepted executable coverage. "
        "Required wire contracts are explicitly classified foundations, not selectable atomics.", "",
        "Canonical family metadata: [`cria/assistfamilies.py`](../../cria/assistfamilies.py). "
        "Atomic metadata and implementation come directly from production `assistruntime.DEFINITIONS`; "
        "this report never executes policies or creates a second atomic catalog.", "",
        "Planning remains OFF unless explicitly enabled. Families are not switches or efficacy scores. "
        "Supporting components and external artifacts are not removable steering policies.", "",
        "Assists are **L5 only**. Registered definitions also cover L0–L4 wire fixes, cria tools, "
        "context fitting (including history compaction) and completion brakes; registry membership "
        "is not an assist count. The `rank4-ablation` profile disables the current operator-selected "
        "subset of Rank-4 definitions with `default_level = 5`, retaining all level-eligible L0–L4 mechanisms. "
        "The historical 48-entry ranking record is not the active disabled set; see the "
        "[profile contract](../../README.md#exact-rank-4-ablation).", "",
        "Frozen detail assignments and judgments remain in [detail-history.json](detail-history.json). "
        "Current ownership resolves direct aliases; no stored history or captures are rewritten.", "",
        "## Current families", "", "| ID | Responsibility | Kind | Coverage |",
        "|---|---|---|---|",
    ]
    for f in families:
        lines.append(f"| [{f.id}](#{f.id.lower()}) | {f.title} | {f.kind} | {f.coverage} |")
    lines += ["", "## Direct historical aliases", "", "| Historical family | Current owner |", "|---|---|"]
    lines += [f"| {old} | {target} |" for old, target in ALIASES.items()]
    lines += ["", "## Responsibilities, boundaries and members", ""]
    for f in families:
        members = [d for d in definitions if d.policy.family_id == f.id]
        lines += [f'<a id="{old.lower()}"></a>' for old in f.lineage if old != f.id]
        lines += [f'<a id="{f.id.lower()}"></a>', f"### {f.id} — {f.title}", "",
                  "**Purpose:** " + f.purpose, "", "**Boundary:** " + f.boundary, "",
                  f"**Kind:** {f.kind}. **Applicability:** {SCOPES[f.scope]}", "",
                  "**Migration:** " + ("Required wire-fit source contract; no removable atomic members or behavioral acceptance claim."
                                      if f.coverage == "required_wire_contract" else
                                      "Registered members below; all other behavior remains navigation-only pending migration."
                                      if members else "No registered atomic members; navigation-only pending migration."
                                      if f.kind != "artifact" else "External artifacts only; not runtime assists."), "",
                  "**Registered atomic definitions:**"]
        for d in members:
            p = d.policy
            rel, _symbol, label = executable_owner(d)
            lines += [f"- `{p.id}` — [`{rel}:{label}`](../../{rel}); execute `{d.execute.__qualname__}`.",
                      f"  Stage `{p.stage}`; default level {p.default_level}; scope `{p.scope}`.",
                      f"  State: {p.state}. Services: {', '.join(p.services) or 'none'}.",
                      f"  Caller triggers: {', '.join(f'{name} (level {level})' for name, level in p.triggers) or 'none'}.",
                      f"  Structural migration claim: {'declared (not behavioral acceptance)' if p.migrated else 'pending integration'}.",
                      f"  Prompts: {', '.join(p.prompts) or 'none'}. Dependencies: {', '.join(p.dependencies) or 'none'}."]
            for title, references in (("Hooks", p.hooks), ("Regressions", p.regressions)):
                rendered = ", ".join(
                    f"[`{ref.path}:{ref.symbol}`](../../{ref.path}#L{reference_line(ref)})"
                    for ref in references)
                lines.append(f"  {title}: {rendered or 'not declared; migration pending'}.")
        if not members:
            lines.append("- None (not an acceptance claim).")
        lines += ["", "**Principal navigation/support owners (not exhaustive stage bindings):**"]
        for owner in f.owners:
            label = owner.path + (":" + owner.symbol if owner.symbol else "")
            anchor = "#L" + str(owner_lines[owner.path, owner.symbol]) if owner.symbol else ""
            lines.append(f"- [`{label}`](../../{owner.path}{anchor})")
        lines += ["", "**Historical families:** " + ", ".join(f.lineage) + ".", "",
                  "**Historical detail lineage:** " + ", ".join(f"`{d}`" for d in f.details) + ".", "",
                  "**Preserved contract distinctions:** " + f.contract, ""]
    lines += ["## Maintenance", "",
              "[Architecture doctrine](../shephard.md#assist-and-family-boundaries) owns creation/consolidation rules. "
              "[Mechanisms](../heuristic-assists.md) and [principles](../principles.md) describe behavior and constraints.", "",
              "Run `python docs/assist-inventory/build_report.py` to regenerate this view; use `--check` to verify agreement. "
              "Validation checks structure, frozen lineage, source declarations, definition ownership, dependencies/order and scopes. "
              "It does not judge English uniqueness, deployment, behavioral benefit or complete production migration.", ""]
    return "\n".join(lines)


def render_levels() -> str:
    """List registered definitions at their own default engagement level."""
    definitions = executable_definitions()
    lines = []
    for level in range(config.MAX_ENGAGEMENT_LEVEL + 1):
        lines += [f"## L{level} — {LEVEL_TITLES[level]}", ""]
        for definition in definitions:
            policy = definition.policy
            if policy.default_level == level:
                lines.append(f"- `{policy.id}` — [{policy.family_id}](REPORT.md#{policy.family_id.lower()})")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outputs = ((REPORT, render()), (LEVELS, render_levels()))
    if args.check:
        stale = [path for path, content in outputs if not path.is_file() or path.read_text() != content]
        if stale:
            print("Generated inventory is stale: " + ", ".join(path.name for path in stale), file=sys.stderr)
            return 1
        print("PASS: taxonomy, frozen lineage, executable definitions and generated reports")
        return 0
    for path, content in outputs:
        path.write_text(content)
        print("Wrote " + str(path.relative_to(ROOT)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
