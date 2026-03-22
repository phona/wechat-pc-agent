"""Tests for wechat.session — vision-based WeChat session management."""

import json
from unittest.mock import MagicMock, patch

import pytest

from wechat.session import WeChatSession
from wechat.vision import UIElement, UIState, ChatEntry


@pytest.fixture
def session():
    """Create a WeChatSession with mocked window + vision."""
    s = WeChatSession()
    window = MagicMock()
    window.is_visible.return_value = True
    window.get_rect.return_value = (0, 0, 1920, 1080)

    vision = MagicMock()
    vision.state = UIState()
    vision.state.elements = {
        "search_box": UIElement("search_box", 85, 60, 250, 30),
        "input_box": UIElement("input_box", 500, 520, 400, 60),
        "chat_list_area": UIElement("chat_list_area", 80, 100, 320, 500),
    }
    vision.state.visible_chats = [
        ChatEntry("张三", True, 2, 150),
        ChatEntry("李四", False, 0, 230),
    ]
    vision.get_element_center.side_effect = lambda name: {
        "search_box": (210, 75),
        "input_box": (700, 550),
    }.get(name)

    s.set_vision(window, vision)
    s._connected = True
    return s


def test_connect_success():
    s = WeChatSession()
    window = MagicMock()
    window.find.return_value = True
    window.activate.return_value = True
    window.maximize.return_value = True

    vision = MagicMock()
    vision.calibrate.return_value = UIState()

    s.set_vision(window, vision)
    assert s.connect() is True
    assert s._connected is True
    window.find.assert_called_once()
    window.activate.assert_called_once()
    vision.calibrate.assert_called_once()


def test_connect_no_window():
    s = WeChatSession()
    window = MagicMock()
    window.find.return_value = False

    s.set_vision(window, None)
    assert s.connect() is False
    assert "WeChat window not found" in s.last_connect_error


def test_connect_no_window_manager():
    s = WeChatSession()
    assert s.connect() is False
    assert "Window manager not initialized" in s.last_connect_error


def test_connect_vlm_calibration_failure():
    s = WeChatSession()
    window = MagicMock()
    window.find.return_value = True
    window.activate.return_value = True

    vision = MagicMock()
    vision.calibrate.side_effect = Exception("VLM timeout")

    s.set_vision(window, vision)
    assert s.connect() is False
    assert "VLM calibration failed" in s.last_connect_error


def test_is_ready_true(session):
    assert session.is_ready() is True


def test_is_ready_false_when_not_connected():
    s = WeChatSession()
    assert s.is_ready() is False


def test_get_session_list(session):
    result = session.get_session_list()
    assert result == ["张三", "李四"]


def test_get_session_list_no_vision():
    s = WeChatSession()
    assert s.get_session_list() == []


def test_get_window_rect(session):
    rect = session.get_window_rect()
    assert rect == (0, 0, 1920, 1080)


def test_search_contact(session):
    result = session.search_contact("张")
    assert "张三" in result
    assert "李四" not in result


def test_search_contact_no_vision():
    s = WeChatSession()
    assert s.search_contact("test") == []


def _make_pyautogui_mock():
    mock = MagicMock()
    mock.position.return_value = (100, 100)
    return mock


def test_send_text_human_success(session):
    pyautogui_mock = _make_pyautogui_mock()
    pyperclip_mock = MagicMock()

    with patch.dict("sys.modules", {"pyautogui": pyautogui_mock, "pyperclip": pyperclip_mock}):
        with patch("wechat.session.time"):
            result = session.send_text_human("张三", "hello world")
    assert result is True
    pyautogui_mock.press.assert_called()


def test_send_text_human_chinese_uses_clipboard(session):
    pyautogui_mock = _make_pyautogui_mock()
    pyperclip_mock = MagicMock()

    with patch.dict("sys.modules", {"pyautogui": pyautogui_mock, "pyperclip": pyperclip_mock}):
        with patch("wechat.session.time"):
            result = session.send_text_human("张三", "你好世界")
    assert result is True
    pyperclip_mock.copy.assert_called_with("你好世界")


def test_send_text_human_no_vision():
    s = WeChatSession()
    result = s.send_text_human("张三", "test")
    assert result is False


def test_bezier_move_produces_multiple_moves(session):
    pyautogui_mock = _make_pyautogui_mock()
    with patch("wechat.session.time"):
        session._bezier_move_click(500, 500, pyautogui_mock)
    assert pyautogui_mock.moveTo.call_count >= 10
    pyautogui_mock.click.assert_called_once_with(500, 500)


def test_open_chat(session):
    pyautogui_mock = _make_pyautogui_mock()
    pyperclip_mock = MagicMock()

    with patch.dict("sys.modules", {"pyautogui": pyautogui_mock, "pyperclip": pyperclip_mock}):
        with patch("wechat.session.time"):
            result = session.open_chat("张三")
    assert result is True
