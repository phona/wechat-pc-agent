import pytest
from unittest.mock import MagicMock, patch

from wechat.session import WeChatSession
from wechat.commander import CommandDispatcher


@pytest.fixture
def session():
    s = WeChatSession()
    s._wx = MagicMock()
    return s


@pytest.fixture
def commander(session):
    return CommandDispatcher(session)


def test_unknown_action(commander):
    result = commander.dispatch("nonexistent", {})
    assert result["status"] == "error"
    assert "unknown action" in result["error"]


def test_search_contact(commander, session):
    session._wx.GetSessionList.return_value = ["Zhang San", "Li Si", "Zhang Wei"]
    with patch("wechat.session.pyautogui", create=True):
        with patch.dict("sys.modules", {"pyautogui": MagicMock()}):
            result = commander.dispatch("search_contact", {"name": "Zhang"})
    assert result["status"] == "ok"
    assert "Zhang" in result["data"]["query"]


def test_search_contact_missing_name(commander):
    result = commander.dispatch("search_contact", {})
    assert result["status"] == "error"
    assert "missing" in result["error"]


def test_send_message(commander, session):
    result = commander.dispatch("send_message", {"to": "Alice", "content": "hi"})
    assert result["status"] == "ok"
    session._wx.SendMsg.assert_called_once_with("hi", "Alice")


def test_send_message_missing_params(commander):
    result = commander.dispatch("send_message", {"to": "Alice"})
    assert result["status"] == "error"


def test_send_file(commander, session):
    result = commander.dispatch("send_file", {"to": "Alice", "file_path": "/tmp/a.pdf"})
    assert result["status"] == "ok"
    session._wx.SendFiles.assert_called_once_with("/tmp/a.pdf", "Alice")


def test_open_chat(commander, session):
    result = commander.dispatch("open_chat", {"name": "GroupA"})
    assert result["status"] == "ok"
    session._wx.ChatWith.assert_called_once_with("GroupA")


def test_open_chat_missing_name(commander):
    result = commander.dispatch("open_chat", {})
    assert result["status"] == "error"


def test_list_contacts(commander, session):
    session._wx.GetSessionList.return_value = ["GroupA"]
    session._wx.GetAllFriends.return_value = ["Alice"]
    result = commander.dispatch("list_contacts", {})
    assert result["status"] == "ok"
    assert result["data"]["sessions"] == ["GroupA"]
    assert result["data"]["friends"] == ["Alice"]


def test_collect_history_with_callback(session):
    callback = MagicMock()
    commander = CommandDispatcher(session, history_callback=callback)
    result = commander.dispatch("collect_history", {"name": "GroupA", "days": 7})
    assert result["status"] == "ok"
    callback.assert_called_once_with("GroupA", 7)


def test_collect_history_no_callback(commander):
    result = commander.dispatch("collect_history", {"name": "GroupA"})
    assert result["status"] == "error"
    assert "not available" in result["error"]


def test_collect_history_missing_name(commander):
    result = commander.dispatch("collect_history", {})
    assert result["status"] == "error"


def test_dispatch_catches_exceptions(session):
    """When session.send_text catches the error, dispatch returns error status."""
    session._wx.SendMsg.side_effect = RuntimeError("boom")
    commander = CommandDispatcher(session)
    result = commander.dispatch("send_message", {"to": "X", "content": "Y"})
    # send_text catches the exception and returns False, so dispatch gets sent=False
    assert result["status"] == "error"
    assert result["data"]["sent"] is False
