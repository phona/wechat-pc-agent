"""SQLite query layer for decrypted WeChat databases."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .decompress import decompress_message

logger = logging.getLogger(__name__)

# WeChat message type constants
MSG_TYPE_TEXT = 1
MSG_TYPE_IMAGE = 3
MSG_TYPE_VOICE = 34
MSG_TYPE_VIDEO = 43
MSG_TYPE_EMOJI = 47
MSG_TYPE_LOCATION = 48
MSG_TYPE_LINK = 49
MSG_TYPE_VOIP = 50
MSG_TYPE_SYSTEM = 10000

MSG_TYPE_NAMES = {
    MSG_TYPE_TEXT: "text",
    MSG_TYPE_IMAGE: "image",
    MSG_TYPE_VOICE: "voice",
    MSG_TYPE_VIDEO: "video",
    MSG_TYPE_EMOJI: "emoji",
    MSG_TYPE_LOCATION: "location",
    MSG_TYPE_LINK: "link",
    MSG_TYPE_VOIP: "voip",
    MSG_TYPE_SYSTEM: "system",
}


@dataclass
class DBMessage:
    """A message from the WeChat database."""
    msg_id: int
    sender: str
    content: str
    timestamp: int
    msg_type: int
    conversation_id: str

    @property
    def type_name(self) -> str:
        return MSG_TYPE_NAMES.get(self.msg_type, f"unknown({self.msg_type})")

    @property
    def is_self(self) -> bool:
        """Check if message was sent by the account owner."""
        # In WeChat DB, self-sent messages have talker == conversation_id
        # and the sender field is empty or equals the owner wxid
        return not self.sender or self.sender == self.conversation_id


class DBReader:
    """Read messages from a decrypted WeChat database.

    WeChat stores messages across multiple database files (MSG0.db, MSG1.db, ...),
    each containing a set of chat tables named like 'Chat_<hash>'.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> DBReader:
        self.open()
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def _ensure_open(self) -> sqlite3.Connection:
        if not self._conn:
            raise RuntimeError("Database not open. Use open() or context manager.")
        return self._conn

    def get_chat_tables(self) -> list[str]:
        """Get all chat table names in this database."""
        conn = self._ensure_open()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Chat_%'",
        )
        return [row[0] for row in cursor.fetchall()]

    def get_conversations(self) -> list[str]:
        """Get unique conversation IDs from chat table names.

        The table name format is 'Chat_<md5hash>' where the hash maps to
        a conversation ID. We return the table names as identifiers.
        """
        return self.get_chat_tables()

    def get_messages(
        self,
        table_name: str,
        after_timestamp: int = 0,
        limit: int = 500,
    ) -> list[DBMessage]:
        """Read messages from a specific chat table.

        Args:
            table_name: The chat table name (e.g., 'Chat_abc123...').
            after_timestamp: Only return messages after this Unix timestamp.
            limit: Max messages to return.

        Returns:
            List of DBMessage sorted by timestamp ascending.
        """
        conn = self._ensure_open()
        try:
            cursor = conn.execute(
                f"SELECT localId, strTalker, strContent, nCreateTime, "
                f"nMsgType, CompressContent, BytesExtra "
                f"FROM [{table_name}] "
                f"WHERE nCreateTime > ? "
                f"ORDER BY nCreateTime ASC "
                f"LIMIT ?",
                (after_timestamp, limit),
            )
        except sqlite3.OperationalError as e:
            logger.debug("Failed to query table %s: %s", table_name, e)
            return []

        messages = []
        for row in cursor.fetchall():
            content = row["strContent"] or ""

            # Try decompressing if CompressContent exists
            compress_content = row["CompressContent"]
            if compress_content and isinstance(compress_content, bytes):
                decompressed = decompress_message(compress_content, 4)
                if decompressed:
                    content = decompressed

            messages.append(DBMessage(
                msg_id=row["localId"],
                sender=row["strTalker"] or "",
                content=content,
                timestamp=row["nCreateTime"],
                msg_type=row["nMsgType"],
                conversation_id=table_name,
            ))

        return messages

    def get_message_count(self, table_name: str) -> int:
        """Get total message count for a chat table."""
        conn = self._ensure_open()
        try:
            cursor = conn.execute(f"SELECT COUNT(*) FROM [{table_name}]")
            return cursor.fetchone()[0]
        except sqlite3.OperationalError:
            return 0
