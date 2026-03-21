"""Session lifecycle manager — controls active/break/inactive state transitions."""

import logging
import random
import time

logger = logging.getLogger(__name__)

STATE_ACTIVE = "active"
STATE_BREAK = "break"
STATE_INACTIVE = "inactive"

# Warm-up phase: higher idle probability in first minutes after a break
WARMUP_DURATION = 150.0  # 2.5 minutes
WARMUP_IDLE_PROB = 0.8
NORMAL_IDLE_PROB = 0.25
IDLE_CHECK_INTERVAL = 15.0  # only consider idle action every N seconds


class SessionLifecycle:
    """State machine that simulates natural usage sessions with breaks.

    States:
        ACTIVE  — bot processes queue items and may send messages
        BREAK   — bot pauses sending, may do occasional idle actions
        INACTIVE — outside active hours, no activity at all
    """

    def __init__(
        self,
        human_timing=None,
        session_min_minutes: int = 20,
        session_max_minutes: int = 90,
        break_min_minutes: int = 5,
        break_max_minutes: int = 30,
    ):
        self._human_timing = human_timing
        self._session_min = session_min_minutes * 60.0
        self._session_max = session_max_minutes * 60.0
        self._break_min = break_min_minutes * 60.0
        self._break_max = break_max_minutes * 60.0

        self._state = STATE_ACTIVE
        self._session_start = time.time()
        self._session_duration = random.uniform(self._session_min, self._session_max)
        self._break_end = 0.0
        self._last_idle_check = 0.0
        self._last_send_time = 0.0

    def should_process(self) -> bool:
        """Check if the bot should process queue items right now."""
        self._update_state()
        return self._state == STATE_ACTIVE

    def should_idle(self) -> bool:
        """Check if an idle action should be performed (called when queue is empty)."""
        now = time.time()
        if now - self._last_idle_check < IDLE_CHECK_INTERVAL:
            return False
        self._last_idle_check = now

        self._update_state()

        if self._state == STATE_INACTIVE:
            return False

        if self._state == STATE_BREAK:
            # During breaks, very occasional idle (10%)
            return random.random() < 0.10

        # Active state: higher idle during warm-up
        elapsed = now - self._session_start
        if elapsed < WARMUP_DURATION:
            return random.random() < WARMUP_IDLE_PROB
        return random.random() < NORMAL_IDLE_PROB

    def record_send(self) -> None:
        """Record that a message was sent."""
        self._last_send_time = time.time()

    def get_state(self) -> str:
        """Return current state string for logging."""
        self._update_state()
        return self._state

    def time_until_active(self) -> float:
        """Seconds until next active period. 0 if already active."""
        self._update_state()
        now = time.time()

        if self._state == STATE_ACTIVE:
            return 0.0
        if self._state == STATE_BREAK:
            return max(0.0, self._break_end - now)
        # INACTIVE — estimate next active hour transition
        # Return a moderate sleep to re-check periodically
        return 60.0

    def _update_state(self) -> None:
        """Transition state based on time and active hours."""
        now = time.time()

        # Check active hours first
        if self._human_timing and not self._human_timing.is_active_hour():
            if self._state != STATE_INACTIVE:
                logger.info("Session lifecycle: entering inactive period (off-hours)")
            self._state = STATE_INACTIVE
            return

        # If we were inactive but now in active hours, start a new session
        if self._state == STATE_INACTIVE:
            logger.info("Session lifecycle: active hours resumed, starting new session")
            self._start_new_session(now)
            return

        # Active → Break transition
        if self._state == STATE_ACTIVE:
            if now - self._session_start >= self._session_duration:
                break_duration = random.uniform(self._break_min, self._break_max)
                self._break_end = now + break_duration
                self._state = STATE_BREAK
                logger.info(
                    "Session lifecycle: taking a break (%.0f min)",
                    break_duration / 60,
                )
            return

        # Break → Active transition
        if self._state == STATE_BREAK:
            if now >= self._break_end:
                logger.info("Session lifecycle: break over, resuming")
                self._start_new_session(now)
            return

    def _start_new_session(self, now: float) -> None:
        self._state = STATE_ACTIVE
        self._session_start = now
        self._session_duration = random.uniform(self._session_min, self._session_max)
        logger.info("Session lifecycle: new session (%.0f min)", self._session_duration / 60)
