import time


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

    def retry_after(self):
        now = self.clock()
        tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
        if tokens >= 1:
            return 0.0
        return (1 - tokens) / self.rate
