import importlib
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from config import AppConfig


class _Signal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)


class _Widget:
    def __init__(self, *args, **kwargs):
        pass


class _QDialog(_Widget):
    def __init__(self, parent=None):
        super().__init__()
        self.parent = parent
        self.accepted = False

    def setWindowTitle(self, title):
        self.title = title

    def setMinimumWidth(self, width):
        self.minimum_width = width

    def accept(self):
        self.accepted = True

    def reject(self):
        self.accepted = False


class _QFormLayout:
    def __init__(self, parent=None):
        self.parent = parent
        self.rows = []

    def addRow(self, *args):
        self.rows.append(args)


class _QLineEdit(_Widget):
    class EchoMode:
        Password = "password"

    def __init__(self, text=""):
        self._text = text
        self.echo_mode = None

    def setEchoMode(self, mode):
        self.echo_mode = mode

    def text(self):
        return self._text

    def setText(self, value):
        self._text = value


class _QSpinBox(_Widget):
    def __init__(self):
        self._value = 0
        self._range = (0, 0)
        self._suffix = ""

    def setRange(self, low, high):
        self._range = (low, high)

    def setValue(self, value):
        self._value = value

    def value(self):
        return self._value

    def setSuffix(self, suffix):
        self._suffix = suffix


class _QDoubleSpinBox(_QSpinBox):
    pass


class _QDialogButtonBox(_Widget):
    class StandardButton:
        Save = 1
        Cancel = 2

    def __init__(self, buttons):
        self.buttons = buttons
        self.accepted = _Signal()
        self.rejected = _Signal()


class _QMessageBox:
    critical_calls = []

    @classmethod
    def critical(cls, *args):
        cls.critical_calls.append(args)


def _install_qtwidgets_stub():
    qtwidgets = ModuleType("PyQt6.QtWidgets")
    qtwidgets.QDialog = _QDialog
    qtwidgets.QDialogButtonBox = _QDialogButtonBox
    qtwidgets.QDoubleSpinBox = _QDoubleSpinBox
    qtwidgets.QFormLayout = _QFormLayout
    qtwidgets.QLineEdit = _QLineEdit
    qtwidgets.QMessageBox = _QMessageBox
    qtwidgets.QSpinBox = _QSpinBox

    pyqt6 = ModuleType("PyQt6")
    pyqt6.QtWidgets = qtwidgets
    return pyqt6, qtwidgets


def _load_settings_dialog():
    pyqt6, qtwidgets = _install_qtwidgets_stub()
    with patch.dict(sys.modules, {"PyQt6": pyqt6, "PyQt6.QtWidgets": qtwidgets}):
        sys.modules.pop("app.widgets.settings_dialog", None)
        return importlib.import_module("app.widgets.settings_dialog")


def test_settings_dialog_uses_current_config_fields(tmp_path):
    module = _load_settings_dialog()
    cfg = AppConfig(
        orchestrator_url="http://example.test",
        orchestrator_ws_url="ws://example.test/ws/agent",
        agent_token="token-1",
        poll_interval=1.5,
        scroll_delay_ms=900,
        max_history_days=10,
        wal_poll_interval_ms=250,
    )
    config_file = tmp_path / "config.json"

    with patch("config.CONFIG_FILE", config_file):
        dialog = module.SettingsDialog(cfg)
        dialog.orchestrator_url.setText("http://changed.test")
        dialog.orchestrator_ws_url.setText("ws://changed.test/ws/agent")
        dialog.agent_token.setText("token-2")
        dialog.poll_interval.setValue(2.0)
        dialog.scroll_delay.setValue(700)
        dialog.max_history_days.setValue(45)
        dialog.wal_poll_interval.setValue(125)
        dialog._save()

    assert dialog.accepted is True
    assert cfg.orchestrator_url == "http://changed.test"
    assert cfg.orchestrator_ws_url == "ws://changed.test/ws/agent"
    assert cfg.agent_token == "token-2"
    assert cfg.poll_interval == 2.0
    assert cfg.scroll_delay_ms == 700
    assert cfg.max_history_days == 45
    assert cfg.wal_poll_interval_ms == 125
    assert config_file.exists()
