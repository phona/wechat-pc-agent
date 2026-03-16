"""Read messages from decrypted WeChat MSG database."""

import sqlite3
from dataclasses import dataclass


MSG_TYPE_MAP = {
    1: "text",
    3: "image",
    34: "voice",
    43: "video",
    47: "emoji",
    49: "file",
    10000: "system",
}


@dataclass
class DBMessage:
    local_id: int
    msg_svr_id: int
    msg_type: int
    is_sender: bool
    create_time: int
    talker: str
    content: str

    @property
    def type_name(self) -> str:
        return MSG_TYPE_MAP.get(self.msg_type, f"unknown({self.msg_type})")


class DBReader:
    """Query decrypted WeChat MSG database."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def get_messages_since(self, timestamp: int, limit: int = 500) -> list[DBMessage]:
        """Get messages created after the given unix timestamp."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT localId, MsgSvrID, Type, IsSender, CreateTime, StrTalker, StrContent "
                "FROM MSG WHERE CreateTime > ? ORDER BY CreateTime ASC LIMIT ?",
                (timestamp, limit),
            ).fetchall()
            return [self._row_to_msg(r) for r in rows]
        finally:
            conn.close()

    def get_messages_for_contact(self, talker: str, since: int, limit: int = 500) -> list[DBMessage]:
        """Get messages for a specific contact/group since a timestamp."""
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT localId, MsgSvrID, Type, IsSender, CreateTime, StrTalker, StrContent "
                "FROM MSG WHERE StrTalker = ? AND CreateTime > ? ORDER BY CreateTime ASC LIMIT ?",
                (talker, since, limit),
            ).fetchall()
            return [self._row_to_msg(r) for r in rows]
        finally:
            conn.close()

    def get_all_talkers(self) -> list[str]:
        """Get all unique talker IDs (contacts and groups)."""
        conn = self._connect()
        try:
            rows = conn.execute("SELECT DISTINCT StrTalker FROM MSG").fetchall()
            return [r["StrTalker"] for r in rows]
        finally:
            conn.close()

    def get_latest_timestamp(self) -> int:
        """Get the most recent message timestamp."""
        conn = self._connect()
        try:
            row = conn.execute("SELECT MAX(CreateTime) as ts FROM MSG").fetchone()
            return row["ts"] or 0
        finally:
            conn.close()

    @staticmethod
    def _row_to_msg(row: sqlite3.Row) -> DBMessage:
        return DBMessage(
            local_id=row["localId"],
            msg_svr_id=row["MsgSvrID"],
            msg_type=row["Type"],
            is_sender=bool(row["IsSender"]),
            create_time=row["CreateTime"],
            talker=row["StrTalker"],
            content=row["StrContent"] or "",
        )
