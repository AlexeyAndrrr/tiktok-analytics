import asyncio
import time
import random


class RateLimiter:
    """Token-bucket rate limiter with exponential backoff for 429 responses."""

    def __init__(self, requests_per_second: float = 1.0, daily_limit: int = 500):
        self.min_interval = 1.0 / requests_per_second
        self.daily_limit = daily_limit
        self._last_request = 0.0
        self._daily_count = 0
        self._day_start = time.time()

    async def acquire(self):
        """Wait until a request can be made."""
        now = time.time()

        # Reset daily counter if new day
        if now - self._day_start > 86400:
            self._daily_count = 0
            self._day_start = now

        if self._daily_count >= self.daily_limit:
            raise RuntimeError(f"Daily API limit reached ({self.daily_limit} requests)")

        # Enforce minimum interval
        elapsed = now - self._last_request
        if elapsed < self.min_interval:
            await asyncio.sleep(self.min_interval - elapsed)

        self._last_request = time.time()
        self._daily_count += 1

    async def backoff(self, attempt: int):
        """Exponential backoff with jitter."""
        delay = min(2 ** attempt + random.uniform(0, 1), 60)
        await asyncio.sleep(delay)
