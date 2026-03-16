"""
Tests for QThread workers.

These tests mock PyQt6 signals and wxauto to run without a display server.
Worker.run() is called directly (not via start()) to avoid needing a QApplication.
"""
import pytest
from queue import Queue
from unittest.mock import MagicMock, patch, call


@pytest.fixture
def mock_session():
    from wechat.session import WeChatSession
    s = WeChatSession()
    s._wx = MagicMock()
    return s


# ---- SenderWorker ----

def _run_sender(worker, timeout=0.5):
    """Run SenderWorker.run() in a thread and stop it after *timeout* seconds."""
    import threading, time
    t = threading.Thread(target=worker.run, daemon=True)
    t.start()
    time.sleep(timeout)
    worker.stop()
    t.join(timeout=2)


class TestSenderWorker:
    def test_sends_text_message(self, mock_session):
        from app.workers.sender_worker import SenderWorker

        q = Queue()
        q.put({"chat_name": "GroupA", "content": "hello", "msgtype": "text"})

        mock_session.send_text = MagicMock(return_value=True)
        worker = SenderWorker(mock_session, q, max_retries=1)
        worker.message_sent = MagicMock()
        worker.error_occurred = MagicMock()

        _run_sender(worker)

        mock_session.send_text.assert_called_once_with("GroupA", "hello")
        # "started" + "Sent to ..."
        assert worker.message_sent.emit.call_count >= 2

    def test_sends_file_message(self, mock_session):
        from app.workers.sender_worker import SenderWorker

        q = Queue()
        q.put({"chat_name": "GroupA", "content": "/tmp/file.pdf", "msgtype": "file"})

        mock_session.send_file = MagicMock(return_value=True)
        worker = SenderWorker(mock_session, q, max_retries=1)
        worker.message_sent = MagicMock()
        worker.error_occurred = MagicMock()

        _run_sender(worker)

        mock_session.send_file.assert_called_once_with("GroupA", "/tmp/file.pdf")

    def test_skips_empty_content(self, mock_session):
        from app.workers.sender_worker import SenderWorker

        q = Queue()
        q.put({"chat_name": "GroupA", "content": "", "msgtype": "text"})

        mock_session.send_text = MagicMock()
        worker = SenderWorker(mock_session, q, max_retries=1)
        worker.message_sent = MagicMock()
        worker.error_occurred = MagicMock()

        _run_sender(worker)

        mock_session.send_text.assert_not_called()

    def test_retries_on_failure(self, mock_session):
        from app.workers.sender_worker import SenderWorker

        q = Queue()
        q.put({"chat_name": "GroupA", "content": "hello", "msgtype": "text"})

        # Fail twice then succeed
        mock_session.send_text = MagicMock(side_effect=[False, False, True])
        worker = SenderWorker(mock_session, q, max_retries=3)
        worker.message_sent = MagicMock()
        worker.error_occurred = MagicMock()

        with patch("app.workers.sender_worker.time.sleep"):
            _run_sender(worker, timeout=1.0)

        assert mock_session.send_text.call_count == 3
        # Two failure logs
        assert worker.error_occurred.emit.call_count >= 2

    def test_emits_error_after_all_retries_exhausted(self, mock_session):
        from app.workers.sender_worker import SenderWorker

        q = Queue()
        q.put({"chat_name": "GroupA", "content": "hello", "msgtype": "text"})

        mock_session.send_text = MagicMock(return_value=False)
        worker = SenderWorker(mock_session, q, max_retries=2)
        worker.message_sent = MagicMock()
        worker.error_occurred = MagicMock()

        with patch("app.workers.sender_worker.time.sleep"):
            _run_sender(worker, timeout=1.0)

        # "attempt 1/2 failed", "attempt 2/2 failed", "Failed to send after 2 retries"
        calls = [c.args[0] for c in worker.error_occurred.emit.call_args_list]
        assert any("Failed to send" in c for c in calls)

    def test_skips_missing_chat_name(self, mock_session):
        from app.workers.sender_worker import SenderWorker

        q = Queue()
        q.put({"chat_name": "", "content": "hello", "msgtype": "text"})

        mock_session.send_text = MagicMock()
        worker = SenderWorker(mock_session, q, max_retries=1)
        worker.message_sent = MagicMock()
        worker.error_occurred = MagicMock()

        _run_sender(worker)

        mock_session.send_text.assert_not_called()

    def test_stop_emits_stopped_message(self, mock_session):
        from app.workers.sender_worker import SenderWorker

        q = Queue()
        worker = SenderWorker(mock_session, q)
        worker.message_sent = MagicMock()
        worker.error_occurred = MagicMock()

        _run_sender(worker, timeout=0.3)

        calls = [c.args[0] for c in worker.message_sent.emit.call_args_list]
        assert "Sender worker started" in calls
        assert "Sender worker stopped" in calls


# ---- ListenerWorker ----

class TestListenerWorker:
    def test_forwards_listen_messages(self, mock_session):
        """ListenerWorker uses AddListenChat + GetListenMessage."""
        from app.workers.listener_worker import ListenerWorker

        mock_client = MagicMock()
        mock_client.forward_message.return_value = True

        # Setup mock listen messages
        mock_msg = MagicMock()
        mock_msg.sender = "Alice"
        mock_msg.content = "Hello"
        mock_msg.type = None
        mock_msg.time = "12:00"

        # GetListenMessage returns {chat_name: [messages]}
        mock_session._wx.GetListenMessage.return_value = {"GroupA": [mock_msg]}
        mock_session._wx.AddListenChat = MagicMock()
        mock_session._wx.RemoveListenChat = MagicMock()

        worker = ListenerWorker(mock_session, mock_client, poll_interval=0.01)
        worker.message_received = MagicMock()
        worker.error_occurred = MagicMock()
        worker.set_chats(["GroupA"])

        # Run one cycle: start, process one batch, then stop
        import threading
        def stop_after_delay():
            import time
            time.sleep(0.05)
            worker._running = False

        t = threading.Thread(target=stop_after_delay)
        t.start()
        worker.run()
        t.join()

        mock_session._wx.AddListenChat.assert_called_once()
        mock_client.forward_message.assert_called_once_with(
            sender_id="Alice",
            conversation_id="GroupA",
            msg_type="text",
            content="Hello",
        )


# ---- HistoryWorker ----

class TestHistoryWorker:
    def test_collects_history_for_chats(self, mock_session):
        from app.workers.history_worker import HistoryWorker
        from wechat.reader import MessageReader

        reader = MessageReader(mock_session, scroll_delay_ms=10)

        # Mock: return messages on first call, empty after
        call_count = [0]
        def get_messages(chat_name=None):
            call_count[0] += 1
            if call_count[0] == 1:
                mock_msg = MagicMock()
                mock_msg.sender = "X"
                mock_msg.content = "history-msg"
                mock_msg.type = None
                mock_msg.time = "10:00"
                return [mock_msg]
            return []

        mock_session.get_chat_messages = get_messages
        mock_session.scroll_up = MagicMock()

        worker = HistoryWorker(reader, MagicMock(), max_history_days=30)
        worker.progress_updated = MagicMock()
        worker.chat_completed = MagicMock()
        worker.all_completed = MagicMock()
        worker.log_message = MagicMock()
        worker.error_occurred = MagicMock()
        worker.set_chats(["TestChat"])

        with patch("wechat.reader.time.sleep"):
            worker.run()

        worker.chat_completed.emit.assert_called_once()
        worker.all_completed.emit.assert_called_once()

    def test_stop_cancels_history(self, mock_session):
        from app.workers.history_worker import HistoryWorker
        from wechat.reader import MessageReader

        reader = MessageReader(mock_session, scroll_delay_ms=10)

        # Always return messages (infinite)
        mock_msg = MagicMock()
        mock_msg.sender = "X"
        mock_msg.content = "infinite"
        mock_msg.type = None
        mock_msg.time = "1"
        mock_session.get_chat_messages = lambda chat_name=None: [mock_msg]
        mock_session.scroll_up = MagicMock()

        worker = HistoryWorker(reader, MagicMock(), max_history_days=30)
        worker.progress_updated = MagicMock()
        worker.chat_completed = MagicMock()
        worker.all_completed = MagicMock()
        worker.log_message = MagicMock()
        worker.error_occurred = MagicMock()
        worker.set_chats(["Chat1", "Chat2"])

        # Patch collect_history to stop the worker mid-run (simulating user stop)
        original_collect = reader.collect_history

        def stop_on_first_chat(**kwargs):
            worker._running = False  # stop after first chat starts
            return 0

        reader.collect_history = stop_on_first_chat

        worker.run()

        # Should process at most the first chat before stopping
        assert worker.chat_completed.emit.call_count <= 1
