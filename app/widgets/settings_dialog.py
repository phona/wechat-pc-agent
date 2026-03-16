from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QSpinBox, QDoubleSpinBox,
    QDialogButtonBox, QLabel,
)

from config import AppConfig


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(400)
        self.config = config

        layout = QFormLayout(self)

        self.orchestrator_url = QLineEdit(config.orchestrator_url)
        self.agent_port = QSpinBox()
        self.agent_port.setRange(1024, 65535)
        self.agent_port.setValue(config.agent_port)

        self.agent_token = QLineEdit(config.agent_token)
        self.agent_token.setEchoMode(QLineEdit.EchoMode.Password)

        self.poll_interval = QDoubleSpinBox()
        self.poll_interval.setRange(0.1, 30.0)
        self.poll_interval.setValue(config.poll_interval)
        self.poll_interval.setSuffix(" s")

        self.scroll_delay = QSpinBox()
        self.scroll_delay.setRange(200, 5000)
        self.scroll_delay.setValue(config.scroll_delay_ms)
        self.scroll_delay.setSuffix(" ms")

        self.max_history_days = QSpinBox()
        self.max_history_days.setRange(1, 365)
        self.max_history_days.setValue(config.max_history_days)
        self.max_history_days.setSuffix(" days")

        layout.addRow("Orchestrator URL:", self.orchestrator_url)
        layout.addRow("Agent Port:", self.agent_port)
        layout.addRow("API Token:", self.agent_token)
        layout.addRow("Poll Interval:", self.poll_interval)
        layout.addRow("Scroll Delay:", self.scroll_delay)
        layout.addRow("Max History:", self.max_history_days)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _save(self) -> None:
        self.config.orchestrator_url = self.orchestrator_url.text()
        self.config.agent_port = self.agent_port.value()
        self.config.agent_token = self.agent_token.text()
        self.config.poll_interval = self.poll_interval.value()
        self.config.scroll_delay_ms = self.scroll_delay.value()
        self.config.max_history_days = self.max_history_days.value()
        self.config.save()
        self.accept()
