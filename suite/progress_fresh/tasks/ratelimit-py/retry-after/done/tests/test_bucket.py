from ratelimit.bucket import TokenBucket


class Fake:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_burst_then_refill():
    c = Fake()
    b = TokenBucket(rate=1, capacity=2, clock=c)
    assert b.allow() and b.allow()
    assert not b.allow()
    c.t = 1.0
    assert b.allow()


def test_retry_after_reports_wait_without_consuming():
    c = Fake()
    b = TokenBucket(rate=2, capacity=1, clock=c)
    assert b.retry_after() == 0.0
    assert b.allow()
    assert b.retry_after() == 0.5
    c.t = 0.25
    assert b.retry_after() == 0.25
    c.t = 0.5
    assert b.allow()
