"""Rate limiter for WeChat message sending — rolling window with hourly/daily caps."""

import logging
import threading
import time
from collections import deque

logger = logging.getLogger(__name__)


class RateLimiter:
    """Enforce hourly/daily send rate caps with a rolling window."""

    def __init__(
        self,
        hourly_warn: int = 80,
        hourly_pause: int = 120,
        daily_warn: int = 200,
        daily_pause: int = 300,
        min_interval: float = 3.0,
    ):
        self.hourly_warn = hourly_warn
        self.hourly_pause = hourly_pause
        self.daily_warn = daily_warn
        self.daily_pause = daily_pause
        self.min_interval = min_interval

        self._sends: deque[float] = deque()
        self._last_send: float = 0.0
        self._lock = threading.Lock()

    def can_send(self) -> tuple[bool, str]:
        """Check whether sending is allowed. Returns (allowed, reason)."""
        with self._lock:
            allowed, reason, _ = self._check()
            return allowed, reason

    def record_send(self) -> None:
        """Record a successful send."""
        with self._lock:
            now = time.time()
            self._sends.append(now)
            self._last_send = now
            self._prune(now)

    def get_required_cooldown(self) -> float:
        """Seconds to wait before the next send is allowed."""
        with self._lock:
            _, _, cooldown = self._check()
            return cooldown

    def get_stats(self) -> dict:
        """Return current rate stats for UI display."""
        with self._lock:
            now = time.time()
            self._prune(now)
            hourly = self._hourly_count(now)
            daily = len(self._sends)
            allowed, _, _ = self._check_unlocked(now, hourly, daily)
            return {
                "hourly_count": hourly,
                "daily_count": daily,
                "last_send": self._last_send,
                "can_send": allowed,
            }

    def _check(self) -> tuple[bool, str, float]:
        """Core check logic. Caller must hold _lock. Returns (allowed, reason, cooldown)."""
        now = time.time()
        self._prune(now)
        hourly = self._hourly_count(now)
        daily = len(self._sends)
        return self._check_unlocked(now, hourly, daily)

    def _check_unlocked(self, now: float, hourly: int, daily: int) -> tuple[bool, str, float]:
        """Pure logic — no lock, no IO."""
        if daily >= self.daily_pause:
            # Cooldown: time until oldest entry ages out of the 24h window
            oldest_daily = self._sends[0] if self._sends else now
            cooldown = max(60.0, 86400 - (now - oldest_daily))
            return False, f"Daily limit reached ({self.daily_pause})", cooldown

        if hourly >= self.hourly_pause:
            # Cooldown: time until oldest hourly entry ages out
            cutoff = now - 3600
            oldest_hourly = next((t for t in self._sends if t >= cutoff), now)
            cooldown = max(10.0, 3600 - (now - oldest_hourly))
            return False, f"Hourly limit reached ({self.hourly_pause})", cooldown

        if self._last_send:
            remaining = self.min_interval - (now - self._last_send)
            if remaining > 0:
                return False, "Min interval not elapsed", remaining

        if daily >= self.daily_warn:
            logger.warning("Daily send count %d approaching limit %d", daily, self.daily_pause)
        if hourly >= self.hourly_warn:
            logger.warning("Hourly send count %d approaching limit %d", hourly, self.hourly_pause)

        return True, "", 0.0

    def _prune(self, now: float) -> None:
        """Remove entries older than 24 hours."""
        cutoff = now - 86400
        while self._sends and self._sends[0] < cutoff:
            self._sends.popleft()

    def _hourly_count(self, now: float) -> int:
        cutoff = now - 3600
        return sum(1 for t in self._sends if t >= cutoff)
