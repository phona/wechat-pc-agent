import logging
import random
import time
from queue import Queue, Empty
from PyQt6.QtCore import QThread, pyqtSignal

from wechat.session import WeChatSession

logger = logging.getLogger(__name__)


class SenderWorker(QThread):
    """Consumes the send queue and dispatches messages via WeChatSession."""

    message_sent = pyqtSignal(str)    # log message
    error_occurred = pyqtSignal(str)
    rate_limited = pyqtSignal(str)
    humanized_delay = pyqtSignal(float)
    idle_action = pyqtSignal(str)

    def __init__(
        self,
        session: WeChatSession,
        send_queue: Queue,
        max_retries: int = 3,
        rate_limiter=None,
        human_timing=None,
        human_simulation_enabled: bool = False,
        ui_simulator=None,
        session_lifecycle=None,
        ws_bridge=None,
    ):
        super().__init__()
        self.session = session
        self.send_queue = send_queue
        self.max_retries = max_retries
        self._rate_limiter = rate_limiter
        self._human_timing = human_timing
        self._human_simulation_enabled = human_simulation_enabled
        self._ui_simulator = ui_simulator
        self._session_lifecycle = session_lifecycle
        self._ws_bridge = ws_bridge
        self._running = False
        self._deferred_items: list[tuple[float, dict]] = []  # (ready_time, item)
        self._state = "idle"
        self._last_send_ts = 0.0
        self._last_error = ""
        self._start_ts = 0.0

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        self._running = True
        self._start_ts = time.time()
        self.message_sent.emit("Sender worker started")
        self._report_status("active")

        while self._running:
            # Session lifecycle gate
            if self._session_lifecycle and not self._session_lifecycle.should_process():
                state = self._session_lifecycle.get_state()
                wait = min(self._session_lifecycle.time_until_active(), 30.0)
                self.idle_action.emit(f"Session {state}, waiting {wait:.0f}s")
                self._report_status(state)
                self._interruptible_sleep(wait)
                continue

            # Check for deferred items that are ready
            item = self._pop_deferred_item()

            # Get from queue if no deferred item ready
            if item is None:
                try:
                    item = self.send_queue.get(timeout=1.0)
                except Empty:
                    # Queue empty — maybe do idle action
                    if self._ui_simulator and self._session_lifecycle and self._session_lifecycle.should_idle():
                        self._report_status("idle")
                        self._do_idle_action()
                    continue

            chat_name = item.get("chat_name", "")
            content = item.get("content", "")
            msgtype = item.get("msgtype", "text")

            if not chat_name or not content:
                continue

            # Rate limiting: hold the item locally and wait until allowed
            self._report_status("rate_check")
            if self._rate_limiter:
                while self._running:
                    can, reason = self._rate_limiter.can_send()
                    if can:
                        break
                    cooldown = self._rate_limiter.get_required_cooldown()
                    self.rate_limited.emit(f"{reason} (cooling down {cooldown:.0f}s)")
                    if not self._interruptible_sleep(min(cooldown, 10.0)):
                        break
                if not self._running:
                    break

            # Reading simulation: simulate reading the incoming message
            if self._ui_simulator and self._human_simulation_enabled:
                incoming_len = item.get("incoming_msg_length", 0)
                if incoming_len > 0:
                    try:
                        import pyautogui
                        self._ui_simulator.simulate_reading(incoming_len, pyautogui=pyautogui)
                    except ImportError:
                        self._ui_simulator.simulate_reading(incoming_len)

            # Human timing delay
            if self._human_simulation_enabled and self._human_timing:
                delay = self._human_timing.sample_reply_delay(len(content))

                # Interaction variety: 8% distraction delay
                if random.random() < 0.08:
                    extra = random.uniform(30, 180)
                    delay += extra
                    self.idle_action.emit(f"Distracted for {extra:.0f}s extra")

                self.humanized_delay.emit(delay)
                if not self._interruptible_sleep(delay):
                    break

            # Interaction variety: 3% read-and-leave (defer the item)
            if self._human_simulation_enabled and random.random() < 0.03:
                defer_seconds = random.uniform(60, 300)
                self._deferred_items.append((time.time() + defer_seconds, item))
                self.idle_action.emit(f"Read-and-leave: deferred {chat_name} for {defer_seconds:.0f}s")
                continue

            self._report_status("sending")
            self._send_item(chat_name, content, msgtype)

        self._report_status("stopped")
        self.message_sent.emit("Sender worker stopped")

    def _send_item(self, chat_name: str, content: str, msgtype: str) -> None:
        """Send a single item with retries."""
        success = False
        for attempt in range(1, self.max_retries + 1):
            if not self._running:
                break

            if msgtype == "text":
                if self._human_simulation_enabled:
                    success = self.session.send_text_human(chat_name, content)
                else:
                    success = self.session.send_text(chat_name, content)
            else:
                success = self.session.send_file(chat_name, content)

            if success:
                if self._rate_limiter:
                    self._rate_limiter.record_send()
                if self._session_lifecycle:
                    self._session_lifecycle.record_send()
                self._last_send_ts = time.time()
                self._last_error = ""
                self.message_sent.emit(f"Sent to {chat_name}: {content[:50]}...")
                self._report_status("active")
                break

            err = f"Send attempt {attempt}/{self.max_retries} failed for {chat_name}"
            self._last_error = err
            self.error_occurred.emit(err)
            if not self._interruptible_sleep(2.0):
                break

        if not success and self._running:
            err = f"Failed to send to {chat_name} after {self.max_retries} retries"
            self._last_error = err
            self.error_occurred.emit(err)
            self._report_status("error")

    def _pop_deferred_item(self) -> dict | None:
        """Return a deferred item if one is ready, else None."""
        now = time.time()
        for i, (ready_time, item) in enumerate(self._deferred_items):
            if now >= ready_time:
                self._deferred_items.pop(i)
                return item
        return None

    def _do_idle_action(self) -> None:
        """Perform an idle action if pyautogui is available."""
        try:
            import pyautogui
            window_rect = self._get_window_rect()
            self._ui_simulator.perform_idle_action(pyautogui, window_rect=window_rect)
            self.idle_action.emit("Performed idle action")
        except (ImportError, Exception) as e:
            logger.debug("Idle action skipped: %s", e)

    def _get_window_rect(self) -> tuple | None:
        """Try to get the WeChat window rectangle."""
        return self.session.get_window_rect()

    def _report_status(self, state: str) -> None:
        """Report current agent status to orchestrator via WebSocket bridge."""
        self._state = state
        if not self._ws_bridge:
            return
        status = {
            "state": state,
            "queue_size": self.send_queue.qsize(),
            "last_send_ts": self._last_send_ts,
            "uptime": time.time() - self._start_ts,
            "error": self._last_error,
            "deferred_count": len(self._deferred_items),
        }
        if self._rate_limiter:
            stats = self._rate_limiter.get_stats()
            status["hourly_sent"] = stats.get("hourly_count", 0)
            status["daily_sent"] = stats.get("daily_count", 0)
        if self._session_lifecycle:
            status["lifecycle_state"] = self._session_lifecycle.get_state()
        try:
            self._ws_bridge.report_status(status)
        except Exception:
            pass

    def _interruptible_sleep(self, duration: float) -> bool:
        """Sleep in 1-second chunks, checking _running. Returns False if interrupted."""
        waited = 0.0
        while waited < duration and self._running:
            chunk = min(1.0, duration - waited)
            time.sleep(chunk)
            waited += chunk
        return self._running
