"""
Shared fixtures and module-level mocks for tests.

Stubs PyQt6 so worker tests can import modules that depend on it
without actually having PyQt6 installed.
"""
import sys
from unittest.mock import MagicMock


def _stub_pyqt6():
    """Insert fake PyQt6 modules into sys.modules before any worker import."""
    if "PyQt6" in sys.modules:
        return  # already present (real or stub)

    # Build a minimal mock tree for PyQt6.QtCore
    qt_core = MagicMock()

    # QThread needs to be a real-ish class so workers can subclass it
    class FakeQThread:
        def __init__(self, *a, **kw):
            self._running = False

        def start(self):
            pass

    qt_core.QThread = FakeQThread

    # pyqtSignal returns a descriptor-like mock
    qt_core.pyqtSignal = lambda *args, **kwargs: MagicMock()

    pyqt6 = MagicMock()
    pyqt6.QtCore = qt_core

    sys.modules["PyQt6"] = pyqt6
    sys.modules["PyQt6.QtCore"] = qt_core


# Run stub immediately at conftest load time (before test collection imports)
_stub_pyqt6()
