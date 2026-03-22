"""Dual-track sync state: tracks both vision and DB channels."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class SyncState:
    """Track sync progress per conversation for both vision and DB channels.

    Format::

        {
            "conversations": {
                "Chat_abc123": {
                    "db_last_timestamp": 1700000000,
                    "db_count": 150,
                    "vision_last_timestamp": 1700001000
                }
            },
            "vision_msg_ids": ["msg1", "msg2", ...]
        }

    ``vision_msg_ids`` is a bounded set of recently forwarded message IDs
    used for deduplication during DB reconciliation.
    """

    MAX_VISION_IDS = 10000  # cap to avoid unbounded growth

    def __init__(self, state_path: Path) -> None:
        self._path = state_path
        self._conversations: dict[str, dict] = {}
        self._vision_msg_ids: set[str] = set()

    # ── persistence ──────────────────────────────────────────

    def load(self) -> None:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                self._conversations = raw.get("conversations", {})
                self._vision_msg_ids = set(raw.get("vision_msg_ids", []))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load sync state: %s", e)
                self._conversations = {}
                self._vision_msg_ids = set()

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # Trim vision IDs if over limit
        ids_list = list(self._vision_msg_ids)
        if len(ids_list) > self.MAX_VISION_IDS:
            ids_list = ids_list[-self.MAX_VISION_IDS:]
            self._vision_msg_ids = set(ids_list)
        data = {
            "conversations": self._conversations,
            "vision_msg_ids": ids_list,
        }
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # ── vision channel ───────────────────────────────────────

    def record_vision_msg(
        self, conversation_id: str, timestamp: int, msg_id: str,
    ) -> None:
        """Record a message forwarded by the vision pipeline."""
        self._vision_msg_ids.add(msg_id)
        entry = self._conversations.setdefault(conversation_id, {})
        entry["vision_last_timestamp"] = max(
            entry.get("vision_last_timestamp", 0), timestamp,
        )

    def is_msg_synced(self, msg_id: str) -> bool:
        """Check if a message was already forwarded (by either channel)."""
        return msg_id in self._vision_msg_ids

    # ── DB channel ───────────────────────────────────────────

    def get_db_last_timestamp(self, conversation_id: str) -> int:
        entry = self._conversations.get(conversation_id, {})
        return entry.get("db_last_timestamp", 0)

    def get_db_synced_count(self, conversation_id: str) -> int:
        entry = self._conversations.get(conversation_id, {})
        return entry.get("db_count", 0)

    def update_db_sync(
        self, conversation_id: str, last_timestamp: int, count: int,
    ) -> None:
        entry = self._conversations.setdefault(conversation_id, {})
        entry["db_last_timestamp"] = last_timestamp
        entry["db_count"] = entry.get("db_count", 0) + count

    # ── convenience ──────────────────────────────────────────

    def get_all(self) -> dict[str, dict]:
        return dict(self._conversations)
