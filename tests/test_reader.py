import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from wechat.session import WeChatSession
from wechat.reader import MessageReader


class FakeMsg:
    """Simulates a wxauto message object."""
    def __init__(self, sender="", content="", msg_type=None, time_str=""):
        self.sender = sender
        self.content = content
        self.type = msg_type
        self.time = time_str


@pytest.fixture
def session():
    s = WeChatSession()
    s._wx = MagicMock()
    return s


@pytest.fixture
def reader(session):
    return MessageReader(session, scroll_delay_ms=10)


# --- poll_new_messages ---

def test_poll_returns_new_messages(reader, session):
    session._wx.GetAllMessage.return_value = [
        FakeMsg(sender="Alice", content="Hello", time_str="12:00"),
        FakeMsg(sender="Bob", content="World", time_str="12:01"),
    ]
    result = reader.poll_new_messages(["GroupA"])
    assert len(result) == 2
    assert result[0]["sender"] == "Alice"
    assert result[0]["content"] == "Hello"
    assert result[0]["chat_name"] == "GroupA"
    assert result[1]["sender"] == "Bob"


def test_poll_deduplicates(reader, session):
    session._wx.GetAllMessage.return_value = [
        FakeMsg(sender="Alice", content="Hello", time_str="12:00"),
    ]
    result1 = reader.poll_new_messages(["GroupA"])
    result2 = reader.poll_new_messages(["GroupA"])
    assert len(result1) == 1
    assert len(result2) == 0  # duplicate


def test_poll_multiple_chats(reader, session):
    session._wx.GetAllMessage.side_effect = [
        [FakeMsg(sender="A", content="msg1", time_str="1")],
        [FakeMsg(sender="B", content="msg2", time_str="2")],
    ]
    result = reader.poll_new_messages(["Chat1", "Chat2"])
    assert len(result) == 2
    assert result[0]["chat_name"] == "Chat1"
    assert result[1]["chat_name"] == "Chat2"


def test_poll_empty_chat(reader, session):
    session._wx.GetAllMessage.return_value = []
    result = reader.poll_new_messages(["Empty"])
    assert result == []


def test_poll_handles_error(reader, session):
    session._wx.ChatWith.side_effect = Exception("fail")
    result = reader.poll_new_messages(["Bad"])
    assert result == []


# --- _detect_type ---

def test_detect_type_text(reader):
    msg = FakeMsg(msg_type=None)
    assert reader._detect_type(msg) == "text"


def test_detect_type_image(reader):
    msg = FakeMsg(msg_type="image")
    assert reader._detect_type(msg) == "image"


def test_detect_type_picture(reader):
    msg = FakeMsg(msg_type="Picture")
    assert reader._detect_type(msg) == "image"


def test_detect_type_voice(reader):
    msg = FakeMsg(msg_type="voice")
    assert reader._detect_type(msg) == "voice"


def test_detect_type_audio(reader):
    msg = FakeMsg(msg_type="Audio")
    assert reader._detect_type(msg) == "voice"


def test_detect_type_video(reader):
    msg = FakeMsg(msg_type="video")
    assert reader._detect_type(msg) == "video"


def test_detect_type_file(reader):
    msg = FakeMsg(msg_type="file")
    assert reader._detect_type(msg) == "file"


# --- collect_history ---

def test_collect_history_basic(reader, session):
    """History collection should read messages, scroll, and stop after empty scrolls."""
    call_count = [0]

    def get_messages(chat_name=None):
        call_count[0] += 1
        if call_count[0] <= 2:
            return [FakeMsg(sender="X", content=f"msg-{call_count[0]}", time_str=str(call_count[0]))]
        return []  # Empty after 2 rounds

    session.get_chat_messages = get_messages
    session._wx.ChatWith = MagicMock()
    session.scroll_up = MagicMock()

    with patch("wechat.reader.time.sleep"):
        total = reader.collect_history("TestChat", max_days=30)

    assert total == 2


def test_collect_history_stops_on_callback(reader, session):
    """History collection should stop when should_stop returns True."""
    session.get_chat_messages = lambda chat_name=None: [
        FakeMsg(sender="X", content="msg", time_str="1")
    ]
    session._wx.ChatWith = MagicMock()
    session.scroll_up = MagicMock()

    stop_after = [0]

    def should_stop():
        stop_after[0] += 1
        return stop_after[0] > 1

    with patch("wechat.reader.time.sleep"):
        total = reader.collect_history("Chat", should_stop=should_stop)

    # Should have collected only 1 round before stopping
    assert total >= 1


def test_collect_history_calls_progress(reader, session):
    """Progress callback should be called with count and chat name."""
    call_count = [0]

    def get_messages(chat_name=None):
        call_count[0] += 1
        if call_count[0] == 1:
            return [FakeMsg(sender="X", content="msg", time_str="1")]
        return []

    session.get_chat_messages = get_messages
    session._wx.ChatWith = MagicMock()
    session.scroll_up = MagicMock()

    progress_calls = []

    with patch("wechat.reader.time.sleep"):
        reader.collect_history(
            "Chat",
            progress_callback=lambda count, name: progress_calls.append((count, name)),
        )

    assert len(progress_calls) > 0
    assert progress_calls[0] == (1, "Chat")


def test_collect_history_error_sets_status(reader, session):
    """If ChatWith raises, collect_history should return 0."""
    session._wx.ChatWith.side_effect = Exception("window not found")

    with patch("wechat.reader.time.sleep"):
        total = reader.collect_history("BadChat")

    assert total == 0
