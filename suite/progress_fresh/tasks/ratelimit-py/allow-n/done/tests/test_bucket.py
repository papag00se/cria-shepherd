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


def test_cost_and_denied_keeps_tokens():
    c = Fake()
    b = TokenBucket(rate=1, capacity=3, clock=c)
    assert not b.allow(cost=4)
    assert b.allow(cost=2)
    assert not b.allow(cost=2)
    assert b.allow(cost=1)
