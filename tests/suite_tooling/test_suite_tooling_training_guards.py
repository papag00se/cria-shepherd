"""Training-pipeline stages refuse unqualified or contaminated data: hold-out/leakage guards, quarantine of
ambiguous labels, frozen cohorts, preflight and explicit GPU authority. No GPU, model or network."""
import hashlib
import json
import time
from types import SimpleNamespace

import pytest

from suite.gliclass_probe import load_frozen_cohorts
from suite.onejev_probe import checked_decision, checked_probabilities, file_sha
from suite.training_admit import assess_real, validate_review, verify_disjoint
from suite.training_evaluation import exclusion_index, screen
from suite.training_prepare import choose, partition_rows, sha
from suite.training_preflight import validate_native_result
from suite.training_run import fit_specs, validate_authorization
from suite.training_seed import canonical_input


def row(task, session, raw, family="retrospective", model="one"):
    return {"id": family + "-" + raw, "family": family, "task": task, "session": session,
            "candidate_sha256": raw, "run_ids": [task + "-run"], "coder_model": model}


def test_overlapping_inputs_or_sessions_quarantine_the_whole_component_but_a_task_stays_together():
    """A duplicate input or shared session across tasks would leak train into test: both rows are QUARANTINEd
    (and never selected); one task is never split by model/run."""
    dup = [row("feed-pipeline-java", "a", "same"), row("rust-toml-cli", "b", "same")]
    shared = [row("feed-pipeline-java", "s", "x"), row("handles-cli-node", "s", "y")]
    for rows in (dup, shared):
        partition_rows(rows)
        assert {r["partition"] for r in rows} == {"QUARANTINE"} and choose(rows) == set()
    a, b = row("orders-api-py", "a", "a"), row("orders-api-py", "b", "b", model="two")
    partition_rows([a, b])
    assert a["partition"] == b["partition"] == "TRAIN" and a["group_id"] == b["group_id"]


def test_selection_is_label_blind_and_order_independent():
    """Choosing annotation rows ignores historical labels/usefulness and input order, and spreads coder models."""
    rows = [row("orders-api-py", str(i), str(i), model=str(i % 3)) for i in range(30)]
    partition_rows(rows)
    first = choose(rows)
    for i, r in enumerate(rows):
        r.update(historical_label="PLAN" if i % 2 else "RETROSPECTIVE", usefulness=100 - i)
    assert choose(list(reversed(rows))) == first and len(first) == 12
    assert {r["coder_model"] for r in rows if r["id"] in first} == {"0", "1", "2"}


def case():
    return {"id": "a", "family": "dictation", "complete_input": {"public_directive": "Inspect the error."},
            "partition": "TRAIN", "group_id": "g-a", "task": "t-a", "all_sessions": ["s-a"],
            "all_run_ids": ["r-a"], "candidate_sha256": "raw-a"}


def review(label="DESCRIBES", **extra):
    return {"id": "a", "family": "dictation", "label": label, "review_status": "REVIEWED",
            "input_sha256": hashlib.sha256(b'{"public_directive":"Inspect the error."}').hexdigest(),
            "support_field": "public_directive", "support_start": 0, "support_end": 7, "support_text": "Inspect",
            "reason": "Names the investigation.", **extra}


@pytest.mark.parametrize("main,indep,local,expected", [
    (review(), review("DICTATES"), True, "LABEL_DISAGREEMENT"),            # no majority / no main override
    (review("UNKNOWN"), review("UNKNOWN"), True, "UNRESOLVED_LABEL"),       # unknown is never a negative
    (review(), review(), False, "LOCAL_USE_NOT_APPROVED"),                 # privacy hold beats agreement
    (review(), review(local_use_approved=False), True, "REVIEWER_LOCAL_USE_HOLD")])
def test_real_cases_are_admitted_only_on_agreeing_approved_reviews(main, indep, local, expected):
    """Any disagreement, unresolved label, or privacy hold quarantines the case."""
    assert expected in assess_real(case(), main, indep, local)
    assert assess_real(case(), review(), review(), True) == []


def test_review_must_quote_the_exact_input_and_split_ids_must_be_disjoint():
    """Support text/hash are validated, not merely present; a session shared across partitions stops assembly."""
    bad = review(support_text="different")
    with pytest.raises(ValueError):
        validate_review(case(), bad)
    with pytest.raises(ValueError):
        validate_review(case(), review(input_sha256="wrong"))
    b = {**case(), "id": "b", "partition": "DEV", "group_id": "g-b", "task": "t-b",
         "all_sessions": ["other", "s-a"], "all_run_ids": ["r-b"], "candidate_sha256": "raw-b"}
    with pytest.raises(ValueError, match="session"):
        verify_disjoint([case(), b])


def fresh(tmp_path):
    raw = json.dumps({"candidate": "Inspect the real error.", "task": "Build a tide sensor dashboard.",
                      "captured_at_ns": 30}).encode()
    path = tmp_path / "source.json"
    path.write_bytes(raw)
    src = {"request": str(path), "request_sha256": sha(raw)}
    text = "Inspect the real error."
    c = {"id": "new", "family": "dictation", "task": "tide", "group_id": "tides", "all_sessions": ["ns"],
         "all_run_ids": ["nr"], "ancestor_tasks": [], "ancestry_complete": True, "source_kind": "real_public_candidate",
         "complete_input": {"public_directive": text}, "input_sha256": sha(canonical_input({"public_directive": text})),
         "candidate_sha256": sha(text.encode()),
         "source": {**src, "pointer": "/candidate", "decoded_character_span": [0, len(text)], "utf8_byte_span": [0, len(text)]},
         "task_source": {**src, "pointer": "/task"}, "capture_event_source": {**src, "pointer": "/captured_at_ns"}}
    x = exclusion_index([], [])
    r = {"task": "tide", "group_id": "tides", "reserved_at_ns": 20, "task_sha256": sha(b"Build a tide sensor dashboard."),
         "exclusions_sha256": sha(canonical_input(x)), "partition": "EVAL_PROSPECTIVE_SEALED",
         "novelty_reviews": [{"reviewer": w, "decision": "INDEPENDENT_SCENARIO", "reason": "compared"} for w in ("ra", "rb")]}
    k = {"collection_start_ns": 10, "exclusions_sha256": sha(canonical_input(x)),
         "reservations": {"tide": sha(canonical_input(r))}}
    return c, r, k, x


def rebind(c, r, k, x):
    k["exclusions_sha256"] = r["exclusions_sha256"] = sha(canonical_input(x))
    k["reservations"][c["task"]] = sha(canonical_input(r))


@pytest.mark.parametrize("kind", ["task", "session", "run", "group"])
def test_known_ancestry_blocks_freshness_even_under_a_new_case_name(tmp_path, kind):
    """A held-out case sharing any task/session/run/group edge with excluded history is not fresh."""
    c, r, k, x = fresh(tmp_path)
    assert screen(c, r, k, x, time.time_ns()) == []
    value = "old-" + kind
    x[kind].append(value)
    {"task": lambda: c["ancestor_tasks"].append(value), "session": lambda: c["all_sessions"].append(value),
     "run": lambda: c["all_run_ids"].append(value), "group": lambda: c.update(group_id=value)}[kind]()
    r["group_id"] = c["group_id"]
    rebind(c, r, k, x)
    assert "KNOWN_ANCESTRY_OR_EXACT_INPUT" in screen(c, r, k, x, time.time_ns())


def test_blinded_intake_refuses_labels_unknown_lineage_and_self_reviewed_novelty(tmp_path):
    """Labels/annotation channels reach no blinded reviewer; unknown lineage or one reviewer never passes."""
    c, r, k, x = fresh(tmp_path)
    c["ancestry_complete"] = False
    assert "UNRESOLVED_ANCESTRY" in screen(c, r, k, x, time.time_ns())
    c, r, k, x = fresh(tmp_path)
    r["novelty_reviews"][1]["reviewer"] = "ra"
    rebind(c, r, k, x)
    assert "NOVELTY_NOT_INDEPENDENTLY_REVIEWED" in screen(c, r, k, x, time.time_ns())
    for field in ("label", "teacher_output"):
        c[field] = "hidden"
        with pytest.raises(ValueError, match="blinded"):
            screen(c, r, k, x, time.time_ns())
        c.pop(field)
    c["all_sessions"] = [""]
    with pytest.raises(ValueError, match="lineage"):
        screen(c, r, k, x, time.time_ns())


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


def test_calibration_folds_exclude_their_task_and_gpu_training_needs_bound_authority():
    """No training id appears in its own calibration fold; GPU training needs explicit authorization bound to
    this recipe and device."""
    folds = {"folds": [{"calibration_task": "held-" + i, "real_training_ids": sorted(set("abc") - {i}),
                        "real_calibration_ids": [i], "mixed_arm_synthetic_training_ids": ["s"]} for i in "abc"]}
    for job in fit_specs([17, 29], folds, ["a", "b", "c"], ["s"]):
        if job["calibration_task"]:
            assert set(job["train_ids"]).isdisjoint(job["predict_ids"])
    leaky = {"folds": [{"calibration_task": "h", "real_training_ids": ["a"], "real_calibration_ids": ["a"],
                        "mixed_arm_synthetic_training_ids": []}]}
    with pytest.raises(ValueError, match="fold"):
        fit_specs([17], leaky, ["a"], [])
    auth = {"training_authorized": True, "gpu_uuid": "gpu", "recipe_sha256": "recipe"}
    validate_authorization(auth, "recipe", "gpu")
    for field, value in (("training_authorized", False), ("gpu_uuid", "other"), ("recipe_sha256", "changed")):
        with pytest.raises(ValueError, match="authorization"):
            validate_authorization({**auth, field: value}, "recipe", "gpu")


def test_preflight_gates_a_fit_a_noop_or_memorizing_run_cannot_qualify():
    """Missing preflight stops the matrix before loading inputs; wrong routing/no parameter update/memorization fails."""
    from suite.training_run import run
    with pytest.raises(ValueError, match="preflight is required"):
        run(SimpleNamespace(root="unused", recipe="unused.json", integrity_receipt=None))
    ok = lambda: {**{n: True for n in ("optimizer_membership_exact", "decoding_correct", "routing_gradients_correct",
                                       "tiny_final_overfit_all_eight", "all_existing_quarantines_unchanged")},
                  "arms": [{"epochs": 200, "all_groups_update_after_warmup": True, "checks": [{"step": 200, "summaries": {
                      f: {"count": 4, "risk_coverage": {"0.5": {"disagreements_with_reviewed_target": 0}}}
                      for f in ("retrospective", "dictation")}}]}]}
    validate_native_result(ok())
    for name in ("optimizer_membership_exact", "decoding_correct", "tiny_final_overfit_all_eight"):
        bad = ok()
        bad[name] = False
        with pytest.raises(ValueError, match="preflight incomplete"):
            validate_native_result(bad)
    bad = ok()
    bad["arms"][0]["all_groups_update_after_warmup"] = False
    with pytest.raises(ValueError, match="parameter update"):
        validate_native_result(bad)
    bad = ok()
    bad["arms"][0]["checks"][0]["summaries"]["dictation"]["risk_coverage"]["0.5"]["disagreements_with_reviewed_target"] = 1
    with pytest.raises(ValueError, match="memorize"):
        validate_native_result(bad)


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
