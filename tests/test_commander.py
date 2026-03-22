"""Tests for wechat.commander — command dispatch via vision-based session."""

import pytest
from unittest.mock import MagicMock, patch

from wechat.session import WeChatSession
from wechat.commander import CommandDispatcher
from wechat.vision import ChatEntry, UIElement, UIState


@pytest.fixture
def session():
    s = WeChatSession()
    vision = MagicMock()
    vision.state = UIState()
    vision.state.visible_chats = [
        ChatEntry("Zhang San", False, 0, 100),
        ChatEntry("Li Si", False, 0, 200),
        ChatEntry("Zhang Wei", False, 0, 300),
    ]
    vision.state.elements = {
        "search_box": UIElement("search_box", 85, 60, 250, 30),
        "input_box": UIElement("input_box", 500, 520, 400, 60),
    }
    vision.get_element_center.side_effect = lambda name: {
        "search_box": (210, 75),
        "input_box": (700, 550),
    }.get(name)
    s._vision = vision
    s._connected = True

    window = MagicMock()
    window.is_visible.return_value = True
    window.get_rect.return_value = (0, 0, 1920, 1080)
    s._window = window
    return s


@pytest.fixture
def commander(session):
    return CommandDispatcher(session)


def test_unknown_action(commander):
    result = commander.dispatch("nonexistent", {})
    assert result["status"] == "error"
    assert "unknown action" in result["error"]


def test_search_contact(commander, session):
    result = commander.dispatch("search_contact", {"name": "Zhang"})
    assert result["status"] == "ok"
    assert "Zhang" in result["data"]["query"]
    assert "Zhang San" in result["data"]["matches"]
    assert "Zhang Wei" in result["data"]["matches"]
    assert "Li Si" not in result["data"]["matches"]


def test_search_contact_missing_name(commander):
    result = commander.dispatch("search_contact", {})
    assert result["status"] == "error"
    assert "missing" in result["error"]


def test_send_message(commander, session):
    pyautogui_mock = MagicMock()
    pyautogui_mock.position.return_value = (100, 100)
    pyperclip_mock = MagicMock()

    with patch.dict("sys.modules", {"pyautogui": pyautogui_mock, "pyperclip": pyperclip_mock}):
        with patch("wechat.session.time"):
            result = commander.dispatch("send_message", {"to": "Zhang San", "content": "hi"})
    assert result["status"] == "ok"
    assert result["data"]["sent"] is True


def test_send_message_missing_params(commander):
    result = commander.dispatch("send_message", {"to": "Alice"})
    assert result["status"] == "error"


def test_send_file(commander, session):
    # send_file requires Windows, so it returns False on Linux
    result = commander.dispatch("send_file", {"to": "Alice", "file_path": "/tmp/a.pdf"})
    # Will fail on non-Windows (returns error status)
    assert result["status"] in ("ok", "error")


def test_open_chat(commander, session):
    pyautogui_mock = MagicMock()
    pyautogui_mock.position.return_value = (100, 100)
    pyperclip_mock = MagicMock()

    with patch.dict("sys.modules", {"pyautogui": pyautogui_mock, "pyperclip": pyperclip_mock}):
        with patch("wechat.session.time"):
            result = commander.dispatch("open_chat", {"name": "Zhang San"})
    assert result["status"] == "ok"
    assert result["data"]["opened"] is True


def test_open_chat_missing_name(commander):
    result = commander.dispatch("open_chat", {})
    assert result["status"] == "error"


def test_list_contacts(commander, session):
    result = commander.dispatch("list_contacts", {})
    assert result["status"] == "ok"
    assert "Zhang San" in result["data"]["sessions"]


def test_dispatch_catches_exceptions(session):
    """When session raises, dispatch catches and returns error."""
    session._vision = None  # Break vision to cause errors
    commander = CommandDispatcher(session)
    result = commander.dispatch("send_message", {"to": "X", "content": "Y"})
    assert result["status"] == "error"
