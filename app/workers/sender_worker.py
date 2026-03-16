import logging
import time
from queue import Queue, Empty
from PyQt6.QtCore import QThread, pyqtSignal

from wechat.session import WeChatSession

logger = logging.getLogger(__name__)


class SenderWorker(QThread):
    """Consumes the send queue and dispatches messages via wxauto."""

    message_sent = pyqtSignal(str)    # log message
    error_occurred = pyqtSignal(str)

    def __init__(self, session: WeChatSession, send_queue: Queue, max_retries: int = 3):
        super().__init__()
        self.session = session
        self.send_queue = send_queue
        self.max_retries = max_retries
        self._running = False

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        self._running = True
        self.message_sent.emit("Sender worker started")

        while self._running:
            try:
                item = self.send_queue.get(timeout=1.0)
            except Empty:
                continue

            chat_name = item.get("chat_name", "")
            content = item.get("content", "")
            msgtype = item.get("msgtype", "text")

            if not chat_name or not content:
                continue

            success = False
            for attempt in range(1, self.max_retries + 1):
                if not self._running:
                    break

                if msgtype == "text":
                    success = self.session.send_text(chat_name, content)
                else:
                    # For file types, content is file path
                    success = self.session.send_file(chat_name, content)

                if success:
                    self.message_sent.emit(f"Sent to {chat_name}: {content[:50]}...")
                    break

                self.error_occurred.emit(f"Send attempt {attempt}/{self.max_retries} failed for {chat_name}")
                time.sleep(2)

            if not success:
                self.error_occurred.emit(f"Failed to send to {chat_name} after {self.max_retries} retries")

        self.message_sent.emit("Sender worker stopped")
