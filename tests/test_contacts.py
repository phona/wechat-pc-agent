import pytest
from unittest.mock import MagicMock

from wechat.session import WeChatSession
from wechat.contacts import ContactCollector


@pytest.fixture
def session():
    s = WeChatSession()
    s._wx = MagicMock()
    return s


@pytest.fixture
def collector(session):
    return ContactCollector(session)


def test_collect_sessions(collector, session):
    session._wx.GetSessionList.return_value = ["GroupA", "Friend1", "GroupB"]
    result = collector.collect_sessions()
    assert result == ["GroupA", "Friend1", "GroupB"]


def test_collect_sessions_empty(collector, session):
    session._wx.GetSessionList.return_value = []
    result = collector.collect_sessions()
    assert result == []


def test_collect_friends(collector, session):
    session._wx.GetAllFriends.return_value = ["Alice", "Bob"]
    result = collector.collect_friends()
    assert result == ["Alice", "Bob"]


def test_collect_friends_with_objects(collector, session):
    """Friend objects with .name attribute should be handled."""
    friend = MagicMock()
    friend.name = "Charlie"
    friend.__str__ = lambda self: "Charlie"
    session._wx.GetAllFriends.return_value = [friend]
    result = collector.collect_friends()
    assert result == ["Charlie"]


def test_collect_friends_none(collector, session):
    session._wx.GetAllFriends.return_value = None
    result = collector.collect_friends()
    assert result == []


def test_collect_friends_error(collector, session):
    session._wx.GetAllFriends.side_effect = Exception("fail")
    result = collector.collect_friends()
    assert result == []


def test_collect_all(collector, session):
    session._wx.GetSessionList.return_value = ["GroupA"]
    session._wx.GetAllFriends.return_value = ["Alice"]
    result = collector.collect_all()
    assert result["sessions"] == ["GroupA"]
    assert result["friends"] == ["Alice"]
