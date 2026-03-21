from queue import Queue

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer

from config import AppConfig
from wechat.session import WeChatSession
from wechat.contacts import ContactCollector
from wechat.commander import CommandDispatcher
from bridge.ws_client import WebSocketBridge

from app.widgets.status_panel import StatusPanel
from app.widgets.control_panel import ControlPanel
from app.widgets.chat_selector import ChatSelector
from app.widgets.progress_panel import ProgressPanel
from app.widgets.log_viewer import LogViewer
from app.widgets.settings_dialog import SettingsDialog

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
        self._sender_worker: SenderWorker | None = None
        self._contact_worker: ContactWorker | None = None
        self._ws_worker: WebSocketWorker | None = None
        self._db_worker: DBWorker | None = None

        # Connect button signals
        self.control_panel.btn_connect.clicked.connect(self._connect_wechat)
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
        rate_limiter = None
        human_timing = None
        ui_simulator = None
        session_lifecycle = None

        if self.config.human_simulation_enabled:
            from wechat.rate_limiter import RateLimiter
            from wechat.human_timing import HumanTiming
            from wechat.ui_simulator import UISimulator
            from wechat.session_manager import SessionLifecycle

            rate_limiter = RateLimiter(
                hourly_pause=self.config.rate_limit_hourly_max,
                daily_pause=self.config.rate_limit_daily_max,
                min_interval=self.config.min_send_interval,
            )
            human_timing = HumanTiming(self.config.resolved_behavior_profile_path)
            human_timing.load()

            ui_simulator = UISimulator(
                typo_enabled=self.config.typo_enabled,
                typo_rate=self.config.typo_rate,
                mouse_overshoot_enabled=self.config.mouse_overshoot_enabled,
            )
            self.session.ui_simulator = ui_simulator

            if self.config.session_lifecycle_enabled:
                session_lifecycle = SessionLifecycle(
                    human_timing=human_timing,
                    session_min_minutes=self.config.session_duration_min,
                    session_max_minutes=self.config.session_duration_max,
                    break_min_minutes=self.config.break_duration_min,
                    break_max_minutes=self.config.break_duration_max,
                )

        # Create WebSocket bridge first so SenderWorker can report status
        commander = CommandDispatcher(self.session)
        self.ws_bridge = WebSocketBridge(
            ws_url=self.config.orchestrator_ws_url,
            token=self.config.agent_token,
            send_queue=self.send_queue,
            commander=commander,
            agent_id="agent-1",
        )

        self._sender_worker = SenderWorker(
            self.session,
            self.send_queue,
            rate_limiter=rate_limiter,
            human_timing=human_timing,
            human_simulation_enabled=self.config.human_simulation_enabled,
            ui_simulator=ui_simulator if self.config.human_simulation_enabled else None,
            session_lifecycle=session_lifecycle,
            ws_bridge=self.ws_bridge,
        )
        self._sender_worker.message_sent.connect(lambda m: self.log_viewer.append(m, "SUCCESS"))
        self._sender_worker.error_occurred.connect(lambda m: self.log_viewer.append(m, "ERROR"))
        if self.config.human_simulation_enabled:
            self._sender_worker.rate_limited.connect(lambda m: self.log_viewer.append(m, "WARN"))
            self._sender_worker.humanized_delay.connect(
                lambda d: self.log_viewer.append(f"Human delay: {d:.1f}s", "INFO")
            )
            self._sender_worker.idle_action.connect(lambda m: self.log_viewer.append(m, "INFO"))
        self._sender_worker.start()

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

    def _stop_all(self) -> None:
        for worker in (self._sender_worker, self._ws_worker, self._db_worker):
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
        for worker in (self._sender_worker, self._ws_worker, self._db_worker):
            if worker and worker.isRunning():
                worker.stop()
                worker.wait(3000)
        super().closeEvent(event)
