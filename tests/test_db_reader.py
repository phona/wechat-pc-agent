"""Tests for WeChat database reader and related modules."""

import json
import sqlite3
from pathlib import Path

import pytest

from wechat.db.reader import DBMessage, DBReader, MSG_TYPE_TEXT, MSG_TYPE_IMAGE
from wechat.db.sync_state import SyncState
from wechat.db.decompress import decompress_message


# --- DBReader tests ---

@pytest.fixture
def sample_db(tmp_path):
    """Create a sample decrypted WeChat database with test data."""
    db_path = tmp_path / "MSG0.db"
    conn = sqlite3.connect(str(db_path))

    # Create a chat table mimicking WeChat's schema
    conn.execute("""
        CREATE TABLE Chat_abc123 (
            localId INTEGER PRIMARY KEY,
            strTalker TEXT,
            strContent TEXT,
            nCreateTime INTEGER,
            nMsgType INTEGER,
            CompressContent BLOB,
            BytesExtra BLOB
        )
    """)

    # Insert test messages
    messages = [
        (1, "user_a", "Hello", 1700000100, MSG_TYPE_TEXT, None, None),
        (2, "user_b", "Hi there", 1700000200, MSG_TYPE_TEXT, None, None),
        (3, "user_a", "", 1700000300, MSG_TYPE_IMAGE, None, None),
        (4, "user_b", "See you", 1700000400, MSG_TYPE_TEXT, None, None),
        (5, "user_a", "Bye", 1700000500, MSG_TYPE_TEXT, None, None),
    ]
    conn.executemany(
        "INSERT INTO Chat_abc123 VALUES (?, ?, ?, ?, ?, ?, ?)", messages,
    )

    # Create a second chat table
    conn.execute("""
        CREATE TABLE Chat_def456 (
            localId INTEGER PRIMARY KEY,
            strTalker TEXT,
            strContent TEXT,
            nCreateTime INTEGER,
            nMsgType INTEGER,
            CompressContent BLOB,
            BytesExtra BLOB
        )
    """)
    conn.execute(
        "INSERT INTO Chat_def456 VALUES (1, 'user_c', 'Test msg', 1700001000, 1, NULL, NULL)",
    )

    conn.commit()
    conn.close()
    return db_path


class TestDBReader:
    def test_get_chat_tables(self, sample_db):
        with DBReader(sample_db) as reader:
            tables = reader.get_chat_tables()
            assert set(tables) == {"Chat_abc123", "Chat_def456"}

    def test_get_conversations(self, sample_db):
        with DBReader(sample_db) as reader:
            convos = reader.get_conversations()
            assert len(convos) == 2

    def test_get_messages_all(self, sample_db):
        with DBReader(sample_db) as reader:
            msgs = reader.get_messages("Chat_abc123")
            assert len(msgs) == 5
            assert msgs[0].sender == "user_a"
            assert msgs[0].content == "Hello"
            assert msgs[0].timestamp == 1700000100
            assert msgs[0].msg_type == MSG_TYPE_TEXT

    def test_get_messages_after_timestamp(self, sample_db):
        with DBReader(sample_db) as reader:
            msgs = reader.get_messages("Chat_abc123", after_timestamp=1700000200)
            assert len(msgs) == 3
            assert msgs[0].content == ""  # image message
            assert msgs[0].msg_type == MSG_TYPE_IMAGE

    def test_get_messages_with_limit(self, sample_db):
        with DBReader(sample_db) as reader:
            msgs = reader.get_messages("Chat_abc123", limit=2)
            assert len(msgs) == 2

    def test_get_message_count(self, sample_db):
        with DBReader(sample_db) as reader:
            assert reader.get_message_count("Chat_abc123") == 5
            assert reader.get_message_count("Chat_def456") == 1

    def test_nonexistent_table(self, sample_db):
        with DBReader(sample_db) as reader:
            msgs = reader.get_messages("Chat_nonexistent")
            assert msgs == []
            assert reader.get_message_count("Chat_nonexistent") == 0

    def test_context_manager(self, sample_db):
        reader = DBReader(sample_db)
        with reader:
            msgs = reader.get_messages("Chat_abc123")
            assert len(msgs) == 5
        # After exiting, connection should be closed
        assert reader._conn is None

    def test_not_open_raises(self, sample_db):
        reader = DBReader(sample_db)
        with pytest.raises(RuntimeError, match="not open"):
            reader.get_chat_tables()


class TestDBMessage:
    def test_type_name(self):
        msg = DBMessage(1, "user", "hi", 100, MSG_TYPE_TEXT, "Chat_x")
        assert msg.type_name == "text"

        msg = DBMessage(2, "user", "", 200, MSG_TYPE_IMAGE, "Chat_x")
        assert msg.type_name == "image"

        msg = DBMessage(3, "user", "", 300, 999, "Chat_x")
        assert msg.type_name == "unknown(999)"

    def test_is_self(self):
        msg = DBMessage(1, "", "hi", 100, MSG_TYPE_TEXT, "Chat_x")
        assert msg.is_self is True

        msg = DBMessage(2, "other_user", "hi", 100, MSG_TYPE_TEXT, "Chat_x")
        assert msg.is_self is False


# --- SyncState tests ---

class TestSyncState:
    def test_new_state_returns_defaults(self, tmp_path):
        state = SyncState(tmp_path / "sync.json")
        state.load()
        assert state.get_db_last_timestamp("Chat_x") == 0
        assert state.get_db_synced_count("Chat_x") == 0

    def test_update_and_save(self, tmp_path):
        path = tmp_path / "sync.json"
        state = SyncState(path)
        state.load()

        state.update_db_sync("Chat_abc", 1700000500, 10)
        state.save()

        assert path.exists()

        # Reload
        state2 = SyncState(path)
        state2.load()
        assert state2.get_db_last_timestamp("Chat_abc") == 1700000500
        assert state2.get_db_synced_count("Chat_abc") == 10

    def test_update_accumulates_count(self, tmp_path):
        state = SyncState(tmp_path / "sync.json")
        state.load()

        state.update_db_sync("Chat_abc", 100, 5)
        state.update_db_sync("Chat_abc", 200, 3)
        assert state.get_db_synced_count("Chat_abc") == 8
        assert state.get_db_last_timestamp("Chat_abc") == 200

    def test_get_all(self, tmp_path):
        state = SyncState(tmp_path / "sync.json")
        state.load()
        state.update_db_sync("Chat_a", 100, 5)
        state.update_db_sync("Chat_b", 200, 10)

        all_state = state.get_all()
        assert len(all_state) == 2
        assert "Chat_a" in all_state
        assert "Chat_b" in all_state

    def test_corrupted_file(self, tmp_path):
        path = tmp_path / "sync.json"
        path.write_text("not json!!!")

        state = SyncState(path)
        state.load()  # should not raise
        assert state.get_db_last_timestamp("Chat_x") == 0

    def test_vision_msg_tracking(self, tmp_path):
        state = SyncState(tmp_path / "sync.json")
        state.load()
        state.record_vision_msg("Chat_a", 1000, "msg_001")
        assert state.is_msg_synced("msg_001") is True
        assert state.is_msg_synced("msg_002") is False

    def test_vision_msg_persists(self, tmp_path):
        path = tmp_path / "sync.json"
        state = SyncState(path)
        state.load()
        state.record_vision_msg("Chat_a", 1000, "msg_001")
        state.save()

        state2 = SyncState(path)
        state2.load()
        assert state2.is_msg_synced("msg_001") is True

    def test_vision_last_timestamp_max(self, tmp_path):
        state = SyncState(tmp_path / "sync.json")
        state.load()
        state.record_vision_msg("Chat_a", 2000, "m1")
        state.record_vision_msg("Chat_a", 1000, "m2")  # older
        all_s = state.get_all()
        assert all_s["Chat_a"]["vision_last_timestamp"] == 2000

    def test_vision_ids_trimmed_on_save(self, tmp_path):
        path = tmp_path / "sync.json"
        state = SyncState(path)
        state.load()
        state.MAX_VISION_IDS = 5  # small cap for testing
        for i in range(10):
            state.record_vision_msg("Chat_a", i, f"msg_{i}")
        state.save()
        # After save, only 5 IDs should remain
        assert len(state._vision_msg_ids) == 5

    def test_dual_track_independent(self, tmp_path):
        """Vision and DB channels track independently."""
        state = SyncState(tmp_path / "sync.json")
        state.load()
        state.record_vision_msg("Chat_a", 500, "v1")
        state.update_db_sync("Chat_a", 1000, 50)
        all_s = state.get_all()
        assert all_s["Chat_a"]["vision_last_timestamp"] == 500
        assert all_s["Chat_a"]["db_last_timestamp"] == 1000
        assert all_s["Chat_a"]["db_count"] == 50


# --- Decompress tests ---

class TestDecompressMessage:
    def test_no_compression(self):
        data = "Hello world".encode("utf-8")
        assert decompress_message(data, 0) == "Hello world"

    def test_empty_data(self):
        assert decompress_message(b"", 0) == ""
        assert decompress_message(b"", 4) == ""

    def test_zstd_compression(self):
        try:
            import zstandard as zstd
        except ImportError:
            pytest.skip("zstandard not installed")

        original = "这是一条测试消息"
        compressor = zstd.ZstdCompressor()
        compressed = compressor.compress(original.encode("utf-8"))

        result = decompress_message(compressed, 4)
        assert result == original

    def test_invalid_zstd_falls_through(self):
        # Invalid compressed data should fall through to raw decode
        data = "plain text".encode("utf-8")
        result = decompress_message(data, 4)
        # Should still return something (either decoded or with replacements)
        assert isinstance(result, str)

    def test_non_utf8_with_replace(self):
        data = b"\xff\xfe\x00\x01"
        result = decompress_message(data, 0)
        assert isinstance(result, str)
