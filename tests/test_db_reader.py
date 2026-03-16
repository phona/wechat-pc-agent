"""Tests for DBReader using an in-memory SQLite database."""

import sqlite3
import tempfile
import os
import pytest

from wechat.db_reader import DBReader, DBMessage


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary MSG database with test data."""
    path = str(tmp_path / "MSG_ALL.db")
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE MSG (
            localId INTEGER PRIMARY KEY,
            MsgSvrID INT,
            Type INT,
            IsSender INT,
            CreateTime INT,
            StrTalker TEXT,
            StrContent TEXT,
            CompressContent BLOB
        )
    """)
    conn.executemany(
        "INSERT INTO MSG (localId, MsgSvrID, Type, IsSender, CreateTime, StrTalker, StrContent) VALUES (?,?,?,?,?,?,?)",
        [
            (1, 1001, 1, 0, 1700000000, "wxid_alice", "Hello"),
            (2, 1002, 1, 1, 1700000001, "wxid_alice", "Hi back"),
            (3, 1003, 3, 0, 1700000010, "wxid_bob", "[image]"),
            (4, 1004, 1, 0, 1700000020, "group@chatroom", "Group message"),
            (5, 1005, 34, 0, 1700000030, "wxid_alice", "[voice]"),
            (6, 1006, 49, 0, 1700000040, "wxid_bob", "<xml>file</xml>"),
        ],
    )
    conn.commit()
    conn.close()
    return path


class TestDBReader:
    def test_get_messages_since(self, db_path):
        reader = DBReader(db_path)
        msgs = reader.get_messages_since(1700000005)
        assert len(msgs) == 4
        assert msgs[0].talker == "wxid_bob"
        assert msgs[0].msg_type == 3

    def test_get_messages_since_zero(self, db_path):
        reader = DBReader(db_path)
        msgs = reader.get_messages_since(0)
        assert len(msgs) == 6

    def test_get_messages_since_with_limit(self, db_path):
        reader = DBReader(db_path)
        msgs = reader.get_messages_since(0, limit=2)
        assert len(msgs) == 2
        assert msgs[0].content == "Hello"
        assert msgs[1].content == "Hi back"

    def test_get_messages_for_contact(self, db_path):
        reader = DBReader(db_path)
        msgs = reader.get_messages_for_contact("wxid_alice", since=0)
        assert len(msgs) == 3
        assert all(m.talker == "wxid_alice" for m in msgs)

    def test_get_messages_for_contact_with_timestamp(self, db_path):
        reader = DBReader(db_path)
        msgs = reader.get_messages_for_contact("wxid_alice", since=1700000005)
        assert len(msgs) == 1
        assert msgs[0].msg_type == 34  # voice

    def test_get_all_talkers(self, db_path):
        reader = DBReader(db_path)
        talkers = reader.get_all_talkers()
        assert set(talkers) == {"wxid_alice", "wxid_bob", "group@chatroom"}

    def test_get_latest_timestamp(self, db_path):
        reader = DBReader(db_path)
        assert reader.get_latest_timestamp() == 1700000040

    def test_get_latest_timestamp_empty_db(self, tmp_path):
        path = str(tmp_path / "empty.db")
        conn = sqlite3.connect(path)
        conn.execute("""
            CREATE TABLE MSG (
                localId INTEGER PRIMARY KEY, MsgSvrID INT, Type INT,
                IsSender INT, CreateTime INT, StrTalker TEXT, StrContent TEXT
            )
        """)
        conn.commit()
        conn.close()
        reader = DBReader(path)
        assert reader.get_latest_timestamp() == 0

    def test_dbmessage_type_name(self, db_path):
        reader = DBReader(db_path)
        msgs = reader.get_messages_since(0)
        assert msgs[0].type_name == "text"
        assert msgs[2].type_name == "image"
        assert msgs[4].type_name == "voice"
        assert msgs[5].type_name == "file"

    def test_is_sender_flag(self, db_path):
        reader = DBReader(db_path)
        msgs = reader.get_messages_since(0)
        assert msgs[0].is_sender is False
        assert msgs[1].is_sender is True
