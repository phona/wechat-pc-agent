from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel
from PyQt6.QtCore import Qt


class StatusPanel(QWidget):
    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        self.wechat_indicator = QLabel("\u25cf")
        self.wechat_label = QLabel("WeChat: Disconnected")
        self.orchestrator_indicator = QLabel("\u25cf")
        self.orchestrator_label = QLabel("Orchestrator: Unknown")
        self.db_indicator = QLabel("\u25cf")
        self.db_label = QLabel("DB: Not loaded")
        self.sync_label = QLabel("")

        for indicator in (self.wechat_indicator, self.orchestrator_indicator, self.db_indicator):
            indicator.setStyleSheet("color: #999; font-size: 14px;")

        layout.addWidget(self.wechat_indicator)
        layout.addWidget(self.wechat_label)
        layout.addSpacing(20)
        layout.addWidget(self.orchestrator_indicator)
        layout.addWidget(self.orchestrator_label)
        layout.addSpacing(20)
        layout.addWidget(self.db_indicator)
        layout.addWidget(self.db_label)
        layout.addStretch()
        layout.addWidget(self.sync_label)

    def set_wechat_status(self, connected: bool, user: str = "") -> None:
        if connected:
            self.wechat_indicator.setStyleSheet("color: #22c55e; font-size: 14px;")
            self.wechat_label.setText(f"WeChat: Connected{' (' + user + ')' if user else ''}")
        else:
            self.wechat_indicator.setStyleSheet("color: #ef4444; font-size: 14px;")
            self.wechat_label.setText("WeChat: Disconnected")

    def set_orchestrator_status(self, online: bool) -> None:
        if online:
            self.orchestrator_indicator.setStyleSheet("color: #22c55e; font-size: 14px;")
            self.orchestrator_label.setText("Orchestrator: Online")
        else:
            self.orchestrator_indicator.setStyleSheet("color: #ef4444; font-size: 14px;")
            self.orchestrator_label.setText("Orchestrator: Offline")

    def set_db_status(self, status: str) -> None:
        colors = {
            "decrypting": "#eab308",
            "ready": "#22c55e",
            "error": "#ef4444",
            "idle": "#999",
        }
        self.db_indicator.setStyleSheet(f"color: {colors.get(status, '#999')}; font-size: 14px;")
        labels = {
            "decrypting": "DB: Decrypting...",
            "ready": "DB: Ready",
            "error": "DB: Error",
            "idle": "DB: Not loaded",
        }
        self.db_label.setText(labels.get(status, f"DB: {status}"))

    def set_sync_info(self, text: str) -> None:
        self.sync_label.setText(text)
