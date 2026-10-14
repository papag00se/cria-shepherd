#!/usr/bin/env python3
"""Render the canonical family map from inert Python metadata; no model/runtime calls."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from cria.assistfamilies import FAMILIES, AssistFamily  # noqa: E402

HISTORY = Path(__file__).with_name("detail-history.json")
REPORT = Path(__file__).with_name("REPORT.md")
EXPECTED_FAMILY_IDS = tuple(f"F{i:02}" for i in range(1, 77))
SCOPES = {
    "gated_runtime": "Runtime/config gates owned by the implementation; related opt-in variants remain separate.",
    "experimental_planning": "Experimental planning only; OFF unless explicitly enabled.",
    "native_artifacts": "Checked-in native integration artifacts; no deployment/readiness claim.",
    "configured_cli_provider": "Optional configured CLI-provider bridge; no execution-boundary endorsement.",
}


def declarations(path: Path) -> dict[str, int]:
    """Locate named Python owners without importing executor/provider modules."""
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


def validate(families: tuple[AssistFamily, ...], history: dict) -> dict[tuple[str, str], int]:
    if tuple(f.id for f in families) != EXPECTED_FAMILY_IDS:
        raise ValueError("Family identities/order must remain F01–F76")
    if len({f.title for f in families}) != len(families):
        raise ValueError("Family titles must be unique")
    details = [member for family in families for member in family.details]
    if len(set(details)) != len(details):
        raise ValueError("A historical detail belongs to more than one family")
    historical = history["entries"]
    if len({row["id"] for row in historical}) != len(historical):
        raise ValueError("Duplicate historical identity")
    if set(details) != {row["id"] for row in historical}:
        raise ValueError("Family map must cover every retained historical detail exactly once")
    assigned = {detail: family.id for family in families for detail in family.details}
    if any(assigned[row["id"]] != row["family_id"] for row in historical):
        raise ValueError("Historical family assignment drift")
    excluded = {row["id"] for row in history["excluded_details"]}
    if excluded & set(details):
        raise ValueError("Supporting, retired or pending rows cannot become implemented details")
    composites = history["composite_dispositions"]
    if len({row["source_id"] for row in composites}) != len(composites):
        raise ValueError("Duplicate historical composite identity")
    if any(not row["canonical_ids"] or not set(row["canonical_ids"]) <= set(details) | excluded
           for row in composites):
        raise ValueError("Historical composites must resolve to retained identities")
    declared_by_path = {}
    owner_lines = {}
    for family in families:
        if not family.contract or not family.details or not family.owners or family.scope not in SCOPES:
            raise ValueError("Incomplete family " + family.id)
        for owner in family.owners:
            path = ROOT / owner.path
            if Path(owner.path).is_absolute() or not path.resolve().is_relative_to(ROOT):
                raise ValueError("Implementation owner must be repository-relative " + owner.path)
            if not path.is_file():
                raise ValueError("Missing implementation owner " + owner.path)
            if owner.symbol:
                if path.suffix != ".py":
                    raise ValueError("Named Python owner in non-Python artifact " + owner.path)
                if owner.path not in declared_by_path:
                    declared_by_path[owner.path] = declarations(path)
                if owner.symbol not in declared_by_path[owner.path]:
                    raise ValueError("Missing named implementation owner " + owner.path + ":" + owner.symbol)
                owner_lines[owner.path, owner.symbol] = declared_by_path[owner.path][owner.symbol]
    return owner_lines


def render(families: tuple[AssistFamily, ...] = FAMILIES, history: dict | None = None) -> str:
    history = json.loads(HISTORY.read_text()) if history is None else history
    owner_lines = validate(families, history)
    lines = [
        "# The 76 assist families",
        "",
        "**Canonical implementation map:** [`cria/assistfamilies.py`](../../cria/assistfamilies.py). "
        "This generated view names capabilities and their principal code owners, not every conditional "
        "branch, parser adapter, caller or safety criterion as another assist.",
        "",
        "- **76 families, not 409 independent features.** The 409 original detail identities remain "
        "a historical contract map in [`detail-history.json`](detail-history.json). Each belongs to one family.",
        "- **Grouping is not permission to collapse policies.** Keep different authority boundaries, "
        "gates, refusal rules and information risks separate inside a family. Principal owners are "
        "navigation bindings, not an exhaustive call graph or proof of necessity/usefulness.",
        "- **No family score ranges.** Historical detail scores describe the frozen " +
        history["source_revision"] + " review only. They are not ratings of today's code, averages, "
        "confidence ranges or measured usefulness. Historical risks remain in the detail map.",
        "- **No deployment claim.** This is the checked-in implementation taxonomy; an installed "
        "service, native artifact or inherited pending source package needs its own acceptance.",
        "- **Planning remains OFF.** F32 owns explicit consent; F39 and F50 describe experimental "
        "planner capabilities. Metadata does not enable an assist, select a model, run a tool or create a wrapper.",
        "",
        "## Browse by capability",
        "",
    ]
    categories = tuple(dict.fromkeys(f.category for f in families))
    for category in categories:
        rows = [family for family in families if family.category == category]
        lines += ["### " + category, "", "| ID | Family |", "|---|---|"]
        lines += [f"| {f.id} | [{f.title}](#{f.id.lower()}) |" for f in rows]
        lines.append("")
    lines += ["## Contracts and principal owners", ""]
    for family in families:
        lines += [f'<a id="{family.id.lower()}"></a>', f"### {family.id} — {family.title}", "", family.contract, "",
                  "**Scope:** " + SCOPES[family.scope], "", "**Principal implementation owners:**"]
        for owner in family.owners:
            label = owner.path + (":" + owner.symbol if owner.symbol else "")
            anchor = ("#L" + str(owner_lines[owner.path, owner.symbol])) if owner.symbol else ""
            lines.append(f"- [`{label}`](../../{owner.path}{anchor})")
        lines += ["", "**Historical contract IDs:** " + ", ".join(f"`{d}`" for d in family.details) + ".", ""]
    lines += [
        "## Maintenance and boundaries",
        "",
        "Update titles, contracts and owners in the registry, not this generated file. "
        "Keep existing family/detail identities stable; a new adapter ordinarily belongs to an existing "
        "family. Adding a genuinely different capability requires a reasoned taxonomy change, not a count target.",
        "",
        "Regenerate with `python docs/assist-inventory/build_report.py`; "
        "check with `python docs/assist-inventory/build_report.py --check`. "
        "The builder validates identity coverage and real code owners without importing runtime/provider modules.",
        "",
        "F03's argument conversion, F12's syntax guard and F28's language safety dispatch were already shared. "
        "F13 now shares mutation argument preparation/refusal; F37 now shares critic response reading. "
        "The remaining families are codified ownership/navigation groups—not a claim of 76 newly unified engines.",
        "",
        "Required separations include: preserving orphan results versus deleting unanswered calls (F07); "
        "withholding versus retrying incomplete actions (F09); measured fitting versus unchanged resend suppression (F55); "
        "URL advice versus persistent research denial (F51); and independent retrospective/scope/fidelity judgments (F70). "
        "Unknown candidate/transport facts remain unknown. Context reduction stays at the single labelled floor, "
        "and irreducible protected overflow must still perform zero completion POST.",
        "",
        "The retained history excludes supporting/retired/proposed rows from the implemented-detail map. "
        "Old procedural assignments, state files, validation/finalization receipts and incident scratch "
        "are not a second catalog and do not belong in this durable index. Actual model-call logs retain their own provenance.",
        "",
        "Design law: [principles](../principles.md). Mechanism notes: [heuristic assists](../heuristic-assists.md). "
        "Architecture/research boundary: [Shephard](../shephard.md).",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = render()
    if args.check:
        if not REPORT.is_file() or REPORT.read_text() != content:
            print("Family report is stale; regenerate it", file=sys.stderr)
            return 1
        print("PASS: family identities, historical coverage, source owners and generated report")
        return 0
    REPORT.write_text(content)
    print("Wrote " + str(REPORT.relative_to(ROOT)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
