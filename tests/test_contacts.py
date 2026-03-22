"""Tests for wechat.contacts — contact collection via vision-based session."""

import pytest
from unittest.mock import MagicMock

from wechat.session import WeChatSession
from wechat.contacts import ContactCollector
from wechat.vision import ChatEntry, UIState


@pytest.fixture
def session():
    s = WeChatSession()
    vision = MagicMock()
    vision.state = UIState()
    vision.state.visible_chats = [
        ChatEntry("GroupA", False, 0, 100),
        ChatEntry("Friend1", True, 1, 200),
        ChatEntry("GroupB", False, 0, 300),
    ]
    s._vision = vision
    return s


@pytest.fixture
def collector(session):
    return ContactCollector(session)


def test_collect_sessions(collector, session):
    result = collector.collect_sessions()
    assert result == ["GroupA", "Friend1", "GroupB"]


def test_collect_sessions_empty(collector, session):
    session._vision.state.visible_chats = []
    result = collector.collect_sessions()
    assert result == []


def test_collect_friends(collector):
    """collect_friends now returns the same as collect_sessions (VLM-based)."""
    result = collector.collect_friends()
    assert result == ["GroupA", "Friend1", "GroupB"]


def test_collect_friends_no_vision():
    s = WeChatSession()
    collector = ContactCollector(s)
    result = collector.collect_friends()
    assert result == []


def test_collect_all(collector):
    result = collector.collect_all()
    assert result["sessions"] == ["GroupA", "Friend1", "GroupB"]
    assert result["friends"] == ["GroupA", "Friend1", "GroupB"]
