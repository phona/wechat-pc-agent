import json
import logging
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from wechat.reader import MessageReader

logger = logging.getLogger(__name__)


class HistoryWorker(QThread):
    """Collects historical messages by scrolling up in selected chats."""

    progress_updated = pyqtSignal(int, str)  # (count, chat_name)
    chat_completed = pyqtSignal(str, int)    # (chat_name, total_new)
    all_completed = pyqtSignal()
    log_message = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, reader: MessageReader, client,
                 max_history_days: int = 30, sync_state_path: str = ""):
        super().__init__()
        self.reader = reader
        self.client = client
        self.max_history_days = max_history_days
        self.sync_state_path = sync_state_path
        self._chat_names: list[str] = []
        self._running = False

    def set_chats(self, chat_names: list[str]) -> None:
        self._chat_names = list(chat_names)

    def stop(self) -> None:
        self._running = False

    def _load_sync_state(self) -> dict:
        if not self.sync_state_path:
            return {}
        try:
            path = Path(self.sync_state_path)
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
        return {}

    def _save_sync_state(self, state: dict) -> None:
        if not self.sync_state_path:
            return
        path = Path(self.sync_state_path)
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.rename(path)

    def run(self) -> None:
        self._running = True
        self.log_message.emit(f"History collection starting for {len(self._chat_names)} chat(s)")
        sync_state = self._load_sync_state()

        for i, chat_name in enumerate(self._chat_names):
            if not self._running:
                self.log_message.emit("History collection stopped by user")
                break

            self.log_message.emit(f"Collecting history: {chat_name} ({i+1}/{len(self._chat_names)})")

            try:
                def on_batch(batch: list) -> None:
                    for msg in batch:
                        self.client.forward_message(msg)

                total = self.reader.collect_history(
                    chat_name=chat_name,
                    max_days=self.max_history_days,
                    progress_callback=lambda count, name: self.progress_updated.emit(count, name),
                    should_stop=lambda: not self._running,
                    on_batch=on_batch,
                )
                sync_state[chat_name] = {"status": "completed", "total": total}
                self._save_sync_state(sync_state)
                self.chat_completed.emit(chat_name, total)
                self.log_message.emit(f"Completed {chat_name}: {total} new messages")
            except Exception as e:
                self.error_occurred.emit(f"History error for {chat_name}: {e}")
                logger.error("History collection error: %s", e)

        self.all_completed.emit()
        self.log_message.emit("History collection finished")
