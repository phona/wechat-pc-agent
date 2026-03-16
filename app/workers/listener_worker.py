import logging
import time
from PyQt6.QtCore import QThread, pyqtSignal

from typing import Protocol

from wechat.session import WeChatSession
from wechat.reader import MessageReader, message_hash


class MessageForwarder(Protocol):
    def forward_message(self, sender_id: str, conversation_id: str, msg_type: str, content: str, **kwargs) -> bool: ...

logger = logging.getLogger(__name__)


class ListenerWorker(QThread):
    """
    Listens for new messages using wxauto's AddListenChat (event-driven).
    Falls back to polling if AddListenChat is not available.
    Forwards each new message to the orchestrator immediately.
    """

    message_received = pyqtSignal(str)  # log message
    error_occurred = pyqtSignal(str)

    def __init__(self, session: WeChatSession, client: MessageForwarder, poll_interval: float = 1.0):
        super().__init__()
        self.session = session
        self.client = client
        self.poll_interval = poll_interval
        self._chat_names: list[str] = []
        self._running = False
        self._seen_hashes: set[str] = set()

    def set_chats(self, chat_names: list[str]) -> None:
        self._chat_names = list(chat_names)

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        self._running = True
        self.message_received.emit("Listener started")

        # Register listeners for each chat
        for chat_name in self._chat_names:
            self.session.add_listen_chat(chat_name, callback=None)
        self.message_received.emit(f"Listening to {len(self._chat_names)} chat(s) via AddListenChat")

        while self._running:
            try:
                # GetListenMessage returns {chat_name: [messages]} for chats with new msgs
                listen_msgs = self.session.get_listen_messages()
                for chat_name, msgs in listen_msgs.items():
                    for msg in msgs:
                        sender = getattr(msg, "sender", "") or chat_name
                        content = getattr(msg, "content", "") or ""
                        msg_type = self._detect_type(msg)
                        timestamp = getattr(msg, "time", "") or ""

                        h = message_hash(chat_name, str(sender), str(content), str(timestamp))
                        if h in self._seen_hashes:
                            continue
                        self._seen_hashes.add(h)

                        success = self.client.forward_message(
                            sender_id=str(sender),
                            conversation_id=chat_name,
                            msg_type=msg_type,
                            content=str(content),
                        )
                        status = "forwarded" if success else "FAILED"
                        self.message_received.emit(
                            f"[{chat_name}] {sender}: {str(content)[:40]}... ({status})"
                        )
            except Exception as e:
                self.error_occurred.emit(f"Listener error: {e}")
                logger.error("Listener error: %s", e)

            time.sleep(self.poll_interval)

        # Cleanup listeners
        for chat_name in self._chat_names:
            self.session.remove_listen_chat(chat_name)
        self.message_received.emit("Listener stopped")

    @staticmethod
    def _detect_type(msg) -> str:
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
