from queue import Queue

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer

from config import AppConfig
from wechat.session import WeChatSession
from wechat.reader import MessageReader
from wechat.contacts import ContactCollector
from wechat.commander import CommandDispatcher
from bridge.ws_client import WebSocketBridge

from app.widgets.status_panel import StatusPanel
from app.widgets.control_panel import ControlPanel
from app.widgets.chat_selector import ChatSelector
from app.widgets.progress_panel import ProgressPanel
from app.widgets.log_viewer import LogViewer
from app.widgets.settings_dialog import SettingsDialog

from app.workers.listener_worker import ListenerWorker
from app.workers.history_worker import HistoryWorker
from app.workers.sender_worker import SenderWorker
from app.workers.contact_worker import ContactWorker
from app.workers.ws_worker import WebSocketWorker
from app.workers.db_worker import DBWorker
from wechat.db_decrypt import DBDecryptor


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self.setWindowTitle("WeChat Agent")
        self.setMinimumSize(800, 600)

        # Core components
        self.session = WeChatSession()
        self.send_queue: Queue = Queue()
        self.ws_bridge: WebSocketBridge | None = None

        # Build UI
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # Status
        self.status_panel = StatusPanel()
        main_layout.addWidget(self.status_panel)

        # Controls
        self.control_panel = ControlPanel()
        main_layout.addWidget(self.control_panel)

        # Middle: chat selector + progress
        middle = QSplitter(Qt.Orientation.Horizontal)
        self.chat_selector = ChatSelector()
        self.progress_panel = ProgressPanel()
        middle.addWidget(self.chat_selector)
        middle.addWidget(self.progress_panel)
        middle.setStretchFactor(0, 1)
        middle.setStretchFactor(1, 1)
        main_layout.addWidget(middle)

        # Log viewer
        self.log_viewer = LogViewer()
        main_layout.addWidget(self.log_viewer)

        # Workers (created on demand)
        self._listener_worker: ListenerWorker | None = None
        self._history_worker: HistoryWorker | None = None
        self._sender_worker: SenderWorker | None = None
        self._contact_worker: ContactWorker | None = None
        self._ws_worker: WebSocketWorker | None = None
        self._db_worker: DBWorker | None = None

        # Connect button signals
        self.control_panel.btn_connect.clicked.connect(self._connect_wechat)
        self.control_panel.btn_start.clicked.connect(self._start_listening)
        self.control_panel.btn_collect_history.clicked.connect(self._collect_history)
        self.control_panel.btn_stop.clicked.connect(self._stop_all)
        self.control_panel.btn_settings.clicked.connect(self._open_settings)
        self.chat_selector.btn_refresh.clicked.connect(self._refresh_chats)

        # Health check timer
        self._health_timer = QTimer(self)
        self._health_timer.timeout.connect(self._check_health)
        self._health_timer.start(10000)

        self.log_viewer.append("Agent ready. Click 'Connect WeChat' to begin.", "INFO")

    def _connect_wechat(self) -> None:
        self.log_viewer.append("Connecting to WeChat PC...", "INFO")
        if self.session.connect():
            self.status_panel.set_wechat_status(True)
            self.control_panel.set_connected(True)
            self.log_viewer.append("Connected to WeChat PC", "SUCCESS")
            self._refresh_chats()
            self._start_bridge()
        else:
            self.status_panel.set_wechat_status(False)
            reason = self.session.last_connect_error or "Is it running and logged in?"
            self.log_viewer.append(f"Failed to connect to WeChat: {reason}", "ERROR")
            if self.session.last_connect_diagnostics:
                self.log_viewer.append("Connect diagnostics:", "WARN")
                for line in self.session.last_connect_diagnostics:
                    self.log_viewer.append(f"  {line}", "INFO")
            QMessageBox.critical(
                self,
                "WeChat Connection Error",
                f"Failed to connect to WeChat:\n{reason}",
            )

    def _refresh_chats(self) -> None:
        if not self.session.is_ready():
            self.log_viewer.append("WeChat not connected", "WARN")
            return

        collector = ContactCollector(self.session)
        self._contact_worker = ContactWorker(collector)
        self._contact_worker.contacts_loaded.connect(self.chat_selector.set_chats)
        self._contact_worker.log_message.connect(lambda m: self.log_viewer.append(m, "INFO"))
        self._contact_worker.error_occurred.connect(lambda m: self.log_viewer.append(m, "ERROR"))
        self._contact_worker.start()

    def _start_bridge(self) -> None:
        """Start the WebSocket bridge and sender worker."""
        self._sender_worker = SenderWorker(self.session, self.send_queue)
        self._sender_worker.message_sent.connect(lambda m: self.log_viewer.append(m, "SUCCESS"))
        self._sender_worker.error_occurred.connect(lambda m: self.log_viewer.append(m, "ERROR"))
        self._sender_worker.start()

        commander = CommandDispatcher(self.session, history_callback=self._collect_history_for)
        self.ws_bridge = WebSocketBridge(
            ws_url=self.config.orchestrator_ws_url,
            token=self.config.agent_token,
            send_queue=self.send_queue,
            commander=commander,
            agent_id="agent-1",
        )
        self._ws_worker = WebSocketWorker(self.ws_bridge)
        self._ws_worker.log_message.connect(lambda m: self.log_viewer.append(m, "INFO"))
        self._ws_worker.error_occurred.connect(lambda m: self.log_viewer.append(m, "ERROR"))
        self._ws_worker.start()
        self.log_viewer.append(f"WebSocket bridge connecting to {self.config.orchestrator_ws_url}", "INFO")

        # Start DB worker for real-time message detection via WeChat DB.
        self._start_db_worker()

    def _start_db_worker(self) -> None:
        """Start the DB decryption + WAL monitor worker."""
        if not self.ws_bridge:
            return
        decryptor = DBDecryptor(out_dir=self.config.resolved_decrypted_db_dir)
        self._db_worker = DBWorker(
            decryptor=decryptor,
            bridge=self.ws_bridge,
            sync_timestamp=self.config.db_sync_timestamp,
            wal_poll_interval_ms=self.config.wal_poll_interval_ms,
        )
        self._db_worker.new_messages.connect(
            lambda n: self.log_viewer.append(f"DB: {n} new messages forwarded", "INFO")
        )
        self._db_worker.decrypt_complete.connect(
            lambda p: self.log_viewer.append(f"DB decrypted: {p}", "SUCCESS")
        )
        self._db_worker.history_complete.connect(
            lambda n: self.log_viewer.append(f"DB history scan: {n} messages total", "SUCCESS")
        )
        self._db_worker.log_message.connect(lambda m: self.log_viewer.append(m, "INFO"))
        self._db_worker.error_occurred.connect(lambda m: self.log_viewer.append(m, "ERROR"))
        self._db_worker.start()

    def _start_listening(self) -> None:
        selected = self.chat_selector.get_selected()
        if not selected:
            QMessageBox.warning(self, "No Chats", "Please select at least one chat to monitor.")
            return

        if not self.ws_bridge:
            QMessageBox.warning(self, "Not Connected", "WebSocket bridge not started.")
            return

        self._listener_worker = ListenerWorker(self.session, self.ws_bridge, self.config.poll_interval)
        self._listener_worker.set_chats(selected)
        self._listener_worker.message_received.connect(lambda m: self.log_viewer.append(m, "INFO"))
        self._listener_worker.error_occurred.connect(lambda m: self.log_viewer.append(m, "ERROR"))
        self._listener_worker.start()

        self.control_panel.set_running(True)
        self.log_viewer.append(f"Listening to {len(selected)} chat(s)", "SUCCESS")

    def _collect_history(self) -> None:
        selected = self.chat_selector.get_selected()
        if not selected:
            QMessageBox.warning(self, "No Chats", "Please select at least one chat.")
            return

        if not self.ws_bridge:
            QMessageBox.warning(self, "Not Connected", "WebSocket bridge not started.")
            return

        reader = MessageReader(self.session, self.config.scroll_delay_ms)
        self._history_worker = HistoryWorker(reader, self.ws_bridge, self.config.max_history_days, self.config.resolved_sync_state_path)
        self._history_worker.set_chats(selected)
        self._history_worker.progress_updated.connect(
            lambda count, name: self.progress_panel.set_collecting(name, count)
        )
        self._history_worker.chat_completed.connect(
            lambda name, count: self.progress_panel.set_chat_completed(name, count)
        )
        self._history_worker.all_completed.connect(
            lambda: self.progress_panel.set_idle()
        )
        self._history_worker.all_completed.connect(
            lambda: self.control_panel.set_running(False)
        )
        self._history_worker.log_message.connect(lambda m: self.log_viewer.append(m, "INFO"))
        self._history_worker.error_occurred.connect(lambda m: self.log_viewer.append(m, "ERROR"))
        self._history_worker.start()

        self.control_panel.set_running(True)
        self.log_viewer.append(f"Collecting history for {len(selected)} chat(s)", "INFO")

    def _collect_history_for(self, chat_name: str, days: int = 30) -> None:
        """Trigger history collection for a single chat (called by CommandDispatcher)."""
        if not self.ws_bridge:
            return
        reader = MessageReader(self.session, self.config.scroll_delay_ms)
        self._history_worker = HistoryWorker(reader, self.ws_bridge, days, self.config.resolved_sync_state_path)
        self._history_worker.set_chats([chat_name])
        self._history_worker.log_message.connect(lambda m: self.log_viewer.append(m, "INFO"))
        self._history_worker.error_occurred.connect(lambda m: self.log_viewer.append(m, "ERROR"))
        self._history_worker.all_completed.connect(lambda: self.control_panel.set_running(False))
        self._history_worker.start()
        self.log_viewer.append(f"History collection started for {chat_name} ({days} days)", "INFO")

    def _stop_all(self) -> None:
        for worker in (self._listener_worker, self._history_worker, self._db_worker):
            if worker and worker.isRunning():
                worker.stop()
        self.control_panel.set_running(False)
        self.progress_panel.set_idle()
        self.log_viewer.append("All tasks stopped", "WARN")

    def _open_settings(self) -> None:
        try:
            dialog = SettingsDialog(self.config, self)
            if dialog.exec():
                self.log_viewer.append("Settings saved (reconnect to apply)", "SUCCESS")
        except Exception as exc:
            self.log_viewer.append(f"Failed to open settings: {exc}", "ERROR")
            QMessageBox.critical(self, "Settings Error", f"Failed to open settings: {exc}")

    def _check_health(self) -> None:
        if self.ws_bridge:
            self.status_panel.set_orchestrator_status(self.ws_bridge.health_check())

        if self.session._wx is not None:
            ready = self.session.is_ready()
            self.status_panel.set_wechat_status(ready)

    def closeEvent(self, event) -> None:
        for worker in (self._listener_worker, self._history_worker,
                        self._sender_worker, self._ws_worker, self._db_worker):
            if worker and worker.isRunning():
                worker.stop()
                worker.wait(3000)
        super().closeEvent(event)
