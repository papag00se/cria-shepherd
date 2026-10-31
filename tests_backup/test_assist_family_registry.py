"""Taxonomy migration preserves history without claiming runtime completeness."""
import dataclasses
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from cria.assistfamilies import (ALIASES, BY_ID, DETAIL_TO_FAMILY, FAMILIES,
                                HISTORICAL_DETAIL_TO_FAMILY, executable_definitions,
                                resolve_family)
from cria.assistruntime import DEFINITIONS
from cria.config import Config

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("assist_family_report", ROOT / "docs/assist-inventory/build_report.py")
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


def history():
    return json.loads(report.HISTORY.read_text())


def test_historical_assignments_resolve_without_rewriting_frozen_history():
    original = {row["id"]: row["family_id"] for row in history()["entries"]}
    assert original == dict(HISTORICAL_DETAIL_TO_FAMILY)
    assert {d: resolve_family(f) for d, f in original.items()} == dict(DETAIL_TO_FAMILY)
    assert set(BY_ID) | set(ALIASES) == set(original.values())
    assert not set(BY_ID) & set(ALIASES)
    report.validate(FAMILIES, history())


def test_authorized_merges_have_direct_aliases_and_complete_lineage():
    expected = {"F27": "F40", "F41": "F40", "F42": "F40", "F45": "F44",
                "F46": "F44", "F21": "F20", "F53": "F20", "F37": "F33",
                "F39": "F50", "F02": "F01", "F38": "F34", "F64": "F10", "F18": "F14"}
    assert dict(ALIASES) == expected
    for old, current in expected.items():
        assert resolve_family(old) == current
        assert old in BY_ID[current].lineage
    with pytest.raises(ValueError, match="Unknown"):
        resolve_family("unknown")


def test_registry_references_the_production_definitions_not_metadata_copies():
    assert executable_definitions() is DEFINITIONS
    for d in DEFINITIONS:
        assert d.policy.family_id in BY_ID
        path, symbol, label = report.executable_owner(d)
        assert path == d.execute.__module__.replace(".", "/") + ".py"
        assert symbol and label
    assert not any(o.symbol == "DEFINITION" for f in FAMILIES for o in f.owners)
    assert all(f.purpose and f.boundary for f in FAMILIES)
    assert all(f.coverage in ("navigation_only_pending", "external_artifact", "required_wire_contract") for f in FAMILIES)
    assert BY_ID["F68"].coverage == "required_wire_contract"


def test_map_is_immutable():
    with pytest.raises(TypeError):
        BY_ID["F33"] = FAMILIES[0]
    with pytest.raises(TypeError):
        ALIASES["F37"] = "F01"
    with pytest.raises(TypeError):
        DETAIL_TO_FAMILY["J21"] = "F01"
    with pytest.raises(dataclasses.FrozenInstanceError):
        BY_ID["F33"].title = "changed"


def test_scopes_and_foundations_do_not_enable_planning():
    assert BY_ID["F50"].scope == "experimental_planning"
    assert BY_ID["F65"].kind == "artifact"
    assert BY_ID["F66"].kind == "provider"
    assert all(BY_ID[f].kind == "foundation" for f in ("F26", "F30", "F31", "F68"))
    assert BY_ID["F71"].kind == "support"
    assert not Config().planner.enabled
    assert not {r["id"] for r in history()["excluded_details"]} & set(DETAIL_TO_FAMILY)


def test_duplicate_or_dropped_detail_is_rejected():
    duplicate = dataclasses.replace(FAMILIES[1], details=FAMILIES[1].details + FAMILIES[0].details)
    with pytest.raises(ValueError, match="more than one family"):
        report.validate((FAMILIES[0], duplicate, *FAMILIES[2:]), history())
    missing = dataclasses.replace(FAMILIES[0], details=FAMILIES[0].details[1:])
    with pytest.raises(ValueError, match="cover every"):
        report.validate((missing, *FAMILIES[1:]), history())


@pytest.mark.parametrize("field,value", [("purpose", ""), ("boundary", ""), ("scope", "bad"),
                                         ("kind", "bad"), ("coverage", "accepted")])
def test_required_family_metadata(field, value):
    family = dataclasses.replace(FAMILIES[0], **{field: value})
    with pytest.raises(ValueError, match="Incomplete"):
        report.validate((family, *FAMILIES[1:]), history())


def test_duplicate_family_id_is_rejected_before_indexing():
    with pytest.raises(ValueError, match="Duplicate family ID"):
        report.validate((*FAMILIES, FAMILIES[0]), history())


@pytest.mark.parametrize("change", [{"F37": "missing"}, {"F37": "F37"},
                                   {"F37": "F02"}, {"F33": "F01"}])
def test_invalid_aliases_are_rejected(change):
    with pytest.raises(ValueError, match="Invalid direct family alias"):
        report.validate(FAMILIES, history(), aliases={**ALIASES, **change})


def test_history_assignment_cannot_be_rewritten_to_current_owner():
    data = history()
    row = next(r for r in data["entries"] if r["family_id"] == "F37")
    row["family_id"] = "F33"
    with pytest.raises(ValueError, match="Frozen historical"):
        report.validate(FAMILIES, data)


def test_missing_implementation_owner_is_rejected():
    owner = dataclasses.replace(FAMILIES[0].owners[0], symbol="no_such_capability")
    family = dataclasses.replace(FAMILIES[0], owners=(owner,))
    with pytest.raises(ValueError, match="Missing named implementation owner"):
        report.validate((family, *FAMILIES[1:]), history())
    family = dataclasses.replace(family, owners=(dataclasses.replace(owner, path="cria/missing.py", symbol=""),))
    with pytest.raises(ValueError, match="Missing implementation owner"):
        report.validate((family, *FAMILIES[1:]), history())


def test_duplicate_atomic_ownership_is_rejected():
    with pytest.raises(ValueError, match="Duplicate atomic"):
        report.validate(FAMILIES, history(), definitions=(*DEFINITIONS, DEFINITIONS[0]))


@pytest.mark.parametrize("changes", [{"family_id": "missing"}, {"family_id": "F50"},
                                    {"stage": ""}, {"state": ""}, {"services": ()},
                                    {"scope": "native_artifacts"}, {"default_level": True},
                                    {"dependencies": ("missing",)},
                                    {"dependencies": (DEFINITIONS[0].policy.id,)}])
def test_invalid_atomic_contracts_are_rejected(changes):
    d = dataclasses.replace(DEFINITIONS[0], policy=dataclasses.replace(DEFINITIONS[0].policy, **changes))
    with pytest.raises(ValueError):
        report.validate(FAMILIES, history(), definitions=(d, *DEFINITIONS[1:]))


def test_real_experimental_step_definition_is_valid_without_enabling_planning():
    from cria import steppreparation
    assert any(d is steppreparation.DEFINITION for d in DEFINITIONS)
    assert steppreparation.DEFINITION.policy.scope == "experimental"
    assert BY_ID[steppreparation.DEFINITION.policy.family_id].scope == "experimental_planning"
    assert not Config().planner.enabled
    executable_code = {d.execute.__code__ for d in DEFINITIONS}
    def reject_execution(frame, event, arg):
        if event == "call" and frame.f_code in executable_code:
            raise AssertionError("Metadata generation executed a policy")
    previous = sys.getprofile()
    try:
        sys.setprofile(reject_execution)
        report.validate(FAMILIES, history())
        rendered = report.render()  # In memory only; never refresh the moving REPORT.
    finally:
        sys.setprofile(previous)
    assert "scope `experimental`" in rendered
    assert not Config().planner.enabled


@pytest.mark.parametrize("source,scope,family,message", [
    ("step", "runtime", "F50", "incompatible atomic family"),
    ("argument", "experimental", "F03", "incompatible atomic family"),
    ("argument", "runtime", "F65", "incompatible atomic family"),
    ("argument", "runtime", "F66", "incompatible atomic family"),
    ("step", "experimental", "F65", "incompatible atomic family"),
    ("step", "experimental", "F66", "incompatible atomic family"),
    ("step", "experimental_planning", "F50", "invalid executable definition"),
    ("argument", "unknown", "F03", "invalid executable definition"),
])
def test_atomic_scope_must_match_exact_family_scope(source, scope, family, message):
    from cria import steppreparation
    original = steppreparation.DEFINITION if source == "step" else DEFINITIONS[0]
    # Keep the real registry intact: relocating its sole F03 member would fail
    # family completeness before the scope boundary this counterexample tests.
    changed = dataclasses.replace(original, policy=dataclasses.replace(
        original.policy, id=original.policy.id + "-scope-counterexample", scope=scope, family_id=family))
    definitions = (*DEFINITIONS, changed)
    with pytest.raises(ValueError, match=message):
        report.validate(FAMILIES, history(), definitions=definitions)


def test_atomic_metadata_copy_is_not_an_authoritative_definition():
    with pytest.raises(ValueError, match="authoritative source definition"):
        report.validate(FAMILIES, history(), definitions=(dataclasses.replace(DEFINITIONS[0]), *DEFINITIONS[1:]))


def test_executable_ownership_does_not_require_manual_family_bindings():
    families = tuple(dataclasses.replace(f, owners=())
                     if any(d.policy.family_id == f.id for d in DEFINITIONS) else f for f in FAMILIES)
    report.validate(families, history())


def test_cohesive_source_module_can_own_multiple_explicit_definitions():
    from cria.outputpolicies import RECOVERY
    for index, definition in enumerate(RECOVERY):
        assert report.executable_owner(definition) == (
            "cria/outputpolicies.py", "RECOVERY", f"RECOVERY[{index}]")
        with pytest.raises(ValueError, match="authoritative source definition"):
            report.executable_owner(dataclasses.replace(definition))


def test_forward_dependency_and_missing_prompt_are_rejected():
    first = DEFINITIONS[0]
    for changes, message in (({"dependencies": (DEFINITIONS[1].policy.id,)}, "dependency/order"),
                             ({"prompts": ("no_such_taxonomy_prompt",)}, "Missing implementation")):
        definition = dataclasses.replace(first, policy=dataclasses.replace(first.policy, **changes))
        with pytest.raises(ValueError, match=message):
            report.validate(FAMILIES, history(), definitions=(definition, DEFINITIONS[1]))


def test_scope_and_historical_ownership_are_structurally_checked():
    families = tuple(dataclasses.replace(f, scope="gated_runtime") if f.id == "F65" else f for f in FAMILIES)
    with pytest.raises(ValueError, match="scope/coverage"):
        report.validate(families, history())
    family = dataclasses.replace(FAMILIES[1], lineage=FAMILIES[1].lineage + FAMILIES[0].lineage)
    with pytest.raises(ValueError, match="Duplicate historical family ownership"):
        report.validate((FAMILIES[0], family, *FAMILIES[2:]), history())


def test_migrated_claim_cannot_omit_hooks_or_regressions():
    from cria.assistcontract import Reference
    ref = Reference("tests/test_assist_family_registry.py", "test_migrated_claim_cannot_omit_hooks_or_regressions")
    for hooks, regressions in (((), (ref,)), ((ref,), ()), ((), ())):
        definition = dataclasses.replace(DEFINITIONS[0], policy=dataclasses.replace(
            DEFINITIONS[0].policy, migrated=True, hooks=hooks, regressions=regressions))
        with pytest.raises(ValueError, match="Migrated policy must declare"):
            report.validate(FAMILIES, history(), definitions=(definition, *DEFINITIONS[1:]))


def test_hook_references_are_real_source_declarations_not_arbitrary_strings():
    from cria.assistcontract import Reference
    assert report.reference_line(Reference(
        "tests/test_assist_family_registry.py", "test_hook_references_are_real_source_declarations_not_arbitrary_strings")) > 0
    for reference in ("not a reference", Reference("../outside.py", "hook"),
                      Reference("tests/test_assist_family_registry.py", "missing_hook")):
        with pytest.raises(ValueError):
            report.reference_line(reference)


def test_generated_map_agrees_and_discloses_pending_coverage():
    rendered = report.render()
    assert report.REPORT.read_text() == rendered
    assert all(f"### {f.id} — {f.title}" in rendered for f in FAMILIES)
    assert f"{len(DEFINITIONS)} registered atomic definitions" in rendered
    assert all(rendered.count(f"- `{d.policy.id}` —") == 1 for d in DEFINITIONS)
    for definition in DEFINITIONS:
        policy = definition.policy
        assert f"Stage `{policy.stage}`; default level {policy.default_level}; scope `{policy.scope}`." in rendered
        for reference in (*policy.hooks, *policy.regressions):
            assert f"{reference.path}:{reference.symbol}" in rendered
    assert "Required wire-fit source contract; no removable atomic members" in rendered
    assert all(f'<a id="{old.lower()}"></a>' in rendered for old in ALIASES)
    assert "pending R1/R7 migration" in rendered
    assert "Planning remains OFF" in rendered
    assert "child_score_range" not in rendered and "Score range" not in rendered


def test_levels_document_lists_registry_by_default_level_with_family_anchors():
    from collections import Counter
    import re
    text = report.render_levels()
    assert report.LEVELS.read_text() == text
    sections = re.split(r"(?m)^## L([0-5]) — ", text)
    assert sections[0] == "" and sections[1::2] == list("012345")
    actual = []
    family_report = report.REPORT.read_text()
    names = ("Pure proxy", "Tool-call fixes", "Simple tools", "Context fixes", "Completion refusals", "Assists")
    for raw_level, section in zip(sections[1::2], sections[2::2]):
        level = int(raw_level)
        lines = section.strip().splitlines()
        assert lines[0] == names[level]
        for row in lines[1:]:
            if not row:
                continue
            match = re.fullmatch(r"- `([^`]+)` — \[([^]]+)\]\(REPORT\.md#(f[0-9]+)\)", row)
            assert match, row
            atomic_id, family, anchor = match.groups()
            assert anchor == family.lower()
            assert f'<a id="{anchor}"></a>' in family_report
            actual.append((atomic_id, level, family))
    expected = [(d.policy.id, level, d.policy.family_id) for level in range(6)
                for d in DEFINITIONS if d.policy.default_level == level]
    assert Counter(actual) == Counter(expected)
    assert actual == expected


def test_check_rejects_stale_levels_document(monkeypatch, tmp_path, capsys):
    family_report = tmp_path / "REPORT.md"
    levels = tmp_path / "LEVELS.md"
    family_report.write_text("family\n")
    levels.write_text("stale\n")
    monkeypatch.setattr(report, "REPORT", family_report)
    monkeypatch.setattr(report, "LEVELS", levels, raising=False)
    monkeypatch.setattr(report, "render", lambda: "family\n")
    monkeypatch.setattr(report, "render_levels", lambda: "levels\n", raising=False)
    monkeypatch.setattr(sys, "argv", ["build_report.py", "--check"])
    assert report.main() == 1
    assert "LEVELS" in capsys.readouterr().err
    levels.write_text("levels\n")
    assert report.main() == 0
