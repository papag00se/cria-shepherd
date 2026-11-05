import time


class TokenBucket:
    def __init__(self, rate, capacity, clock=time.monotonic):
        if rate <= 0:
            raise ValueError('rate must be positive')
        if capacity < 1:
            raise ValueError('capacity must be at least 1')
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
