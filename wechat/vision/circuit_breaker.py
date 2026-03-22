"""Circuit breaker for API resilience."""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Circuit breaker: open after N consecutive failures, half-open after cooldown."""

    def __init__(self, fail_threshold: int = 5, cooldown: float = 300.0) -> None:
        self._fail_threshold = fail_threshold
        self._cooldown = cooldown
        self._fail_count = 0
        self._open_since: float = 0.0

    @property
    def is_open(self) -> bool:
        if self._fail_count < self._fail_threshold:
            return False
        # Past cooldown → half-open (allow one attempt)
        if time.time() - self._open_since >= self._cooldown:
            return False
        return True

    @property
    def fail_count(self) -> int:
        return self._fail_count

    def record_success(self) -> None:
        self._fail_count = 0

    def record_failure(self) -> None:
        self._fail_count += 1
        if self._fail_count >= self._fail_threshold:
            self._open_since = time.time()
            logger.warning(
                "Circuit breaker OPEN after %d failures (cooldown %.0fs)",
                self._fail_count, self._cooldown,
            )
