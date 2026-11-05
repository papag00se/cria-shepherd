import pytest

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


@pytest.mark.parametrize('rate,cap', [(0, 1), (-1, 1), (1, 0)])
def test_rejects_bad_arguments(rate, cap):
    with pytest.raises(ValueError):
        TokenBucket(rate=rate, capacity=cap)
