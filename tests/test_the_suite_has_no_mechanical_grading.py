import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "suite"


def test_no_task_specific_graders_exist():
    assert not list((SUITE / "tasks").glob("*/verify.py"))
    assert not list((SUITE / "tasks").glob("*/hidden/*"))
    assert not (SUITE / "results" / "gates").exists()


def test_result_rows_contain_only_run_evidence_and_inferred_judgments():
    forbidden = {"score", "max_score", "success", "verify", "verifier_error", "milestones"}
    for line in (SUITE / "results" / "results.jsonl").read_text().splitlines():
        if line.strip():
            assert forbidden.isdisjoint(json.loads(line))


def test_runner_cannot_invoke_a_task_specific_grader():
    source = (SUITE / "run.py").read_text()
    assert 'task_dir / "verify.py"' not in source
    assert '"score":' not in source
    assert '"max_score":' not in source
