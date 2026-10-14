"""The operator's family map must remain navigable, complete and non-executing."""
import dataclasses
import importlib.util
import json
from pathlib import Path

import pytest

from cria.assistfamilies import BY_ID, DETAIL_TO_FAMILY, FAMILIES
from cria.config import Config

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("assist_family_report", ROOT / "docs/assist-inventory/build_report.py")
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


def history():
    return json.loads(report.HISTORY.read_text())


def test_operator_approved_identities_are_titled_and_have_one_detail_owner():
    assert tuple(BY_ID) == tuple(f"F{i:02}" for i in range(1,77))
    assert len({family.title for family in FAMILIES}) == 76
    rows = history()["entries"]
    assert len(rows) == len(DETAIL_TO_FAMILY) == 409
    assert {row["id"]:row["family_id"] for row in rows} == dict(DETAIL_TO_FAMILY)
    assert all(f.contract and f.owners and f.details for f in FAMILIES)
    report.validate(FAMILIES, history())  # actual file/declaration existence, no executor imports


def test_map_cannot_mutate_family_titles_or_detail_ownership():
    with pytest.raises(TypeError):
        BY_ID["F37"] = FAMILIES[0]
    with pytest.raises(TypeError):
        DETAIL_TO_FAMILY["J21"] = "F01"
    with pytest.raises(dataclasses.FrozenInstanceError):
        BY_ID["F37"].title = "silently changed"


def test_experimental_and_native_entries_do_not_claim_normal_deployment_or_enable_planning():
    assert BY_ID["F39"].scope == BY_ID["F50"].scope == "experimental_planning"
    assert BY_ID["F65"].scope == "native_artifacts"
    assert BY_ID["F66"].scope == "configured_cli_provider"
    assert not Config().planner.enabled
    assert not ({row["id"] for row in history()["excluded_details"]} & set(DETAIL_TO_FAMILY))


def test_duplicate_or_dropped_detail_is_rejected_not_hidden_by_an_index():
    duplicate = dataclasses.replace(FAMILIES[1], details=FAMILIES[1].details + FAMILIES[0].details)
    with pytest.raises(ValueError, match="more than one family"):
        report.validate((FAMILIES[0], duplicate, *FAMILIES[2:]), history())
    missing = dataclasses.replace(FAMILIES[0], details=FAMILIES[0].details[1:])
    with pytest.raises(ValueError, match="cover every"):
        report.validate((missing, *FAMILIES[1:]), history())


def test_renamed_or_missing_code_owner_is_rejected():
    owner = dataclasses.replace(FAMILIES[0].owners[0], symbol="no_such_capability")
    family = dataclasses.replace(FAMILIES[0], owners=(owner,))
    with pytest.raises(ValueError, match="Missing named implementation owner"):
        report.validate((family, *FAMILIES[1:]), history())
    owner = dataclasses.replace(owner, path="cria/no_such_module.py", symbol="")
    family = dataclasses.replace(family, owners=(owner,))
    with pytest.raises(ValueError, match="Missing implementation owner"):
        report.validate((family, *FAMILIES[1:]), history())


def test_generated_report_matches_code_metadata_and_does_not_publish_score_ranges():
    rendered = report.render()
    assert report.REPORT.read_text() == rendered
    assert all(f"### {f.id} — {f.title}" in rendered for f in FAMILIES)
    assert "child_score_range" not in rendered and "Score range" not in rendered
    assert "Planning remains OFF" in rendered
