import pytest
from unittest.mock import MagicMock, patch

from wechat.session import WeChatSession


@pytest.fixture
def session():
    """Create a WeChatSession with a mocked wxauto instance injected."""
    s = WeChatSession()
    s._wx = MagicMock()
    return s


def test_connect_success():
    s = WeChatSession()
    mock_wx = MagicMock()
    with patch.dict("sys.modules", {"wxauto": MagicMock(WeChat=MagicMock(return_value=mock_wx))}):
        assert s.connect() is True
        assert s._wx is mock_wx


def test_connect_failure():
    s = WeChatSession()
    with patch.dict("sys.modules", {"wxauto": MagicMock(WeChat=MagicMock(side_effect=Exception("no window")))}):
        assert s.connect() is False
        assert s._wx is None


def test_wx_property_raises_when_not_connected():
    s = WeChatSession()
    with pytest.raises(RuntimeError, match="not connected"):
        _ = s.wx


def test_wx_property_returns_instance(session):
    assert session.wx is session._wx


def test_is_ready_true(session):
    session._wx.GetSessionList.return_value = ["chat1"]
    assert session.is_ready() is True


def test_is_ready_false_when_none():
    s = WeChatSession()
    assert s.is_ready() is False


def test_is_ready_false_on_exception(session):
    session._wx.GetSessionList.side_effect = Exception("window gone")
    assert session.is_ready() is False


def test_get_session_list(session):
    session._wx.GetSessionList.return_value = ["GroupA", "Friend1", "GroupB"]
    result = session.get_session_list()
    assert result == ["GroupA", "Friend1", "GroupB"]


def test_get_session_list_non_string(session):
    """Non-string session items should be converted to strings."""
    session._wx.GetSessionList.return_value = [MagicMock(__str__=lambda self: "obj-chat")]
    result = session.get_session_list()
    assert result == ["obj-chat"]


def test_get_session_list_error(session):
    session._wx.GetSessionList.side_effect = Exception("fail")
    assert session.get_session_list() == []


def test_get_chat_messages_with_name(session):
    mock_msg = MagicMock()
    session._wx.GetAllMessage.return_value = [mock_msg]
    result = session.get_chat_messages("GroupA")
    session._wx.ChatWith.assert_called_once_with("GroupA")
    assert result == [mock_msg]


def test_get_chat_messages_without_name(session):
    mock_msg = MagicMock()
    session._wx.GetAllMessage.return_value = [mock_msg]
    result = session.get_chat_messages()
    session._wx.ChatWith.assert_not_called()
    assert result == [mock_msg]


def test_get_chat_messages_returns_empty_on_none(session):
    session._wx.GetAllMessage.return_value = None
    assert session.get_chat_messages() == []


def test_get_chat_messages_error(session):
    session._wx.ChatWith.side_effect = Exception("fail")
    assert session.get_chat_messages("X") == []


def test_send_text_success(session):
    assert session.send_text("GroupA", "hello") is True
    session._wx.SendMsg.assert_called_once_with("hello", "GroupA")


def test_send_text_failure(session):
    session._wx.SendMsg.side_effect = Exception("fail")
    assert session.send_text("GroupA", "hello") is False


def test_send_file_success(session):
    assert session.send_file("GroupA", "/tmp/file.pdf") is True
    session._wx.SendFiles.assert_called_once_with("/tmp/file.pdf", "GroupA")


def test_send_file_failure(session):
    session._wx.SendFiles.side_effect = Exception("fail")
    assert session.send_file("GroupA", "/tmp/file.pdf") is False


def test_scroll_up(session):
    with patch.dict("sys.modules", {"pyautogui": MagicMock()}) as modules:
        session.scroll_up()
        import sys
        sys.modules["pyautogui"].scroll.assert_called_once_with(10)


# --- search_contact ---

def test_search_contact(session):
    session._wx.GetSessionList.return_value = ["Zhang San", "Li Si", "Zhang Wei"]
    with patch.dict("sys.modules", {"pyautogui": MagicMock()}):
        result = session.search_contact("Zhang")
    assert "Zhang San" in result
    assert "Zhang Wei" in result
    assert "Li Si" not in result


def test_search_contact_no_results(session):
    session._wx.GetSessionList.return_value = ["Alice", "Bob"]
    with patch.dict("sys.modules", {"pyautogui": MagicMock()}):
        result = session.search_contact("Charlie")
    assert result == []


def test_search_contact_error(session):
    session._wx.GetSessionList.side_effect = Exception("fail")
    with patch.dict("sys.modules", {"pyautogui": MagicMock()}):
        result = session.search_contact("test")
    assert result == []


# --- open_chat ---

def test_open_chat_success(session):
    assert session.open_chat("GroupA") is True
    session._wx.ChatWith.assert_called_once_with("GroupA")


def test_open_chat_failure(session):
    session._wx.ChatWith.side_effect = Exception("fail")
    assert session.open_chat("Bad") is False


# --- add_listen_chat / remove_listen_chat ---

def test_add_listen_chat(session):
    result = session.add_listen_chat("GroupA", callback=None)
    assert result is True
    session._wx.AddListenChat.assert_called_once_with(who="GroupA", savepic=True)


def test_add_listen_chat_failure(session):
    session._wx.AddListenChat.side_effect = Exception("fail")
    result = session.add_listen_chat("Bad", callback=None)
    assert result is False


def test_remove_listen_chat(session):
    session.remove_listen_chat("GroupA")
    session._wx.RemoveListenChat.assert_called_once_with(who="GroupA")


# --- get_listen_messages ---

def test_get_listen_messages(session):
    mock_msg = MagicMock()
    session._wx.GetListenMessage.return_value = {"GroupA": [mock_msg]}
    result = session.get_listen_messages()
    assert "GroupA" in result
    assert result["GroupA"] == [mock_msg]


def test_get_listen_messages_empty(session):
    session._wx.GetListenMessage.return_value = {}
    assert session.get_listen_messages() == {}


def test_get_listen_messages_error(session):
    session._wx.GetListenMessage.side_effect = Exception("fail")
    assert session.get_listen_messages() == {}
