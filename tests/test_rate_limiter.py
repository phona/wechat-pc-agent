import time
from unittest.mock import patch

import pytest

from wechat.simulation.rate_limiter import RateLimiter


def test_can_send_when_empty():
    rl = RateLimiter()
    ok, reason = rl.can_send()
    assert ok is True
    assert reason == ""


def test_min_interval_enforced():
    rl = RateLimiter(min_interval=5.0)
    rl.record_send()
    ok, reason = rl.can_send()
    assert ok is False
    assert "Min interval" in reason


def test_min_interval_elapsed():
    rl = RateLimiter(min_interval=1.0)
    t0 = 1000.0
    with patch("wechat.simulation.rate_limiter.time") as mock_time:
        mock_time.time.return_value = t0
        rl.record_send()
        mock_time.time.return_value = t0 + 2.0
        ok, _ = rl.can_send()
    assert ok is True


def test_hourly_limit_blocks():
    rl = RateLimiter(hourly_pause=5, min_interval=0.0)
    t0 = 1000.0
    with patch("wechat.simulation.rate_limiter.time") as mock_time:
        for i in range(5):
            mock_time.time.return_value = t0 + i
            rl.record_send()
        mock_time.time.return_value = t0 + 10
        ok, reason = rl.can_send()
    assert ok is False
    assert "Hourly" in reason


def test_daily_limit_blocks():
    rl = RateLimiter(daily_pause=5, hourly_pause=1000, min_interval=0.0)
    t0 = 1000.0
    with patch("wechat.simulation.rate_limiter.time") as mock_time:
        for i in range(5):
            mock_time.time.return_value = t0 + i
            rl.record_send()
        mock_time.time.return_value = t0 + 10
        ok, reason = rl.can_send()
    assert ok is False
    assert "Daily" in reason


def test_rolling_window_prunes_old_entries():
    rl = RateLimiter(daily_pause=5, hourly_pause=1000, min_interval=0.0)
    t0 = 1000.0
    with patch("wechat.simulation.rate_limiter.time") as mock_time:
        # Add 4 sends at t0
        for i in range(4):
            mock_time.time.return_value = t0 + i
            rl.record_send()
        # Jump forward 25 hours — old sends should be pruned
        mock_time.time.return_value = t0 + 90000
        ok, _ = rl.can_send()
    assert ok is True


def test_cooldown_for_min_interval():
    rl = RateLimiter(min_interval=5.0)
    t0 = 1000.0
    with patch("wechat.simulation.rate_limiter.time") as mock_time:
        mock_time.time.return_value = t0
        rl.record_send()
        mock_time.time.return_value = t0 + 2.0
        cooldown = rl.get_required_cooldown()
    assert 2.5 < cooldown < 3.5


def test_cooldown_for_hourly_pause():
    rl = RateLimiter(hourly_pause=2, min_interval=0.0)
    t0 = 1000.0
    with patch("wechat.simulation.rate_limiter.time") as mock_time:
        for i in range(2):
            mock_time.time.return_value = t0 + i
            rl.record_send()
        mock_time.time.return_value = t0 + 5
        cooldown = rl.get_required_cooldown()
    # Cooldown computed from rolling window: oldest hourly entry ages out at t0+3600
    assert cooldown >= 10.0


def test_cooldown_for_daily_pause():
    rl = RateLimiter(daily_pause=2, hourly_pause=1000, min_interval=0.0)
    t0 = 1000.0
    with patch("wechat.simulation.rate_limiter.time") as mock_time:
        for i in range(2):
            mock_time.time.return_value = t0 + i
            rl.record_send()
        mock_time.time.return_value = t0 + 5
        cooldown = rl.get_required_cooldown()
    # Cooldown computed from rolling window: oldest daily entry ages out at t0+86400
    assert cooldown >= 60.0


def test_get_stats():
    rl = RateLimiter(min_interval=0.0)
    rl.record_send()
    stats = rl.get_stats()
    assert stats["hourly_count"] == 1
    assert stats["daily_count"] == 1
    assert stats["last_send"] > 0
    assert stats["can_send"] is True


def test_hourly_warn_logs(caplog):
    rl = RateLimiter(hourly_warn=2, hourly_pause=100, min_interval=0.0)
    t0 = 1000.0
    with patch("wechat.simulation.rate_limiter.time") as mock_time:
        for i in range(3):
            mock_time.time.return_value = t0 + i
            rl.record_send()
        mock_time.time.return_value = t0 + 10
        rl.can_send()
    assert "approaching limit" in caplog.text
