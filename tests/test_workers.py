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
        worker.rate_limited = MagicMock()
        worker.humanized_delay = MagicMock()

        _run_sender(worker, timeout=0.3)

        calls = [c.args[0] for c in worker.message_sent.emit.call_args_list]
        assert "Sender worker started" in calls
        assert "Sender worker stopped" in calls


class TestSenderWorkerHumanized:
    def test_human_send_uses_send_text_human(self, mock_session):
        from app.workers.sender_worker import SenderWorker

        q = Queue()
        q.put({"chat_name": "GroupA", "content": "hello", "msgtype": "text"})

        mock_session.send_text_human = MagicMock(return_value=True)
        mock_session.send_text = MagicMock(return_value=True)
        worker = SenderWorker(
            mock_session, q, max_retries=1,
            human_simulation_enabled=True,
        )
        worker.message_sent = MagicMock()
        worker.error_occurred = MagicMock()
        worker.rate_limited = MagicMock()
        worker.humanized_delay = MagicMock()

        _run_sender(worker)

        mock_session.send_text_human.assert_called_once_with("GroupA", "hello")
        mock_session.send_text.assert_not_called()

    def test_rate_limiter_blocks_send(self, mock_session):
        from app.workers.sender_worker import SenderWorker

        q = Queue()
        q.put({"chat_name": "GroupA", "content": "hello", "msgtype": "text"})

        rate_limiter = MagicMock()
        # Block on first call, allow on second
        rate_limiter.can_send.side_effect = [
            (False, "Daily limit reached"),
            (True, ""),
        ]
        rate_limiter.get_required_cooldown.return_value = 0.1

        mock_session.send_text = MagicMock(return_value=True)
        worker = SenderWorker(
            mock_session, q, max_retries=1,
            rate_limiter=rate_limiter,
        )
        worker.message_sent = MagicMock()
        worker.error_occurred = MagicMock()
        worker.rate_limited = MagicMock()
        worker.humanized_delay = MagicMock()

        with patch("app.workers.sender_worker.time.sleep"):
            _run_sender(worker, timeout=0.5)

        worker.rate_limited.emit.assert_called()
        assert "Daily limit" in worker.rate_limited.emit.call_args_list[0].args[0]
        # After the block, the message should still be sent
        mock_session.send_text.assert_called_once()

    def test_human_delay_applied(self, mock_session):
        from app.workers.sender_worker import SenderWorker

        q = Queue()
        q.put({"chat_name": "GroupA", "content": "hello", "msgtype": "text"})

        human_timing = MagicMock()
        human_timing.sample_reply_delay.return_value = 0.1  # short for test

        mock_session.send_text_human = MagicMock(return_value=True)
        worker = SenderWorker(
            mock_session, q, max_retries=1,
            human_timing=human_timing,
            human_simulation_enabled=True,
        )
        worker.message_sent = MagicMock()
        worker.error_occurred = MagicMock()
        worker.rate_limited = MagicMock()
        worker.humanized_delay = MagicMock()

        _run_sender(worker, timeout=1.0)

        worker.humanized_delay.emit.assert_called_once_with(0.1)
        human_timing.sample_reply_delay.assert_called_once()

    def test_backward_compatible_without_humanization(self, mock_session):
        from app.workers.sender_worker import SenderWorker

        q = Queue()
        q.put({"chat_name": "GroupA", "content": "hello", "msgtype": "text"})

        mock_session.send_text = MagicMock(return_value=True)
        worker = SenderWorker(mock_session, q, max_retries=1)
        worker.message_sent = MagicMock()
        worker.error_occurred = MagicMock()
        worker.rate_limited = MagicMock()
        worker.humanized_delay = MagicMock()

        _run_sender(worker)

        mock_session.send_text.assert_called_once_with("GroupA", "hello")

    def test_rate_limiter_record_on_success(self, mock_session):
        from app.workers.sender_worker import SenderWorker

        q = Queue()
        q.put({"chat_name": "GroupA", "content": "hello", "msgtype": "text"})

        rate_limiter = MagicMock()
        rate_limiter.can_send.return_value = (True, "")

        mock_session.send_text = MagicMock(return_value=True)
        worker = SenderWorker(
            mock_session, q, max_retries=1,
            rate_limiter=rate_limiter,
        )
        worker.message_sent = MagicMock()
        worker.error_occurred = MagicMock()
        worker.rate_limited = MagicMock()
        worker.humanized_delay = MagicMock()

        _run_sender(worker)

        rate_limiter.record_send.assert_called_once()


class TestSenderWorkerStatusReporting:
    """Tests for agent status reporting to WebSocket bridge."""

    def test_report_status_called_on_send(self, mock_session):
        from app.workers.sender_worker import SenderWorker

        q = Queue()
        q.put({"chat_name": "GroupA", "content": "hello", "msgtype": "text"})

        ws_bridge = MagicMock()
        mock_session.send_text = MagicMock(return_value=True)
        worker = SenderWorker(
            mock_session, q, max_retries=1,
            ws_bridge=ws_bridge,
        )
        worker.message_sent = MagicMock()
        worker.error_occurred = MagicMock()
        worker.idle_action = MagicMock()

        _run_sender(worker)

        # report_status should have been called multiple times
        assert ws_bridge.report_status.call_count >= 2
        # First call should be "active" (on start)
        first_status = ws_bridge.report_status.call_args_list[0].args[0]
        assert first_status["state"] == "active"

    def test_report_status_includes_queue_size(self, mock_session):
        from app.workers.sender_worker import SenderWorker

        q = Queue()
        q.put({"chat_name": "GroupA", "content": "hello", "msgtype": "text"})
        q.put({"chat_name": "GroupB", "content": "world", "msgtype": "text"})

        ws_bridge = MagicMock()
        mock_session.send_text = MagicMock(return_value=True)
        worker = SenderWorker(
            mock_session, q, max_retries=1,
            ws_bridge=ws_bridge,
        )
        worker.message_sent = MagicMock()
        worker.error_occurred = MagicMock()
        worker.idle_action = MagicMock()

        _run_sender(worker, timeout=1.0)

        # At least one status report should have queue_size key
        statuses = [c.args[0] for c in ws_bridge.report_status.call_args_list]
        assert any("queue_size" in s for s in statuses)

    def test_report_status_error_on_failure(self, mock_session):
        from app.workers.sender_worker import SenderWorker

        q = Queue()
        q.put({"chat_name": "GroupA", "content": "hello", "msgtype": "text"})

        ws_bridge = MagicMock()
        mock_session.send_text = MagicMock(return_value=False)
        worker = SenderWorker(
            mock_session, q, max_retries=1,
            ws_bridge=ws_bridge,
        )
        worker.message_sent = MagicMock()
        worker.error_occurred = MagicMock()
        worker.idle_action = MagicMock()

        with patch("app.workers.sender_worker.time.sleep"):
            _run_sender(worker, timeout=1.0)

        # Should report error state
        statuses = [c.args[0] for c in ws_bridge.report_status.call_args_list]
        assert any(s.get("state") == "error" for s in statuses)
        assert any(s.get("error", "") != "" for s in statuses)

    def test_no_crash_without_ws_bridge(self, mock_session):
        """Worker should work fine without ws_bridge (backward compat)."""
        from app.workers.sender_worker import SenderWorker

        q = Queue()
        q.put({"chat_name": "GroupA", "content": "hello", "msgtype": "text"})

        mock_session.send_text = MagicMock(return_value=True)
        worker = SenderWorker(mock_session, q, max_retries=1)
        worker.message_sent = MagicMock()
        worker.error_occurred = MagicMock()
        worker.idle_action = MagicMock()

        _run_sender(worker)

        mock_session.send_text.assert_called_once()

    def test_report_status_with_rate_limiter_stats(self, mock_session):
        from app.workers.sender_worker import SenderWorker

        q = Queue()
        q.put({"chat_name": "GroupA", "content": "hello", "msgtype": "text"})

        ws_bridge = MagicMock()
        rate_limiter = MagicMock()
        rate_limiter.can_send.return_value = (True, "")
        rate_limiter.get_stats.return_value = {"hourly_count": 10, "daily_count": 50}

        mock_session.send_text = MagicMock(return_value=True)
        worker = SenderWorker(
            mock_session, q, max_retries=1,
            rate_limiter=rate_limiter,
            ws_bridge=ws_bridge,
        )
        worker.message_sent = MagicMock()
        worker.error_occurred = MagicMock()
        worker.idle_action = MagicMock()

        _run_sender(worker)

        statuses = [c.args[0] for c in ws_bridge.report_status.call_args_list]
        assert any(s.get("hourly_sent") == 10 for s in statuses)
        assert any(s.get("daily_sent") == 50 for s in statuses)

    def test_report_status_with_lifecycle(self, mock_session):
        from app.workers.sender_worker import SenderWorker

        q = Queue()
        q.put({"chat_name": "GroupA", "content": "hello", "msgtype": "text"})

        ws_bridge = MagicMock()
        lifecycle = MagicMock()
        lifecycle.should_process.return_value = True
        lifecycle.get_state.return_value = "active"
        lifecycle.should_idle.return_value = False

        mock_session.send_text = MagicMock(return_value=True)
        worker = SenderWorker(
            mock_session, q, max_retries=1,
            ws_bridge=ws_bridge,
            session_lifecycle=lifecycle,
        )
        worker.message_sent = MagicMock()
        worker.error_occurred = MagicMock()
        worker.idle_action = MagicMock()

        _run_sender(worker)

        statuses = [c.args[0] for c in ws_bridge.report_status.call_args_list]
        assert any(s.get("lifecycle_state") == "active" for s in statuses)
