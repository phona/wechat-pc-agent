import logging
from PyQt6.QtCore import QThread, pyqtSignal

from wechat.contacts import ContactCollector

logger = logging.getLogger(__name__)


class ContactWorker(QThread):
    """Collects contacts and groups in background."""

    contacts_loaded = pyqtSignal(list)   # list of session names
    log_message = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, collector: ContactCollector):
        super().__init__()
        self.collector = collector

    def run(self) -> None:
        self.log_message.emit("Collecting contacts...")
        try:
            result = self.collector.collect_all()
            sessions = result.get("sessions", [])
            friends = result.get("friends", [])
            self.contacts_loaded.emit(sessions)
            self.log_message.emit(f"Loaded {len(sessions)} sessions, {len(friends)} friends")
        except Exception as e:
            self.error_occurred.emit(f"Contact collection failed: {e}")
            logger.error("Contact collection error: %s", e)
