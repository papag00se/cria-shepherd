import hashlib

import pytest

from suite import campaign_provenance as provenance


def _hashes():
    return dict(provenance.APPROVED_RUNTIME_SHA256)


def test_exact_report_and_lifecycle_patch_requires_commit_and_then_returns_candidate_head():
    assert provenance._provenance_source_digest() == provenance.PROVENANCE_SOURCE_SHA256
    hashes = _hashes()
    changed = set(hashes) | {provenance.PROVENANCE_PATH}
    assert provenance.INFERENCE_REVISION == "f79cc6146470281b5909cf605b27afca1177e2d1"
    candidate_head = "a" * 40

    with pytest.raises(provenance.ProvenanceError, match="must be committed"):
        provenance.candidate_code_revision(
            provenance.INFERENCE_REVISION, candidate_head, changed, hashes, changed)

    assert provenance.candidate_code_revision(
        provenance.INFERENCE_REVISION, candidate_head, changed, hashes, set()) == candidate_head


@pytest.mark.parametrize("path", [
    "cria/prompts/coder_system.txt",
    "cria/planner.py",
    "suite/sampling.py",
    "suite/tasks/feed-pipeline-java/prompt.txt",
    "suite/tasks/feed-pipeline-java/seed/pom.xml",
    "scripts/live_model.py",
])
def test_changed_prompt_planner_sampling_launch_or_task_input_blocks(path):
    with pytest.raises(provenance.ProvenanceError, match="inference/runtime files"):
        provenance.verify_change_set({path}, _hashes())


def test_a_planner_change_inside_run_owner_is_not_hidden_by_path_allowance():
    hashes = _hashes()
    hashes["suite/run.py"] = hashlib.sha256(b"planner behavior changed").hexdigest()
    with pytest.raises(provenance.ProvenanceError, match="suite/run.py"):
        provenance.verify_change_set({"suite/run.py"}, hashes)


@pytest.mark.parametrize("path", ["suite/battery_status.py", "suite/model_names.py", "AGENTS.md"])
def test_naming_approval_does_not_exempt_future_unreviewed_edits(path):
    hashes = _hashes()
    hashes[path] = hashlib.sha256(b"unreviewed naming or policy change").hexdigest()
    with pytest.raises(provenance.ProvenanceError, match=path.replace(".", r"\.")):
        provenance.verify_change_set({path}, hashes)


def test_a_different_inference_anchor_is_rejected():
    with pytest.raises(provenance.ProvenanceError, match="inference anchor"):
        provenance.validate("other-revision")
