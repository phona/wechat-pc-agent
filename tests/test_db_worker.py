"""Tests for DBWorker QThread — decrypt, history scan, WAL monitor lifecycle."""
import pytest
from unittest.mock import MagicMock, patch, call
from dataclasses import dataclass


@dataclass
class FakeDBMessage:
    local_id: int
    msg_svr_id: int
    msg_type: int
    is_sender: bool
    create_time: int
    talker: str
    content: str

    @property
    def type_name(self) -> str:
        return "text"


@pytest.fixture
def bridge():
    b = MagicMock()
    b.forward_message.return_value = True
    return b


@pytest.fixture
def decryptor(tmp_path):
    d = MagicMock()
    d.decrypt.return_value = str(tmp_path / "MSG_ALL.db")
    d.wx_dir = "/fake/wechat"
    d.merged_path = str(tmp_path / "MSG_ALL.db")
    return d


def _make_worker(decryptor, bridge, sync_timestamp=0, wal_poll_interval_ms=100):
    from app.workers.db_worker import DBWorker
    w = DBWorker(decryptor, bridge, sync_timestamp, wal_poll_interval_ms)
    w.new_messages = MagicMock()
    w.decrypt_complete = MagicMock()
    w.history_complete = MagicMock()
    w.log_message = MagicMock()
    w.error_occurred = MagicMock()

    # Default msleep: stop after first call to prevent infinite keep-alive loop
    def _msleep_auto_stop(ms):
        w._running = False
    w.msleep = _msleep_auto_stop
    return w


def _patch_wal():
    """Patch WALMonitor so it doesn't actually run."""
    return patch("wechat.wal_monitor.WALMonitor")


class TestDBWorkerDecrypt:
    def test_decrypt_failure_emits_error(self, bridge):
        d = MagicMock()
        d.decrypt.side_effect = RuntimeError("WeChat not running")
        w = _make_worker(d, bridge)

        w.run()

        w.error_occurred.emit.assert_called_once()
        assert "Decrypt failed" in w.error_occurred.emit.call_args[0][0]
        w.decrypt_complete.emit.assert_not_called()

    def test_decrypt_success_emits_path(self, decryptor, bridge):
        w = _make_worker(decryptor, bridge)

        # Stop after one msleep cycle in the keep-alive loop
        call_count = [0]
        def msleep_stop(ms):
            call_count[0] += 1
            if call_count[0] >= 1:
                w._running = False
        w.msleep = msleep_stop

        with patch("app.workers.db_worker.DBReader") as MockReader, _patch_wal():
            MockReader.return_value.get_messages_since.return_value = []
            w.run()

        w.decrypt_complete.emit.assert_called_once_with(decryptor.decrypt.return_value)


class TestDBWorkerHistoryScan:
    def test_forwards_history_messages(self, decryptor, bridge):
        msgs_batch1 = [
            FakeDBMessage(1, 100, 1, False, 1000, "alice", "hello"),
            FakeDBMessage(2, 101, 1, True, 1001, "me", "hi"),  # is_sender — skipped
        ]

        w = _make_worker(decryptor, bridge, sync_timestamp=0)

        with patch("app.workers.db_worker.DBReader") as MockReader, _patch_wal():
            reader = MockReader.return_value
            reader.get_messages_since.side_effect = [msgs_batch1, []]
            w.run()

        # Only incoming (non-sender) message forwarded
        bridge.forward_message.assert_called_once_with(
            sender_id="alice",
            conversation_id="alice",
            msg_type="text",
            content="hello",
        )
        w.new_messages.emit.assert_called_with(2)  # batch size, not filtered count
        w.history_complete.emit.assert_called_once_with(2)

    def test_history_scan_paginates(self, decryptor, bridge):
        batch1 = [FakeDBMessage(i, i, 1, False, 1000 + i, "bob", f"msg{i}") for i in range(3)]
        batch2 = [FakeDBMessage(10, 10, 1, False, 2000, "bob", "last")]

        w = _make_worker(decryptor, bridge)

        with patch("app.workers.db_worker.DBReader") as MockReader, _patch_wal():
            reader = MockReader.return_value
            reader.get_messages_since.side_effect = [batch1, batch2, []]
            w.run()

        assert bridge.forward_message.call_count == 4
        w.history_complete.emit.assert_called_once_with(4)

    def test_history_scan_error_emits_and_continues(self, decryptor, bridge):
        """History scan error is reported but worker still emits history_complete."""
        w = _make_worker(decryptor, bridge)

        with patch("app.workers.db_worker.DBReader") as MockReader, _patch_wal():
            reader = MockReader.return_value
            reader.get_messages_since.side_effect = Exception("DB locked")
            w.run()

        w.error_occurred.emit.assert_called()
        assert any("History scan failed" in c.args[0] for c in w.error_occurred.emit.call_args_list)
        w.history_complete.emit.assert_called_once_with(0)

    def test_stop_during_history_scan(self, decryptor, bridge):
        """Stopping during history scan exits cleanly."""
        batch = [FakeDBMessage(1, 1, 1, False, 1000, "alice", "hello")]

        w = _make_worker(decryptor, bridge)

        with patch("app.workers.db_worker.DBReader") as MockReader:
            reader = MockReader.return_value

            def stop_on_second_call(*args, **kwargs):
                w._running = False
                return []

            reader.get_messages_since.side_effect = [batch, stop_on_second_call]
            w.run()

        # Should have forwarded first batch then stopped
        w.history_complete.emit.assert_called_once()


class TestDBWorkerWALMonitor:
    def test_starts_wal_monitor_after_history(self, decryptor, bridge):
        w = _make_worker(decryptor, bridge, wal_poll_interval_ms=50)

        call_count = [0]

        def msleep_stop(ms):
            call_count[0] += 1
            if call_count[0] >= 2:
                w._running = False

        w.msleep = msleep_stop

        with patch("app.workers.db_worker.DBReader") as MockReader, \
             patch("wechat.wal_monitor.WALMonitor") as MockWAL:
            MockReader.return_value.get_messages_since.return_value = []
            w.run()

        MockWAL.assert_called_once()
        MockWAL.return_value.start.assert_called_once()
        MockWAL.return_value.stop.assert_called_once()

    def test_no_wal_monitor_without_wx_dir(self, bridge, tmp_path):
        d = MagicMock()
        d.decrypt.return_value = str(tmp_path / "MSG_ALL.db")
        d.wx_dir = None

        w = _make_worker(d, bridge)

        with patch("app.workers.db_worker.DBReader") as MockReader:
            MockReader.return_value.get_messages_since.return_value = []
            w.run()

        w.error_occurred.emit.assert_called()
        assert any("wx_dir unknown" in c.args[0] for c in w.error_occurred.emit.call_args_list)


class TestDBWorkerRealtimeCallback:
    def test_on_realtime_messages_forwards_incoming(self, decryptor, bridge):
        from app.workers.db_worker import DBWorker

        w = _make_worker(decryptor, bridge)

        msgs = [
            FakeDBMessage(1, 100, 1, False, 5000, "alice", "new msg"),
            FakeDBMessage(2, 101, 1, True, 5001, "me", "outgoing"),
        ]
        w._on_realtime_messages(msgs)

        bridge.forward_message.assert_called_once_with(
            sender_id="alice",
            conversation_id="alice",
            msg_type="text",
            content="new msg",
        )
        w.new_messages.emit.assert_called_once_with(1)
        assert w.sync_timestamp == 5001

    def test_on_realtime_messages_all_outgoing(self, decryptor, bridge):
        w = _make_worker(decryptor, bridge)

        msgs = [FakeDBMessage(1, 100, 1, True, 5000, "me", "outgoing")]
        w._on_realtime_messages(msgs)

        bridge.forward_message.assert_not_called()
        w.new_messages.emit.assert_not_called()


class TestDBWorkerStop:
    def test_stop_sets_flag_and_stops_monitor(self, decryptor, bridge):
        w = _make_worker(decryptor, bridge)
        w._running = True
        mock_monitor = MagicMock()
        w._wal_monitor = mock_monitor

        w.stop()

        assert w._running is False
        mock_monitor.stop.assert_called_once()

    def test_stop_without_monitor(self, decryptor, bridge):
        w = _make_worker(decryptor, bridge)
        w._running = True
        w.stop()
        assert w._running is False
