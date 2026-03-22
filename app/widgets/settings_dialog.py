from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QLabel, QLineEdit, QMessageBox, QSpinBox,
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
        self.orchestrator_ws_url = QLineEdit(config.orchestrator_ws_url)

        self.agent_token = QLineEdit(config.agent_token)
        self.agent_token.setEchoMode(QLineEdit.EchoMode.Password)

        self.max_history_days = QSpinBox()
        self.max_history_days.setRange(1, 365)
        self.max_history_days.setValue(config.max_history_days)
        self.max_history_days.setSuffix(" days")

        layout.addRow("Orchestrator URL:", self.orchestrator_url)
        layout.addRow("WebSocket URL:", self.orchestrator_ws_url)
        layout.addRow("API Token:", self.agent_token)
        layout.addRow("Max History:", self.max_history_days)

        # --- API Settings (shared by VLM + OCR) ---
        api_sep = QLabel("")
        api_sep.setStyleSheet("border-top: 1px solid #ccc; margin: 8px 0;")
        layout.addRow(api_sep)

        self.api_url = QLineEdit(config.api_url)
        self.api_key = QLineEdit(config.api_key)
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)

        layout.addRow("API URL:", self.api_url)
        layout.addRow("API Key:", self.api_key)

        # --- VLM Vision ---
        vlm_sep = QLabel("")
        vlm_sep.setStyleSheet("border-top: 1px solid #ccc; margin: 8px 0;")
        layout.addRow(vlm_sep)

        self.vlm_model = QLineEdit(config.vlm_model)

        self.vlm_timeout = QDoubleSpinBox()
        self.vlm_timeout.setRange(5.0, 120.0)
        self.vlm_timeout.setValue(config.vlm_timeout)
        self.vlm_timeout.setSuffix(" s")

        self.pixel_diff_threshold = QDoubleSpinBox()
        self.pixel_diff_threshold.setRange(0.005, 0.5)
        self.pixel_diff_threshold.setDecimals(3)
        self.pixel_diff_threshold.setSingleStep(0.005)
        self.pixel_diff_threshold.setValue(config.pixel_diff_threshold)

        self.pixel_diff_interval = QDoubleSpinBox()
        self.pixel_diff_interval.setRange(0.5, 10.0)
        self.pixel_diff_interval.setValue(config.pixel_diff_interval)
        self.pixel_diff_interval.setSuffix(" s")

        layout.addRow("VLM Model:", self.vlm_model)
        layout.addRow("VLM Timeout:", self.vlm_timeout)
        layout.addRow("Pixel Diff Threshold:", self.pixel_diff_threshold)
        layout.addRow("Pixel Diff Interval:", self.pixel_diff_interval)

        # --- Light Model (Layer 2) ---
        light_sep = QLabel("")
        light_sep.setStyleSheet("border-top: 1px solid #ccc; margin: 8px 0;")
        layout.addRow(light_sep)

        self.light_model = QComboBox()
        self.light_model.setEditable(True)
        self.light_model.addItems([
            "",
            "deepseek-ai/DeepSeek-OCR",
            "PaddlePaddle/PaddleOCR-VL",
        ])
        if config.light_model:
            idx = self.light_model.findText(config.light_model)
            if idx >= 0:
                self.light_model.setCurrentIndex(idx)
            else:
                self.light_model.setCurrentText(config.light_model)

        self.light_timeout = QDoubleSpinBox()
        self.light_timeout.setRange(1.0, 60.0)
        self.light_timeout.setValue(config.light_timeout)
        self.light_timeout.setSuffix(" s")

        self.light_min_confidence = QDoubleSpinBox()
        self.light_min_confidence.setRange(0.1, 1.0)
        self.light_min_confidence.setDecimals(2)
        self.light_min_confidence.setSingleStep(0.05)
        self.light_min_confidence.setValue(config.light_min_confidence)

        layout.addRow("Light Model:", self.light_model)
        layout.addRow("Light Timeout:", self.light_timeout)
        layout.addRow("Light Min Confidence:", self.light_min_confidence)

        # --- Resilience / Circuit Breaker ---
        res_sep = QLabel("")
        res_sep.setStyleSheet("border-top: 1px solid #ccc; margin: 8px 0;")
        layout.addRow(res_sep)

        self.light_breaker_threshold = QSpinBox()
        self.light_breaker_threshold.setRange(1, 50)
        self.light_breaker_threshold.setValue(config.light_breaker_threshold)
        self.light_breaker_threshold.setSuffix(" failures")

        self.light_breaker_cooldown = QDoubleSpinBox()
        self.light_breaker_cooldown.setRange(10.0, 3600.0)
        self.light_breaker_cooldown.setValue(config.light_breaker_cooldown)
        self.light_breaker_cooldown.setSuffix(" s")

        self.vlm_breaker_threshold = QSpinBox()
        self.vlm_breaker_threshold.setRange(1, 50)
        self.vlm_breaker_threshold.setValue(config.vlm_breaker_threshold)
        self.vlm_breaker_threshold.setSuffix(" failures")

        self.vlm_breaker_cooldown = QDoubleSpinBox()
        self.vlm_breaker_cooldown.setRange(10.0, 7200.0)
        self.vlm_breaker_cooldown.setValue(config.vlm_breaker_cooldown)
        self.vlm_breaker_cooldown.setSuffix(" s")

        self.max_scroll_rounds = QSpinBox()
        self.max_scroll_rounds.setRange(0, 10)
        self.max_scroll_rounds.setValue(config.max_scroll_rounds)

        layout.addRow("Resilience:", QLabel(""))
        layout.addRow("Light Breaker Threshold:", self.light_breaker_threshold)
        layout.addRow("Light Breaker Cooldown:", self.light_breaker_cooldown)
        layout.addRow("VLM Breaker Threshold:", self.vlm_breaker_threshold)
        layout.addRow("VLM Breaker Cooldown:", self.vlm_breaker_cooldown)
        layout.addRow("Max Scroll Rounds:", self.max_scroll_rounds)

        # --- Human Simulation ---
        separator = QLabel("")
        separator.setStyleSheet("border-top: 1px solid #ccc; margin: 8px 0;")
        layout.addRow(separator)

        self.human_simulation_enabled = QCheckBox("Enable human simulation")
        self.human_simulation_enabled.setChecked(config.human_simulation_enabled)

        self.rate_limit_hourly_max = QSpinBox()
        self.rate_limit_hourly_max.setRange(10, 500)
        self.rate_limit_hourly_max.setValue(config.rate_limit_hourly_max)
        self.rate_limit_hourly_max.setSuffix(" /hr")

        self.rate_limit_daily_max = QSpinBox()
        self.rate_limit_daily_max.setRange(50, 1000)
        self.rate_limit_daily_max.setValue(config.rate_limit_daily_max)
        self.rate_limit_daily_max.setSuffix(" /day")

        self.min_send_interval = QDoubleSpinBox()
        self.min_send_interval.setRange(1.0, 30.0)
        self.min_send_interval.setValue(config.min_send_interval)
        self.min_send_interval.setSuffix(" s")

        self.behavior_profile_path = QLineEdit(config.behavior_profile_path)

        layout.addRow("Human Simulation:", self.human_simulation_enabled)
        layout.addRow("Hourly Max:", self.rate_limit_hourly_max)
        layout.addRow("Daily Max:", self.rate_limit_daily_max)
        layout.addRow("Min Interval:", self.min_send_interval)
        layout.addRow("Behavior Profile:", self.behavior_profile_path)

        # --- Advanced Simulation ---
        sep2 = QLabel("")
        sep2.setStyleSheet("border-top: 1px solid #ccc; margin: 8px 0;")
        layout.addRow(sep2)

        self.typo_enabled = QCheckBox("Typing errors")
        self.typo_enabled.setChecked(config.typo_enabled)

        self.mouse_overshoot_enabled = QCheckBox("Mouse overshoot")
        self.mouse_overshoot_enabled.setChecked(config.mouse_overshoot_enabled)

        self.idle_behaviors_enabled = QCheckBox("Idle behaviors")
        self.idle_behaviors_enabled.setChecked(config.idle_behaviors_enabled)

        self.session_lifecycle_enabled = QCheckBox("Session lifecycle")
        self.session_lifecycle_enabled.setChecked(config.session_lifecycle_enabled)

        self.reading_simulation_enabled = QCheckBox("Reading simulation")
        self.reading_simulation_enabled.setChecked(config.reading_simulation_enabled)

        self.session_duration_min = QSpinBox()
        self.session_duration_min.setRange(10, 180)
        self.session_duration_min.setValue(config.session_duration_min)
        self.session_duration_min.setSuffix(" min")

        self.session_duration_max = QSpinBox()
        self.session_duration_max.setRange(10, 180)
        self.session_duration_max.setValue(config.session_duration_max)
        self.session_duration_max.setSuffix(" min")

        self.break_duration_min = QSpinBox()
        self.break_duration_min.setRange(1, 60)
        self.break_duration_min.setValue(config.break_duration_min)
        self.break_duration_min.setSuffix(" min")

        self.break_duration_max = QSpinBox()
        self.break_duration_max.setRange(1, 60)
        self.break_duration_max.setValue(config.break_duration_max)
        self.break_duration_max.setSuffix(" min")

        layout.addRow("Advanced Simulation:", QLabel(""))
        layout.addRow("", self.typo_enabled)
        layout.addRow("", self.mouse_overshoot_enabled)
        layout.addRow("", self.idle_behaviors_enabled)
        layout.addRow("", self.session_lifecycle_enabled)
        layout.addRow("", self.reading_simulation_enabled)
        layout.addRow("Session Min:", self.session_duration_min)
        layout.addRow("Session Max:", self.session_duration_max)
        layout.addRow("Break Min:", self.break_duration_min)
        layout.addRow("Break Max:", self.break_duration_max)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _save(self) -> None:
        try:
            self.config.orchestrator_url = self.orchestrator_url.text().strip()
            self.config.orchestrator_ws_url = self.orchestrator_ws_url.text().strip()
            self.config.agent_token = self.agent_token.text()
            self.config.max_history_days = self.max_history_days.value()
            self.config.api_url = self.api_url.text().strip()
            self.config.api_key = self.api_key.text()
            self.config.vlm_model = self.vlm_model.text().strip()
            self.config.vlm_timeout = self.vlm_timeout.value()
            self.config.pixel_diff_threshold = self.pixel_diff_threshold.value()
            self.config.pixel_diff_interval = self.pixel_diff_interval.value()
            self.config.light_model = self.light_model.currentText().strip()
            self.config.light_timeout = self.light_timeout.value()
            self.config.light_min_confidence = self.light_min_confidence.value()
            self.config.light_breaker_threshold = self.light_breaker_threshold.value()
            self.config.light_breaker_cooldown = self.light_breaker_cooldown.value()
            self.config.vlm_breaker_threshold = self.vlm_breaker_threshold.value()
            self.config.vlm_breaker_cooldown = self.vlm_breaker_cooldown.value()
            self.config.max_scroll_rounds = self.max_scroll_rounds.value()
            self.config.human_simulation_enabled = self.human_simulation_enabled.isChecked()
            self.config.rate_limit_hourly_max = self.rate_limit_hourly_max.value()
            self.config.rate_limit_daily_max = self.rate_limit_daily_max.value()
            self.config.min_send_interval = self.min_send_interval.value()
            self.config.behavior_profile_path = self.behavior_profile_path.text().strip()
            self.config.typo_enabled = self.typo_enabled.isChecked()
            self.config.mouse_overshoot_enabled = self.mouse_overshoot_enabled.isChecked()
            self.config.idle_behaviors_enabled = self.idle_behaviors_enabled.isChecked()
            self.config.session_lifecycle_enabled = self.session_lifecycle_enabled.isChecked()
            self.config.reading_simulation_enabled = self.reading_simulation_enabled.isChecked()
            self.config.session_duration_min = self.session_duration_min.value()
            self.config.session_duration_max = self.session_duration_max.value()
            self.config.break_duration_min = self.break_duration_min.value()
            self.config.break_duration_max = self.break_duration_max.value()
            self.config.save()
        except Exception as exc:
            QMessageBox.critical(self, "Settings Error", f"Failed to save settings: {exc}")
            return

        self.accept()
