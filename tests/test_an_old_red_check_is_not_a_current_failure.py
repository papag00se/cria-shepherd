"""A completion judge must distinguish an old failure from current evidence."""
from cria import loop
from cria.completionreview import ReviewTrigger
from test_loop import _Rlog
from test_generation_driver_policy import setup_driver


def test_changed_workspace_does_not_make_old_failure_current():
    _, session, _ = setup_driver()
    session.last_gate_red = True
    session.last_gate_flag = 'compiler: original failure, exact checker text'
    session.gate_fresh = False
    text = loop._gate_notes(session)
    assert session.last_gate_flag in text
    assert 'currently FAILING' not in text
    assert 'historical' in text.lower()
    assert 'not establish' in text.lower()


def test_whole_task_review_delivers_historical_failure_without_approving(monkeypatch):
    driver, session, body = setup_driver()
    session.last_gate_red = True
    session.last_gate_flag = 'compiler: earlier failure'
    session.gate_fresh = False
    seen = []
    def judge(task, evidence, *args, **kwargs):
        seen.append((task, evidence))
        return False, '', ''
    monkeypatch.setattr(loop, 'judge_satisfaction', judge)
    result = driver._review_task(session, body, _Rlog(), trigger=ReviewTrigger.CLAIM)
    assert not result.approved
    assert seen[0][0] == session.plan.task
    assert session.last_gate_flag in seen[0][1]
    assert 'currently FAILING' not in seen[0][1]
    assert 'HISTORICAL CHECK OBSERVATION' in seen[0][1]


def test_fresh_red_check_still_reaches_completion_judge_as_current():
    _, session, _ = setup_driver()
    session.last_gate_red = True
    session.last_gate_flag = 'compiler: current failure'
    session.gate_fresh = True
    assert 'currently FAILING' in loop._gate_notes(session)
    assert session.last_gate_flag in loop._gate_notes(session)
