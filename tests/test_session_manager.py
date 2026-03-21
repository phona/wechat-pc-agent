"""Tests for wechat.session_manager — session lifecycle state machine."""

import time
from unittest.mock import MagicMock, patch

import pytest

from wechat.session_manager import (
    SessionLifecycle,
    STATE_ACTIVE,
    STATE_BREAK,
    STATE_INACTIVE,
    WARMUP_DURATION,
)


@pytest.fixture
def timing():
    """Mock HumanTiming that always reports active hours."""
    m = MagicMock()
    m.is_active_hour.return_value = True
    return m


@pytest.fixture
def timing_inactive():
    """Mock HumanTiming that reports inactive hours."""
    m = MagicMock()
    m.is_active_hour.return_value = False
    return m


class TestSessionLifecycle:
    def test_starts_active(self, timing):
        lc = SessionLifecycle(human_timing=timing)
        assert lc.get_state() == STATE_ACTIVE
        assert lc.should_process() is True

    def test_active_to_break_transition(self, timing):
        """After session duration elapses, should transition to break."""
        lc = SessionLifecycle(
            human_timing=timing,
            session_min_minutes=1,
            session_max_minutes=1,  # exactly 1 min
        )
        # Force session to have started 2 minutes ago
        lc._session_start = time.time() - 120
        lc._session_duration = 60  # 1 minute

        assert lc.should_process() is False
        assert lc.get_state() == STATE_BREAK

    def test_break_to_active_transition(self, timing):
        """After break ends, should return to active."""
        lc = SessionLifecycle(human_timing=timing)
        # Force into break state that ended 1 second ago
        lc._state = STATE_BREAK
        lc._break_end = time.time() - 1

        assert lc.should_process() is True
        assert lc.get_state() == STATE_ACTIVE

    def test_inactive_during_off_hours(self, timing_inactive):
        lc = SessionLifecycle(human_timing=timing_inactive)
        assert lc.should_process() is False
        assert lc.get_state() == STATE_INACTIVE

    def test_inactive_to_active_when_hours_resume(self):
        timing = MagicMock()
        timing.is_active_hour.return_value = False
        lc = SessionLifecycle(human_timing=timing)
        assert lc.get_state() == STATE_INACTIVE

        # Hours become active
        timing.is_active_hour.return_value = True
        assert lc.should_process() is True
        assert lc.get_state() == STATE_ACTIVE

    def test_time_until_active_when_active(self, timing):
        lc = SessionLifecycle(human_timing=timing)
        assert lc.time_until_active() == 0.0

    def test_time_until_active_during_break(self, timing):
        lc = SessionLifecycle(human_timing=timing)
        lc._state = STATE_BREAK
        lc._break_end = time.time() + 30.0
        remaining = lc.time_until_active()
        assert 25.0 < remaining <= 30.0

    def test_time_until_active_during_inactive(self, timing_inactive):
        lc = SessionLifecycle(human_timing=timing_inactive)
        lc._update_state()
        remaining = lc.time_until_active()
        assert remaining == 60.0  # default re-check interval

    def test_record_send_updates_time(self, timing):
        lc = SessionLifecycle(human_timing=timing)
        before = lc._last_send_time
        lc.record_send()
        assert lc._last_send_time > before

    def test_should_idle_respects_interval(self, timing):
        """should_idle should not fire more often than IDLE_CHECK_INTERVAL."""
        lc = SessionLifecycle(human_timing=timing)
        # Force past warm-up
        lc._session_start = time.time() - 300
        lc._last_idle_check = time.time()  # just checked

        # Should return False because we just checked
        assert lc.should_idle() is False

    def test_should_idle_during_warmup_high_prob(self, timing):
        """During warm-up phase, idle probability should be high."""
        lc = SessionLifecycle(human_timing=timing)
        lc._session_start = time.time()  # just started
        lc._last_idle_check = 0  # force check

        # With high warmup prob (0.8), most calls should return True
        import random
        random.seed(42)
        results = []
        for _ in range(20):
            lc._last_idle_check = 0  # force check each time
            results.append(lc.should_idle())
        assert sum(results) > 10  # should be roughly 80%

    def test_should_idle_false_when_inactive(self, timing_inactive):
        lc = SessionLifecycle(human_timing=timing_inactive)
        lc._last_idle_check = 0
        assert lc.should_idle() is False

    def test_no_human_timing_always_active(self):
        """Without human_timing, active hours check is skipped."""
        lc = SessionLifecycle(human_timing=None)
        assert lc.should_process() is True

    def test_new_session_gets_random_duration(self, timing):
        lc = SessionLifecycle(
            human_timing=timing,
            session_min_minutes=20,
            session_max_minutes=90,
        )
        assert 20 * 60 <= lc._session_duration <= 90 * 60
