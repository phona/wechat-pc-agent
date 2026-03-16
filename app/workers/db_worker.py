"""QThread worker for WeChat DB operations: decrypt, history scan, WAL monitor."""

import logging

from PyQt6.QtCore import QThread, pyqtSignal

from wechat.db_decrypt import DBDecryptor
from wechat.db_reader import DBReader, DBMessage

logger = logging.getLogger(__name__)


class DBWorker(QThread):
    """Manages decrypt -> initial history scan -> WAL monitor lifecycle."""

    new_messages = pyqtSignal(int)
    decrypt_complete = pyqtSignal(str)  # merged db path
    history_complete = pyqtSignal(int)  # total messages forwarded
    log_message = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        decryptor: DBDecryptor,
        bridge,  # WebSocketBridge — has forward_message()
        sync_timestamp: int = 0,
        wal_poll_interval_ms: int = 100,
    ):
        super().__init__()
        self.decryptor = decryptor
        self.bridge = bridge
        self.sync_timestamp = sync_timestamp
        self.wal_poll_interval_ms = wal_poll_interval_ms
        self._running = False
        self._wal_monitor = None

    def run(self) -> None:
        self._running = True

        # Step 1: Decrypt databases.
        self.log_message.emit("Decrypting WeChat databases...")
        try:
            db_path = self.decryptor.decrypt()
        except Exception as e:
            self.error_occurred.emit(f"Decrypt failed: {e}")
            return

        self.decrypt_complete.emit(db_path)
        self.log_message.emit(f"Decrypted DB: {db_path}")

        reader = DBReader(db_path)

        # Step 2: Forward history since last sync timestamp.
        self.log_message.emit(f"Scanning history since timestamp {self.sync_timestamp}...")
        total_forwarded = 0
        try:
            while self._running:
                msgs = reader.get_messages_since(self.sync_timestamp, limit=500)
                if not msgs:
                    break
                self._forward_messages(msgs)
                total_forwarded += len(msgs)
                self.sync_timestamp = max(m.create_time for m in msgs)
                self.new_messages.emit(len(msgs))
        except Exception as e:
            self.error_occurred.emit(f"History scan failed: {e}")

        self.history_complete.emit(total_forwarded)
        self.log_message.emit(f"History scan complete: {total_forwarded} messages forwarded")

        if not self._running:
            return

        # Step 3: Start WAL monitor for real-time detection.
        wx_dir = self.decryptor.wx_dir
        if not wx_dir:
            self.error_occurred.emit("Cannot start WAL monitor: wx_dir unknown")
            return

        from wechat.wal_monitor import WALMonitor

        self._wal_monitor = WALMonitor(
            wx_dir=wx_dir,
            decryptor=self.decryptor,
            reader=reader,
            on_new_messages=self._on_realtime_messages,
            poll_interval_ms=self.wal_poll_interval_ms,
        )
        self._wal_monitor.start(last_timestamp=self.sync_timestamp)
        self.log_message.emit("WAL monitor started for real-time detection")

        # Keep thread alive while WAL monitor runs.
        while self._running:
            self.msleep(500)

        self._wal_monitor.stop()

    def _forward_messages(self, msgs: list[DBMessage]) -> None:
        """Forward messages to orchestrator via WebSocket bridge."""
        for msg in msgs:
            if msg.is_sender:
                continue  # Skip outgoing messages
            self.bridge.forward_message(
                sender_id=msg.talker,
                conversation_id=msg.talker,
                msg_type=msg.type_name,
                content=msg.content,
            )

    def _on_realtime_messages(self, msgs: list[DBMessage]) -> None:
        """Callback from WAL monitor when new messages detected."""
        self._forward_messages(msgs)
        count = sum(1 for m in msgs if not m.is_sender)
        if count > 0:
            self.new_messages.emit(count)
            self.sync_timestamp = max(m.create_time for m in msgs)

    def stop(self) -> None:
        self._running = False
        if self._wal_monitor:
            self._wal_monitor.stop()
