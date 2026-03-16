"""Tests for WALMonitor."""

import os
import time
import tempfile
import sqlite3
import pytest
from unittest.mock import MagicMock, patch

from wechat.db_reader import DBReader, DBMessage
from wechat.wal_monitor import WALMonitor


@pytest.fixture
def wx_dir(tmp_path):
    """Create a fake WeChat Msg directory with WAL files."""
    msg_dir = tmp_path / "Msg"
    msg_dir.mkdir()
    # Create fake WAL files
    for i in range(3):
        wal = msg_dir / f"MSG{i}.db-wal"
        wal.write_bytes(b"fake wal data")
    return str(tmp_path)


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "MSG_ALL.db")
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE MSG (
            localId INTEGER PRIMARY KEY, MsgSvrID INT, Type INT,
            IsSender INT, CreateTime INT, StrTalker TEXT, StrContent TEXT
        )
    """)
    conn.commit()
    conn.close()
    return path


class TestWALMonitor:
    def test_detects_wal_change(self, wx_dir, db_path):
        """Monitor detects WAL mtime change and calls on_new_messages."""
        decryptor = MagicMock()
        reader = DBReader(db_path)
        callback = MagicMock()

        # Insert a message so get_messages_since returns something
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO MSG VALUES (1, 1001, 1, 0, 1700000100, 'wxid_test', 'new msg')"
        )
        conn.commit()
        conn.close()

        monitor = WALMonitor(
            wx_dir=wx_dir,
            decryptor=decryptor,
            reader=reader,
            on_new_messages=callback,
            poll_interval_ms=50,
        )
        monitor.start(last_timestamp=1700000000)

        # Simulate WAL file change by touching the file
        time.sleep(0.1)
        wal_path = os.path.join(wx_dir, "Msg", "MSG0.db-wal")
        os.utime(wal_path, None)

        # Wait for detection
        time.sleep(0.3)
        monitor.stop()

        decryptor.refresh.assert_called()
        callback.assert_called_once()
        msgs = callback.call_args[0][0]
        assert len(msgs) == 1
        assert msgs[0].content == "new msg"

    def test_no_change_no_callback(self, wx_dir, db_path):
        """No WAL change means no callback."""
        decryptor = MagicMock()
        reader = DBReader(db_path)
        callback = MagicMock()

        monitor = WALMonitor(
            wx_dir=wx_dir,
            decryptor=decryptor,
            reader=reader,
            on_new_messages=callback,
            poll_interval_ms=50,
        )
        monitor.start(last_timestamp=0)
        time.sleep(0.2)
        monitor.stop()

        decryptor.refresh.assert_not_called()
        callback.assert_not_called()

    def test_stop(self, wx_dir, db_path):
        decryptor = MagicMock()
        reader = DBReader(db_path)

        monitor = WALMonitor(
            wx_dir=wx_dir,
            decryptor=decryptor,
            reader=reader,
            on_new_messages=MagicMock(),
            poll_interval_ms=50,
        )
        monitor.start(last_timestamp=0)
        assert monitor._running is True
        monitor.stop()
        assert monitor._running is False

    def test_advances_cursor(self, wx_dir, db_path):
        """Cursor advances to max create_time of new messages."""
        decryptor = MagicMock()
        reader = DBReader(db_path)
        callback = MagicMock()

        conn = sqlite3.connect(db_path)
        conn.execute("INSERT INTO MSG VALUES (1, 1001, 1, 0, 1700000100, 'a', 'msg1')")
        conn.execute("INSERT INTO MSG VALUES (2, 1002, 1, 0, 1700000200, 'b', 'msg2')")
        conn.commit()
        conn.close()

        monitor = WALMonitor(
            wx_dir=wx_dir,
            decryptor=decryptor,
            reader=reader,
            on_new_messages=callback,
            poll_interval_ms=50,
        )
        monitor.start(last_timestamp=0)

        time.sleep(0.1)
        wal_path = os.path.join(wx_dir, "Msg", "MSG0.db-wal")
        os.utime(wal_path, None)
        time.sleep(0.3)
        monitor.stop()

        assert monitor.last_timestamp == 1700000200
