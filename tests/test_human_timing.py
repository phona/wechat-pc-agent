"""Tests for HumanTiming module."""

import json
from unittest.mock import patch, MagicMock

import pytest

from wechat.simulation.human_timing import HumanTiming


def test_sample_reply_delay_range():
    ht = HumanTiming()
    # No profile — uses defaults
    delays = [ht.sample_reply_delay() for _ in range(200)]
    assert all(1.0 <= d <= 300.0 for d in delays)
    # Should have some variance
    assert max(delays) > min(delays) + 0.5


def test_sample_reply_delay_longer_for_longer_message():
    ht = HumanTiming()
    short_delays = [ht.sample_reply_delay(msg_length=5) for _ in range(100)]
    long_delays = [ht.sample_reply_delay(msg_length=200) for _ in range(100)]
    avg_short = sum(short_delays) / len(short_delays)
    avg_long = sum(long_delays) / len(long_delays)
    assert avg_long > avg_short


def test_sample_typing_delay_proportional():
    ht = HumanTiming()
    short = ht.sample_typing_delay("Hi")
    long = ht.sample_typing_delay("This is a much longer message with lots of text")
    assert long > short


def test_is_active_hour_no_profile():
    ht = HumanTiming()
    # No profile loaded — should always return True
    assert ht.is_active_hour() is True


def test_is_active_hour_with_profile():
    ht = HumanTiming()
    hours = [0.0] * 24
    hours[10] = 0.2  # active at 10am
    hours[3] = 0.0   # inactive at 3am
    ht._profile = {"active_hours": hours}

    with patch("wechat.simulation.human_timing.datetime") as mock_dt:
        mock_dt.now.return_value = MagicMock(hour=10)
        assert ht.is_active_hour() is True

        mock_dt.now.return_value = MagicMock(hour=3)
        assert ht.is_active_hour() is False


def test_profile_save_load(tmp_path):
    profile_path = str(tmp_path / "profile.json")
    ht = HumanTiming(profile_path=profile_path)
    ht._profile = {
        "reply_delay_mu": 2.0,
        "reply_delay_sigma": 0.5,
        "typing_speed": 4.0,
        "active_hours": [0.04] * 24,
        "sample_count": 100,
    }
    ht.save()

    ht2 = HumanTiming()
    assert ht2.load(profile_path) is True
    assert ht2._profile["reply_delay_mu"] == 2.0
    assert ht2._profile["typing_speed"] == 4.0


def test_load_missing_file():
    ht = HumanTiming()
    assert ht.load("/nonexistent/path.json") is False
