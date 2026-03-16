import asyncio
import logging
from PyQt6.QtCore import QThread, pyqtSignal

from bridge.ws_client import WebSocketBridge

logger = logging.getLogger(__name__)


class WebSocketWorker(QThread):
    """Runs the WebSocket bridge in a background thread with its own event loop."""

    connected = pyqtSignal()
    disconnected = pyqtSignal()
    log_message = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, bridge: WebSocketBridge):
        super().__init__()
        self.bridge = bridge
        self._loop: asyncio.AbstractEventLoop | None = None

    def stop(self):
        self.bridge.stop()
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

    def run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self.bridge._loop = self._loop
        self.log_message.emit("WebSocket bridge starting")

        try:
            self._loop.run_until_complete(self.bridge.run())
        except Exception as e:
            self.error_occurred.emit(f"WebSocket bridge error: {e}")
            logger.error("WebSocket bridge error: %s", e)
        finally:
            self._loop.close()
            self.log_message.emit("WebSocket bridge stopped")
