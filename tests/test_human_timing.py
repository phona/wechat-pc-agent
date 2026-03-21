"""Tests for HumanTiming module."""

import json
import sqlite3
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

from wechat.db_reader import DBReader
from wechat.human_timing import HumanTiming


@pytest.fixture
def db_path(tmp_path):
    """Create a test MSG database with realistic conversation patterns."""
    path = str(tmp_path / "MSG_ALL.db")
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE MSG (
            localId INTEGER PRIMARY KEY,
            MsgSvrID INT,
            Type INT,
            IsSender INT,
            CreateTime INT,
            StrTalker TEXT,
            StrContent TEXT
        )
    """)
    import time as _time
    t = int(_time.time()) - 86400  # yesterday
    rows = [
        # Conversation with alice: incoming then reply with various delays
        (1, 101, 1, 0, t, "alice", "Hey"),
        (2, 102, 1, 1, t + 5, "alice", "Hi there"),         # 5s delay
        (3, 103, 1, 0, t + 100, "alice", "How are you?"),
        (4, 104, 1, 1, t + 108, "alice", "Good thanks!"),    # 8s delay
        (5, 105, 1, 0, t + 200, "alice", "What's up?"),
        (6, 106, 1, 1, t + 215, "alice", "Not much, just working on stuff"),  # 15s delay
        # Conversation with bob
        (7, 107, 1, 0, t + 300, "bob", "Hello"),
        (8, 108, 1, 1, t + 310, "bob", "Hey bob"),           # 10s delay
        (9, 109, 1, 0, t + 400, "bob", "Quick question"),
        (10, 110, 1, 1, t + 403, "bob", "Sure"),             # 3s delay
    ]
    conn.executemany(
        "INSERT INTO MSG (localId, MsgSvrID, Type, IsSender, CreateTime, StrTalker, StrContent) "
        "VALUES (?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    return path


def test_learn_from_db(db_path):
    reader = DBReader(db_path)
    ht = HumanTiming()
    ht.learn(reader, months=6)
    assert ht._profile["sample_count"] == 5
    assert "reply_delay_mu" in ht._profile
    assert "reply_delay_sigma" in ht._profile
    assert ht._profile["typing_speed"] > 0


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

    with patch("wechat.human_timing.datetime") as mock_dt:
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


def test_learn_empty_db(tmp_path):
    path = str(tmp_path / "empty.db")
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE MSG (
            localId INTEGER PRIMARY KEY, MsgSvrID INT, Type INT,
            IsSender INT, CreateTime INT, StrTalker TEXT, StrContent TEXT
        )
    """)
    conn.commit()
    conn.close()

    reader = DBReader(path)
    ht = HumanTiming()
    ht.learn(reader, months=6)
    # Should not crash, uses defaults
    assert ht._profile == {}
