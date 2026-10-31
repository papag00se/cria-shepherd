"""cria.completionreview (authoritative whole-task evaluation): an unaskable claim never gathers evidence or judges, a negative verdict
invalidates held success, only a later true releases, and every review says which trigger asked."""
from types import SimpleNamespace
import pytest
from cria import completionreview as cr

class Calls:
    """The lazy sources and the judge, recording what was asked and in what order."""
    def __init__(self, verdict=(True, 'all green', 'ship it')): self.calls, self.verdict, self.events = [], verdict, []
    def input(self, trigger=cr.ReviewTrigger.CLAIM, task='fix the parser'):
        def src(name, value): return lambda: (self.calls.append(name), value)[1]
        def judge(task, evidence): self.calls.append(('judge', task, evidence)); return self.verdict
        return cr.ReviewInput(trigger, task, src('history', 'HISTORY|'), src('checks', 'CHECKS'), judge, src('diagnosis', 'no task known'),
                              SimpleNamespace(emit=lambda kind, **f: self.events.append((kind, f))))

def state(): return SimpleNamespace(latest_satisfaction=None, latest_satisfaction_evidence='', pending_done='write done', pending_done_parts=(('a',),))

def test_a_claim_without_a_known_task_is_unaskable_gathers_nothing_and_clears_held_success():
    """Never invent a task from compacted history: the empty-task claim records unsatisfied with the diagnosis, calls no evidence source and no judge."""
    c, st = Calls(), state(); result = cr.review_task(c.input(task=''), st)
    assert result.status is cr.ReviewStatus.UNKNOWN_TASK and result.reason == 'no task known' and not result.approved
    assert c.calls == ['diagnosis'] and st.latest_satisfaction is False and st.pending_done == '' and st.pending_done_parts == ()
    assert c.events[0][1]['status'] == 'unknown-task' and c.events[0][1]['satisfied'] is False

def test_a_scheduled_review_judges_even_without_a_task_and_composes_history_then_checks():
    """Only the reactive claim is guarded: a scheduled review asks the judge, with evidence = history + checks in that order."""
    c, st = Calls(), state(); result = cr.review_task(c.input(cr.ReviewTrigger.SCHEDULED, task=''), st)
    assert result.approved and c.calls == ['history', 'checks', ('judge', '', 'HISTORY|CHECKS')] and (result.reason, result.action) == ('all green', 'ship it')

def test_a_negative_verdict_invalidates_held_success_and_a_later_true_releases_it_without_inventing_any():
    """REJECTED clears the pending completion; APPROVED records the evidence and leaves the pending claim as it was (a verdict is not a cache)."""
    c, st = Calls((False, 'tests fail', 'fix them')), state(); rejected = cr.review_task(c.input(), st)
    assert rejected.status is cr.ReviewStatus.REJECTED and st.latest_satisfaction is False and st.latest_satisfaction_evidence == 'tests fail' and st.pending_done == ''
    c2, st2 = Calls(), state(); approved = cr.review_task(c2.input(), st2)
    assert approved.approved and st2.latest_satisfaction is True and st2.latest_satisfaction_evidence == 'all green' and st2.pending_done == 'write done'

@pytest.mark.parametrize('trigger,level,value', [(cr.ReviewTrigger.CLAIM, 4, 'reactive-claim'), (cr.ReviewTrigger.PLAN_EXHAUSTED, 4, 'reactive-plan-exhausted'), (cr.ReviewTrigger.SCHEDULED, 5, 'scheduled')])
def test_every_review_event_names_its_trigger_and_scheduled_reviews_belong_to_the_higher_level(trigger, level, value):
    """The event carries the trigger value and status; only the scheduled review is an L5 behaviour."""
    c = Calls(); cr.review_task(c.input(trigger), state())
    assert trigger.level == level and c.events == [('loop.task_review', {'assist_id': 'whole-task-review', 'family_id': 'F34', 'trigger': value, 'satisfied': True, 'status': 'approved'})]
    with pytest.raises(ValueError): cr.ReviewInput('claim', 't', None, None, None, None, None)
