"""Monitor WeChat MSG database WAL files for real-time message detection."""

import glob
import logging
import os
import threading
import time
from typing import Callable

from wechat.db_decrypt import DBDecryptor
from wechat.db_reader import DBReader, DBMessage

logger = logging.getLogger(__name__)


class WALMonitor:
    """Poll WAL file modification times to detect new messages.

    When a change is detected, re-decrypts the DB and queries for new rows.
    """

    def __init__(
        self,
        wx_dir: str,
        decryptor: DBDecryptor,
        reader: DBReader,
        on_new_messages: Callable[[list[DBMessage]], None],
        poll_interval_ms: int = 100,
    ):
        self.wx_dir = wx_dir
        self.decryptor = decryptor
        self.reader = reader
        self.on_new_messages = on_new_messages
        self.poll_interval = poll_interval_ms / 1000.0

        self._running = False
        self._thread: threading.Thread | None = None
        self._last_mtimes: dict[str, float] = {}
        self._last_timestamp: int = 0

    def start(self, last_timestamp: int = 0) -> None:
        """Start the WAL monitoring loop in a background thread."""
        self._last_timestamp = last_timestamp or self.reader.get_latest_timestamp()
        self._last_mtimes = self._get_wal_mtimes()
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        logger.info("WAL monitor started (interval=%dms, cursor=%d)",
                     int(self.poll_interval * 1000), self._last_timestamp)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _poll_loop(self) -> None:
        while self._running:
            try:
                current_mtimes = self._get_wal_mtimes()
                if current_mtimes != self._last_mtimes:
                    self._last_mtimes = current_mtimes
                    self._on_wal_changed()
            except Exception:
                logger.exception("WAL monitor error")
            time.sleep(self.poll_interval)

    def _on_wal_changed(self) -> None:
        """WAL file changed — re-decrypt and check for new messages."""
        try:
            self.decryptor.refresh()
        except Exception:
            logger.exception("Failed to refresh decrypted DB")
            return

        new_msgs = self.reader.get_messages_since(self._last_timestamp)
        if not new_msgs:
            return

        # Advance cursor to latest message timestamp.
        self._last_timestamp = max(m.create_time for m in new_msgs)
        logger.info("WAL monitor: %d new messages (cursor→%d)", len(new_msgs), self._last_timestamp)

        try:
            self.on_new_messages(new_msgs)
        except Exception:
            logger.exception("on_new_messages callback failed")

    def _get_wal_mtimes(self) -> dict[str, float]:
        """Get modification times of all MSG*-wal files."""
        msg_dir = os.path.join(self.wx_dir, "Msg")
        pattern = os.path.join(msg_dir, "MSG*.db-wal")
        mtimes = {}
        for path in glob.glob(pattern):
            try:
                mtimes[path] = os.path.getmtime(path)
            except OSError:
                pass
        return mtimes

    @property
    def last_timestamp(self) -> int:
        return self._last_timestamp
