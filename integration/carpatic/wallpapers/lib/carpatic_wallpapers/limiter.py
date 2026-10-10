"""Token bucket: Wallhaven allows about 45 API calls a minute; we stay under it before the server has to say no."""
import threading, time

class TokenBucket:
    def __init__(self, per_minute=40, burst=8, clock=time.monotonic, sleep=time.sleep):
        self.rate = per_minute / 60.0
        self.cap = float(burst)
        self.tokens = float(burst)
        self._clock, self._sleep = clock, sleep
        self._last = clock()
        self._lock = threading.Lock()
        self.waited = 0.0

    def _refill(self):
        now = self._clock()
        self.tokens = min(self.cap, self.tokens + (now - self._last) * self.rate)
        self._last = now

    def delay(self):
        """Seconds until one token is available (0 when free now). Does not take it."""
        with self._lock:
            self._refill()
            return 0.0 if self.tokens >= 1 else (1 - self.tokens) / self.rate

    def acquire(self, max_wait=30.0):
        """Take a token, sleeping if needed. Returns False when the wait would exceed max_wait (caller shows 'busy')."""
        with self._lock:
            self._refill()
            need = 0.0 if self.tokens >= 1 else (1 - self.tokens) / self.rate
            if need > max_wait:
                return False
            self.tokens -= 1  # may go below zero: later callers queue behind us
        if need > 0:
            self.waited += need
            self._sleep(need)
        return True
