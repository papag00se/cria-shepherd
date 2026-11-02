"""Offline classifier experiments: frozen cohort loading and native probe scoring. No GPU, model or network."""
import json

import pytest

from suite.gliclass_probe import load_frozen_cohorts
from suite.onejev_probe import checked_decision, checked_probabilities, file_sha


def cohort(i, partition="TRAIN"):
    return {"id": i, "partition": partition, "group_id": i, "input_sha256": i}


def freeze(root, train, held):
    for name, rows in (("train-cases.json", train), ("held-cases.json", held)):
        (root / name).write_text(json.dumps(rows))
    contract = {"train_count": len(train), "held_count": len(held),
                "input_sha256": {str(root / n): file_sha(root / n) for n in ("train-cases.json", "held-cases.json")}}
    (root / "contract.json").write_text(json.dumps(contract))
    return contract


@pytest.mark.parametrize("violation", ["ok", "id", "group", "input", "partition", "duplicate", "bytes", "count"])
def test_frozen_cohorts_admit_only_disjoint_declared_data(tmp_path, violation):
    """Training exposure cannot pass as held evaluation (shared id/group/input, TRAIN partition, dupes), and the
    declared bytes/count are frozen: mutation after the receipt is refused."""
    train, held = [cohort("real")], [cohort("held", "SYNTHETIC_TEST")]
    key = {"id": "id", "group": "group_id", "input": "input_sha256"}.get(violation)
    if key:
        held[0][key] = "real"
    if violation == "partition":
        held[0]["partition"] = "TRAIN"
    if violation == "duplicate":
        train.append(dict(train[0]))
    contract = freeze(tmp_path, train, held)
    if violation == "bytes":
        (tmp_path / "train-cases.json").write_text(json.dumps([cohort("replacement")]))
    if violation == "count":
        (tmp_path / "contract.json").write_text(json.dumps({**contract, "train_count": 2}))
    if violation == "ok":
        assert load_frozen_cohorts(tmp_path) == (contract, train, held)
    else:
        with pytest.raises(ValueError):
            load_frozen_cohorts(tmp_path)


@pytest.mark.parametrize("answer", [{"RETROSPECTIVE": .5, "PLAN": float("nan")}, {"RETROSPECTIVE": .5, "PLAN": .7},
                                    {"RETROSPECTIVE": -.1, "PLAN": 1.1}, {"DESCRIBES": .5, "DICTATES": .5}])
def test_probe_scores_only_valid_native_probabilities_and_the_native_choice(answer):
    """NaN, non-normalized, negative, or wrong-head probabilities are not scored; the native choice (taken
    from unrounded values) is trusted over a recount, and a conflicting choice is refused."""
    with pytest.raises(ValueError):
        checked_probabilities({"probabilities": answer}, "retrospective")
    tie = {"choice": "PLAN", "probabilities": {"RETROSPECTIVE": .5, "PLAN": .5}}
    assert checked_decision(tie, "retrospective") == ("PLAN", tie["probabilities"])
    with pytest.raises(ValueError, match="native choice conflicts"):
        checked_decision({"choice": "RETROSPECTIVE", "probabilities": {"RETROSPECTIVE": .2, "PLAN": .8}}, "retrospective")
