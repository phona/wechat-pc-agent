import hashlib
import logging
import time
from typing import Optional, Callable

from wechat.session import WeChatSession

logger = logging.getLogger(__name__)


def message_hash(chat_name: str, sender: str, content: str, timestamp: str) -> str:
    """SHA-256 hash for deduplication."""
    raw = f"{chat_name}|{sender}|{content}|{timestamp}"
    return hashlib.sha256(raw.encode()).hexdigest()


class MessageReader:
    """Reads messages from WeChat — both new (polling) and history (scrolling)."""

    def __init__(self, session: WeChatSession, scroll_delay_ms: int = 800):
        self.session = session
        self.scroll_delay = scroll_delay_ms / 1000.0
        self._seen_hashes: set[str] = set()

    def poll_new_messages(self, chat_names: list[str]) -> list[dict]:
        """Poll for new messages across selected chats. Returns list of new messages."""
        new_messages = []
        for chat_name in chat_names:
            try:
                msgs = self.session.get_chat_messages(chat_name)
                for msg in msgs:
                    sender = getattr(msg, "sender", "") or chat_name
                    content = getattr(msg, "content", "") or ""
                    msg_type = self._detect_type(msg)
                    timestamp = getattr(msg, "time", "") or ""

                    h = message_hash(chat_name, str(sender), str(content), str(timestamp))
                    if h in self._seen_hashes:
                        continue
                    self._seen_hashes.add(h)

                    new_messages.append({
                        "chat_name": chat_name,
                        "sender": str(sender),
                        "msg_type": msg_type,
                        "content": str(content),
                        "timestamp": str(timestamp),
                    })
            except Exception as e:
                logger.error("Error polling %s: %s", chat_name, e)
        return new_messages

    def collect_history(
        self,
        chat_name: str,
        max_days: int = 30,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
        on_batch: Optional[Callable[[list[dict]], None]] = None,
    ) -> int:
        """
        Scroll up in a chat to collect historical messages.
        Returns total number of new messages collected.
        """
        logger.info("Starting history collection for: %s (max %d days)", chat_name, max_days)

        total_new = 0
        consecutive_empty = 0
        max_empty_scrolls = 5

        try:
            # Switch to the target chat
            self.session.wx.ChatWith(chat_name)
            time.sleep(0.5)

            while consecutive_empty < max_empty_scrolls:
                if should_stop and should_stop():
                    logger.info("History collection stopped by user for: %s", chat_name)
                    break

                # Read visible messages
                msgs = self.session.get_chat_messages()
                batch_new: list[dict] = []

                for msg in msgs:
                    sender = getattr(msg, "sender", "") or chat_name
                    content = getattr(msg, "content", "") or ""
                    msg_type = self._detect_type(msg)
                    timestamp = getattr(msg, "time", "") or ""

                    h = message_hash(chat_name, str(sender), str(content), str(timestamp))
                    if h in self._seen_hashes:
                        continue
                    self._seen_hashes.add(h)

                    batch_new.append({
                        "chat_name": chat_name,
                        "sender": str(sender),
                        "msg_type": msg_type,
                        "content": str(content),
                        "timestamp": str(timestamp),
                    })
                    total_new += 1

                if len(batch_new) == 0:
                    consecutive_empty += 1
                else:
                    consecutive_empty = 0
                    if on_batch:
                        on_batch(batch_new)

                if progress_callback:
                    progress_callback(total_new, chat_name)

                # Scroll up for older messages
                self.session.scroll_up()
                time.sleep(self.scroll_delay)

            status = "completed" if consecutive_empty >= max_empty_scrolls else "paused"
            logger.info("History collection %s for %s: %d new messages", status, chat_name, total_new)

        except Exception as e:
            logger.error("History collection error for %s: %s", chat_name, e)

        return total_new

    def _detect_type(self, msg) -> str:
        """Detect message type from wxauto message object."""
        msg_type = getattr(msg, "type", None)
        if msg_type:
            t = str(msg_type).lower()
            if "image" in t or "picture" in t:
                return "image"
            if "voice" in t or "audio" in t:
                return "voice"
            if "video" in t:
                return "video"
            if "file" in t:
                return "file"
        return "text"
