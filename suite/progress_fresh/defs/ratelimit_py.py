from suite.progress_fresh.dsl import ed

SEED = {
"ratelimit/bucket.py": '''import time


class TokenBucket:
    def __init__(self, rate, capacity, clock=time.monotonic):
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.clock = clock
        self.last = clock()

    def allow(self):
        now = self.clock()
        self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
        self.last = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False
''',
"tests/test_bucket.py": '''from ratelimit.bucket import TokenBucket


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
''',
}
B = SEED["ratelimit/bucket.py"]
T = SEED["tests/test_bucket.py"]
TASK = dict(extension=True, name="ratelimit-py", language="Python", seed=SEED,
unrelated={"ratelimit/bucket.py": "\"\"\"Token bucket rate limiter.\"\"\"\n" + B},
reqs=[
dict(id="validate-args", text="Constructing a TokenBucket with rate <= 0 or capacity < 1 must raise ValueError; add tests for both bad arguments.",
 partial={"ratelimit/bucket.py": ed(B, ("        self.rate = rate\n", "        if rate <= 0:\n            raise ValueError('rate must be positive')\n        self.rate = rate\n"))},
 done={"ratelimit/bucket.py": ed(B, ("        self.rate = rate\n", "        if rate <= 0:\n            raise ValueError('rate must be positive')\n        if capacity < 1:\n            raise ValueError('capacity must be at least 1')\n        self.rate = rate\n")),
       "tests/test_bucket.py": ed(T, ("from ratelimit.bucket", "import pytest\n\nfrom ratelimit.bucket")) + "\n\n@pytest.mark.parametrize('rate,cap', [(0, 1), (-1, 1), (1, 0)])\ndef test_rejects_bad_arguments(rate, cap):\n    with pytest.raises(ValueError):\n        TokenBucket(rate=rate, capacity=cap)\n"}),
dict(id="retry-after", text="Add retry_after() returning how many seconds until the next token is available (0.0 when one is available now) without consuming a token, and test it after the bucket is drained.",
 partial={"ratelimit/bucket.py": B + "\n    def retry_after(self):\n        if self.tokens >= 1:\n            return 0.0\n        return (1 - self.tokens) / self.rate\n"},
 done={"ratelimit/bucket.py": B + "\n    def retry_after(self):\n        now = self.clock()\n        tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)\n        if tokens >= 1:\n            return 0.0\n        return (1 - tokens) / self.rate\n",
       "tests/test_bucket.py": T + "\n\ndef test_retry_after_reports_wait_without_consuming():\n    c = Fake()\n    b = TokenBucket(rate=2, capacity=1, clock=c)\n    assert b.retry_after() == 0.0\n    assert b.allow()\n    assert b.retry_after() == 0.5\n    c.t = 0.25\n    assert b.retry_after() == 0.25\n    c.t = 0.5\n    assert b.allow()\n"}),
dict(id="allow-n", text="allow() should accept a cost parameter (default 1) so heavy requests can take several tokens at once; a request costing more than the capacity must never be allowed, and a denied request must not consume tokens. Test the denied-keeps-tokens case.",
 partial={"ratelimit/bucket.py": ed(B, ("def allow(self):", "def allow(self, cost=1):"), ("        if self.tokens >= 1:\n            self.tokens -= 1\n            return True", "        if self.tokens >= cost:\n            self.tokens -= cost\n            return True"))},
 done={"ratelimit/bucket.py": ed(B, ("def allow(self):", "def allow(self, cost=1):"), ("        if self.tokens >= 1:\n            self.tokens -= 1\n            return True", "        if cost <= self.capacity and self.tokens >= cost:\n            self.tokens -= cost\n            return True")),
       "tests/test_bucket.py": T + "\n\ndef test_cost_and_denied_keeps_tokens():\n    c = Fake()\n    b = TokenBucket(rate=1, capacity=3, clock=c)\n    assert not b.allow(cost=4)\n    assert b.allow(cost=2)\n    assert not b.allow(cost=2)\n    assert b.allow(cost=1)\n"}),
])

# supplementary partial-state files (tests/docs the near-miss did write)
_P = {r["id"]: r["partial"] for r in TASK["reqs"]}
_P["validate-args"]["tests/test_bucket.py"] = ed(T, ("from ratelimit.bucket", "import pytest\n\nfrom ratelimit.bucket")) + "\n\ndef test_rejects_zero_rate():\n    with pytest.raises(ValueError):\n        TokenBucket(rate=0, capacity=1)\n"
_P["retry-after"]["tests/test_bucket.py"] = T + "\n\ndef test_retry_after_when_drained():\n    c = Fake()\n    b = TokenBucket(rate=2, capacity=1, clock=c)\n    assert b.allow()\n    assert b.retry_after() == 0.5\n"
