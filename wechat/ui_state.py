"""Multi-chat UI state manager.

Tracks which chats have been processed, deduplicates messages,
and prioritizes unread chats for processing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class ChatState:
    """State for a single chat conversation."""
    last_seen_msg_hash: str = ""
    last_seen_msg_preview: str = ""  # first 50 chars, for OCR/VLM prompt
    unread: bool = False
    last_checked: float = 0.0
    pending_count: int = 0
    row_bbox: tuple[int, int, int, int] | None = None  # (x, y, w, h) window-relative


class UIStateManager:
    """Manages state across multiple WeChat chats."""

    def __init__(self) -> None:
        self._chats: dict[str, ChatState] = {}
        self.active_chat: str | None = None

    def get_or_create(self, name: str) -> ChatState:
        if name not in self._chats:
            self._chats[name] = ChatState()
        return self._chats[name]

    def mark_unread(self, name: str, count: int | None = None) -> None:
        """Mark a chat as having unread messages."""
        state = self.get_or_create(name)
        state.unread = True
        if count is not None:
            state.pending_count = count

    def mark_read(self, name: str) -> None:
        """Mark a chat as read (no unread messages)."""
        state = self.get_or_create(name)
        state.unread = False
        state.pending_count = 0

    def mark_processed(self, name: str, msg_hash: str, msg_preview: str = "") -> None:
        """Mark a chat as processed with the last seen message hash."""
        state = self.get_or_create(name)
        state.last_seen_msg_hash = msg_hash
        state.last_seen_msg_preview = msg_preview[:50] if msg_preview else ""
        state.unread = False
        state.pending_count = 0
        state.last_checked = time.time()

    def update_from_sidebar(self, chats: list[dict]) -> None:
        """Update unread status from VLM sidebar reading.

        Args:
            chats: list of {"name": str, "has_unread": bool, "unread_count": int|None}
        """
        seen_names = set()
        for chat in chats:
            name = chat.get("name", "")
            if not name:
                continue
            seen_names.add(name)
            has_unread = chat.get("has_unread", False)
            count = chat.get("unread_count")
            if has_unread:
                self.mark_unread(name, count)
            else:
                state = self.get_or_create(name)
                state.unread = False
                state.pending_count = 0

    def get_next_unread(self) -> str | None:
        """Get the next unread chat to process.

        Priority: oldest last_checked time first (process chats we haven't
        looked at in the longest time).
        """
        unread = [
            (name, state)
            for name, state in self._chats.items()
            if state.unread
        ]
        if not unread:
            return None
        # Sort by last_checked ascending (oldest first)
        unread.sort(key=lambda x: x[1].last_checked)
        return unread[0][0]

    def has_unread(self) -> bool:
        """Check if any chat has unread messages."""
        return any(s.unread for s in self._chats.values())

    def get_last_seen_preview(self, name: str) -> str:
        """Get the last seen message preview for a chat."""
        state = self._chats.get(name)
        return state.last_seen_msg_preview if state else ""

    def get_last_seen_hash(self, name: str) -> str:
        """Get the last seen message hash for a chat."""
        state = self._chats.get(name)
        return state.last_seen_msg_hash if state else ""

    def get_all_chat_names(self) -> list[str]:
        """Get names of all known chats."""
        return list(self._chats.keys())

    def get_unread_count(self) -> int:
        """Get total number of unread chats."""
        return sum(1 for s in self._chats.values() if s.unread)

    def update_from_ocr(
        self, name: str, preview: str = "",
        has_unread: bool = False, count: int | None = None,
    ) -> None:
        """Update a single chat from OCR results (Layer 2)."""
        state = self.get_or_create(name)
        if preview:
            state.last_seen_msg_preview = preview[:50]
        if has_unread:
            state.unread = True
            if count is not None:
                state.pending_count = count
        else:
            state.unread = False
            state.pending_count = 0
