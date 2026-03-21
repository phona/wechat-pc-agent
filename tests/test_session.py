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
    s.last_connect_error = "old error"
    with patch("wechat.session.sys.platform", "win32"):
        with patch.object(s, "_probe_admin_status"), patch.object(s, "_probe_wechat_process"):
            with patch.dict("sys.modules", {"wxauto4": MagicMock(WeChat=MagicMock(return_value=mock_wx))}):
                assert s.connect() is True
                assert s._wx is mock_wx
                assert s.last_connect_error == ""
                assert "WeChat() attached successfully" in s.last_connect_diagnostics


def test_connect_failure():
    s = WeChatSession()
    with patch("wechat.session.sys.platform", "win32"):
        with patch.object(s, "_probe_admin_status"), patch.object(
            s, "_probe_wechat_process", side_effect=lambda: setattr(s, "_last_process_probe", False)
        ):
            with patch.dict("sys.modules", {"wxauto4": MagicMock(WeChat=MagicMock(side_effect=Exception("no window")))}):
                assert s.connect() is False
                assert s._wx is None
                assert s.last_connect_error == "no window"
                assert "WeChat() raised Exception: no window" in s.last_connect_diagnostics
                assert any("Start desktop WeChat" in line for line in s.last_connect_diagnostics)


def test_connect_import_failure():
    s = WeChatSession()
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name in ("wxauto4", "wxauto"):
            raise ImportError("missing wxauto")
        return real_import(name, *args, **kwargs)

    with patch("wechat.session.sys.platform", "win32"):
        with patch.object(s, "_probe_admin_status"), patch.object(s, "_probe_wechat_process"):
            with patch("builtins.__import__", side_effect=fake_import):
                assert s.connect() is False
                assert s._wx is None
                assert s.last_connect_error == "wxauto import failed: missing wxauto"
                assert any("wxauto4" in line or "wxauto" in line for line in s.last_connect_diagnostics)


def test_connect_import_failure_missing_pil_hint():
    s = WeChatSession()
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name in ("wxauto4", "wxauto"):
            raise ImportError("No module named 'PIL'")
        return real_import(name, *args, **kwargs)

    with patch("wechat.session.sys.platform", "win32"):
        with patch.object(s, "_probe_admin_status"), patch.object(s, "_probe_wechat_process"):
            with patch("builtins.__import__", side_effect=fake_import):
                assert s.connect() is False
                assert s.last_connect_error == "wxauto import failed: No module named 'PIL'"
                assert any("missing Pillow/PIL" in line for line in s.last_connect_diagnostics)


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


# --- send_text_human ---

def _make_pyautogui_mock():
    mock = MagicMock()
    mock.position.return_value = (100, 100)
    return mock


def _make_pyperclip_mock():
    return MagicMock()


def test_send_text_human_success(session):
    pyautogui_mock = _make_pyautogui_mock()
    pyperclip_mock = _make_pyperclip_mock()
    # Mock _get_input_box_position to avoid win32gui dependency
    with patch.dict("sys.modules", {"pyautogui": pyautogui_mock, "pyperclip": pyperclip_mock}):
        with patch.object(session, "_get_input_box_position", return_value=(500, 700)):
            result = session.send_text_human("GroupA", "hello world")
    assert result is True
    session._wx.ChatWith.assert_called_once_with("GroupA")
    pyautogui_mock.press.assert_called()  # Enter key at minimum


def test_send_text_human_chinese_uses_clipboard(session):
    pyautogui_mock = _make_pyautogui_mock()
    pyperclip_mock = _make_pyperclip_mock()
    with patch.dict("sys.modules", {"pyautogui": pyautogui_mock, "pyperclip": pyperclip_mock}):
        with patch.object(session, "_get_input_box_position", return_value=(500, 700)):
            result = session.send_text_human("GroupA", "你好世界")
    assert result is True
    pyperclip_mock.copy.assert_called_once_with("你好世界")
    pyautogui_mock.hotkey.assert_called_with("ctrl", "v")


def test_send_text_human_ascii_types_chars(session):
    pyautogui_mock = _make_pyautogui_mock()
    pyperclip_mock = _make_pyperclip_mock()
    with patch.dict("sys.modules", {"pyautogui": pyautogui_mock, "pyperclip": pyperclip_mock}):
        with patch.object(session, "_get_input_box_position", return_value=(500, 700)):
            with patch("wechat.session.time"):  # speed up by mocking sleep
                result = session.send_text_human("GroupA", "abc")
    assert result is True
    # Should have typed individual characters via write()
    write_calls = [c for c in pyautogui_mock.write.call_args_list]
    assert len(write_calls) >= 3  # at least a, b, c


def test_send_text_human_falls_back_on_error(session):
    pyautogui_mock = _make_pyautogui_mock()
    pyperclip_mock = _make_pyperclip_mock()
    session._wx.ChatWith.side_effect = Exception("window gone")
    session._wx.SendMsg.side_effect = Exception("window gone")
    with patch.dict("sys.modules", {"pyautogui": pyautogui_mock, "pyperclip": pyperclip_mock}):
        with patch.object(session, "_get_input_box_position", return_value=(500, 700)):
            result = session.send_text_human("GroupA", "test")
    # Falls back to send_text, which also fails because SendMsg raises
    assert result is False


def test_send_text_human_falls_back_without_pyautogui(session):
    """When pyautogui is not available, falls back to send_text."""
    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "pyautogui":
            raise ImportError("no pyautogui")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        result = session.send_text_human("GroupA", "test")
    assert result is True
    session._wx.SendMsg.assert_called_once_with("test", "GroupA")


def test_bezier_move_produces_multiple_moves(session):
    pyautogui_mock = _make_pyautogui_mock()
    with patch("wechat.session.time"):
        session._bezier_move_click(500, 500, pyautogui_mock)
    # Should have called moveTo many times (curved path)
    assert pyautogui_mock.moveTo.call_count >= 10
    # Should end with a click
    pyautogui_mock.click.assert_called_once_with(500, 500)


