"""The off-ramp cadence is minutes of coder work, turned into turns by cria's own measured pace."""
import pytest

from cria import loop
from cria.loop import LoopContext, PlanSession, _CoderReplyReceipts
from cria.plan import Plan, PlanItem

from loop_planner_helpers import Rlog


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def session():
    return PlanSession(plan=Plan(id="p", task="t", created="c", items=[PlanItem("t")]), synthetic=True)


def first_check_turn(monkeypatch, turn_seconds, ctx, *, blocked=()):
    """Run acting turns of `turn_seconds` each through the real coder-call bracket; return the turn the
    off-ramp first runs on (a turn in `blocked` is skipped by the caller, as _periodic_satisfaction does)."""
    clock = Clock()
    monkeypatch.setattr(loop, "_now", clock)
    sess = session()
    replies = _CoderReplyReceipts(lambda b, r: clock.__setattr__("now", clock.now + turn_seconds) or b"{}", sess)
    ran = []
    for turn in range(1, 400):
        sess.drive_count += 1
        replies.chat({}, Rlog())
        clock.now += 999                       # cria's own check/judge time between coder calls: never counted
        if turn in blocked or not loop.periodic_check_due(sess.drive_count, *loop.session_cadence(sess, ctx),
                                                          sess.task_review_last_drive):
            continue
        sess.task_review_last_drive = sess.drive_count
        ran.append(turn)
        if len(ran) == 2:
            return ran
    return ran


@pytest.mark.parametrize("per_minute,start,every", [(1, 8, 5), (2, 16, 8), (4, 32, 16)])
def test_defaults_ask_in_turns_proportional_to_measured_pace(monkeypatch, per_minute, start, every):
    ran = first_check_turn(monkeypatch, 60 / per_minute, LoopContext(planner=None, coder_chat=None,
                                                                    reasoner_chat=None, runs_dir=""))
    assert ran == [start, start + every]       # defaults: 8 / 4 minutes, clamped to [5, 60] turns


def test_a_slower_coder_is_asked_in_fewer_turns_than_a_fast_one(monkeypatch):
    ctx = LoopContext(planner=None, coder_chat=None, reasoner_chat=None, runs_dir="")
    assert first_check_turn(monkeypatch, 30, ctx)[0] < first_check_turn(monkeypatch, 5, ctx)[0]


def test_clamps_and_unmeasured_and_disabled():
    ctx = LoopContext(planner=None, coder_chat=None, reasoner_chat=None, runs_dir="")
    sess = session()
    assert loop.session_cadence(sess, ctx) == (5, 5)                  # unmeasured: the low end
    sess.coder_seconds, sess.coder_timed_turns = 1.0, 1               # very fast: 480 turns -> max
    assert loop.session_cadence(sess, ctx) == (60, 60)
    sess.coder_seconds = 600.0                                        # very slow: 0.8 turns -> min
    assert loop.session_cadence(sess, ctx) == (5, 5)
    ctx = LoopContext(planner=None, coder_chat=None, reasoner_chat=None, runs_dir="",
                      satisfaction_check_start_minutes=0)
    assert not loop.periodic_check_due(1000, *loop.session_cadence(sess, ctx))


def test_a_blocked_due_turn_retries_on_the_next_one(monkeypatch):
    ctx = LoopContext(planner=None, coder_chat=None, reasoner_chat=None, runs_dir="")
    assert first_check_turn(monkeypatch, 60, ctx, blocked={8})[0] == 9
