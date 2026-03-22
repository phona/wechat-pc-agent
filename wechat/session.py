"""WeChat session management via VLM vision + keyboard/mouse simulation.

Replaces wxauto with a version-agnostic approach:
- Win32 API for window management
- VLM for UI element recognition
- pyautogui for keyboard/mouse interaction
"""

import logging
import math
import platform
import random
import subprocess
import sys
import threading
import time

logger = logging.getLogger(__name__)


class WeChatSession:
    """Manages WeChat window interaction via VLM vision + keyboard/mouse simulation."""

    def __init__(self):
        self._window = None  # WeChatWindow
        self._vision = None  # VisionPerception
        self._connected = False
        self.last_connect_error = ""
        self.last_connect_diagnostics: list[str] = []
        self._last_process_probe: bool | None = None
        self.ui_simulator = None  # Optional UISimulator for advanced human sim
        self.window_lock = threading.Lock()

    def set_vision(self, window, vision) -> None:
        """Set the window and vision components (created by MainWindow)."""
        self._window = window
        self._vision = vision

    def connect(self) -> bool:
        """Attach to the running WeChat PC window via Win32 + VLM calibration."""
        self._connected = False
        self.last_connect_error = ""
        self.last_connect_diagnostics = []
        self._last_process_probe = None
        self._record_connect_diag(f"Starting attach on {platform.platform()}")
        self._record_connect_diag(f"Python {platform.python_version()} at {sys.executable}")
        self._probe_admin_status()
        self._probe_wechat_process()

        if not self._window:
            self.last_connect_error = "Window manager not initialized"
            self._record_connect_diag(self.last_connect_error)
            self._append_connect_hints()
            return False

        # Step 1: Find the WeChat window
        if not self._window.find():
            self.last_connect_error = "WeChat window not found"
            self._record_connect_diag(self.last_connect_error)
            self._append_connect_hints()
            return False
        self._record_connect_diag(f"Found WeChat window: hwnd={self._window.hwnd}")

        # Step 2: Activate and maximize
        if not self._window.activate():
            self.last_connect_error = "Failed to activate WeChat window"
            self._record_connect_diag(self.last_connect_error)
            return False
        self._record_connect_diag("Window activated")

        if not self._window.maximize():
            self._record_connect_diag("Warning: maximize failed, continuing anyway")

        # Step 3: VLM calibration
        if self._vision:
            try:
                state = self._vision.calibrate()
                self._record_connect_diag(
                    f"VLM calibration: {len(state.elements)} elements, "
                    f"{len(state.visible_chats)} chats"
                )
            except Exception as e:
                self.last_connect_error = f"VLM calibration failed: {e}"
                self._record_connect_diag(self.last_connect_error)
                logger.exception("VLM calibration failed")
                return False
        else:
            self._record_connect_diag("No VLM configured, skipping calibration")

        self._connected = True
        self._record_connect_diag("Connected successfully")
        logger.info("Connected to WeChat PC window")
        return True

    def is_ready(self) -> bool:
        """Check if WeChat window is visible and responsive."""
        if not self._connected or not self._window:
            return False
        return self._window.is_visible()

    def get_session_list(self) -> list[str]:
        """Get list of visible chat names from VLM state."""
        if not self._vision:
            return []
        return [c.name for c in self._vision.state.visible_chats]

    def get_window_rect(self) -> tuple[int, int, int, int] | None:
        """Get the WeChat window rectangle."""
        if not self._window:
            return None
        try:
            return self._window.get_rect()
        except Exception:
            return None

    def send_text(self, chat_name: str, message: str) -> bool:
        """Send a text message by navigating to the chat and typing."""
        return self.send_text_human(chat_name, message)

    def send_text_human(self, chat_name: str, message: str) -> bool:
        """Send text via UI simulation: search chat, click, type/paste, Enter."""
        try:
            import pyautogui
            import pyperclip
        except ImportError:
            logger.error("pyautogui/pyperclip not available")
            return False

        if not self._vision:
            logger.error("Vision not initialized")
            return False

        message_entered = False
        try:
            # Step 1: Navigate to the chat
            if not self._navigate_to_chat(chat_name, pyautogui, pyperclip):
                logger.error("Failed to navigate to chat: %s", chat_name)
                return False

            # Step 2: Click the input box
            input_pos = self._vision.get_element_center("input_box")
            if not input_pos:
                logger.error("Input box position not calibrated")
                return False

            if self.ui_simulator:
                self.ui_simulator.bezier_move_click(input_pos[0], input_pos[1], pyautogui)
            else:
                self._bezier_move_click(input_pos[0], input_pos[1], pyautogui)
            time.sleep(random.uniform(0.05, 0.15))

            # Step 3: Type or paste the message
            if self.ui_simulator:
                if message.isascii():
                    self.ui_simulator.type_text(message, pyautogui)
                else:
                    self.ui_simulator.paste_text(message, pyautogui)
            elif message.isascii():
                self._type_characters(message, pyautogui)
            else:
                pyperclip.copy(message)
                time.sleep(random.uniform(0.1, 0.3))
                pyautogui.hotkey("ctrl", "v")
                time.sleep(random.uniform(0.1, 0.2))
            message_entered = True

            # Step 4: Press Enter to send
            time.sleep(random.uniform(0.1, 0.4))
            pyautogui.press("enter")
            logger.info("Sent message (vision) to %s", chat_name)
            return True
        except Exception as e:
            logger.error("Send failed for %s: %s", chat_name, e)
            if message_entered:
                return False
            return False

    def open_chat(self, chat_name: str) -> bool:
        """Open a chat by searching and clicking."""
        try:
            import pyautogui
            import pyperclip
        except ImportError:
            return False
        return self._navigate_to_chat(chat_name, pyautogui, pyperclip)

    def search_contact(self, name: str) -> list[str]:
        """Search for contacts — returns visible chat names matching the query."""
        if not self._vision:
            return []
        chats = self._vision.state.visible_chats
        return [c.name for c in chats if name.lower() in c.name.lower()]

    def send_file(self, chat_name: str, file_path: str) -> bool:
        """Send a file via clipboard paste (Ctrl+V)."""
        try:
            import pyautogui
            import pyperclip
        except ImportError:
            return False

        try:
            if not self._navigate_to_chat(chat_name, pyautogui, pyperclip):
                return False

            # Copy file path to clipboard and paste
            # On Windows, we can use PowerShell to set the clipboard to a file
            if sys.platform == "win32":
                subprocess.run(
                    ["powershell", "-command",
                     f'Set-Clipboard -Path "{file_path}"'],
                    check=True, timeout=5,
                )
                time.sleep(0.2)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.5)
                pyautogui.press("enter")
                logger.info("Sent file to %s: %s", chat_name, file_path)
                return True
            else:
                logger.error("File send only supported on Windows")
                return False
        except Exception as e:
            logger.error("Failed to send file to %s: %s", chat_name, e)
            return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _navigate_to_chat(self, chat_name: str, pyautogui, pyperclip) -> bool:
        """Navigate to a chat by clicking search box, typing name, clicking result."""
        search_pos = self._vision.get_element_center("search_box") if self._vision else None
        if not search_pos:
            logger.error("Search box position not calibrated")
            return False

        # Click search box
        if self.ui_simulator:
            self.ui_simulator.bezier_move_click(search_pos[0], search_pos[1], pyautogui)
        else:
            self._bezier_move_click(search_pos[0], search_pos[1], pyautogui)
        time.sleep(random.uniform(0.2, 0.4))

        # Clear and type contact name
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.05)
        if chat_name.isascii():
            pyautogui.typewrite(chat_name, interval=0.05)
        else:
            pyperclip.copy(chat_name)
            pyautogui.hotkey("ctrl", "v")
        time.sleep(random.uniform(0.5, 0.8))

        # Click first search result (below search box)
        search_el = self._vision.state.elements.get("search_box") if self._vision else None
        if search_el:
            result_x = search_pos[0]
            result_y = search_pos[1] + search_el.h // 2 + 40  # First result offset
            if self.ui_simulator:
                self.ui_simulator.bezier_move_click(result_x, result_y, pyautogui)
            else:
                self._bezier_move_click(result_x, result_y, pyautogui)
        else:
            # Fallback: press Enter to select first result
            pyautogui.press("enter")
        time.sleep(random.uniform(0.3, 0.5))

        # Close search overlay
        pyautogui.press("escape")
        time.sleep(0.2)
        return True

    def _bezier_move_click(self, x: int, y: int, pyautogui) -> None:
        """Move mouse along a cubic Bézier curve to (x, y) and click."""
        start_x, start_y = pyautogui.position()
        dx = x - start_x
        dy = y - start_y
        distance = math.hypot(dx, dy)
        steps = max(10, int(distance / 5))

        perp_x, perp_y = -dy, dx
        norm = math.hypot(perp_x, perp_y) or 1.0
        perp_x, perp_y = perp_x / norm, perp_y / norm

        offset1 = random.gauss(0, 30)
        offset2 = random.gauss(0, 30)
        cp1_x = start_x + dx * 0.33 + perp_x * offset1
        cp1_y = start_y + dy * 0.33 + perp_y * offset1
        cp2_x = start_x + dx * 0.66 + perp_x * offset2
        cp2_y = start_y + dy * 0.66 + perp_y * offset2

        for i in range(1, steps + 1):
            t = i / steps
            inv = 1 - t
            bx = inv**3 * start_x + 3 * inv**2 * t * cp1_x + 3 * inv * t**2 * cp2_x + t**3 * x
            by = inv**3 * start_y + 3 * inv**2 * t * cp1_y + 3 * inv * t**2 * cp2_y + t**3 * y
            pyautogui.moveTo(int(bx), int(by), _pause=False)
            time.sleep(random.uniform(0.003, 0.012))

        pyautogui.click(x, y)

    @staticmethod
    def _type_characters(text: str, pyautogui) -> None:
        """Type text character by character with human-like delays."""
        for char in text:
            pyautogui.write(char)
            if random.random() < 0.05:
                time.sleep(random.uniform(0.2, 0.5))
            else:
                time.sleep(random.uniform(0.03, 0.15))

    # ------------------------------------------------------------------
    # Diagnostics (kept from original)
    # ------------------------------------------------------------------

    def _record_connect_diag(self, message: str) -> None:
        self.last_connect_diagnostics.append(message)
        logger.info("WeChat connect: %s", message)

    def _probe_admin_status(self) -> None:
        if sys.platform != "win32":
            self._record_connect_diag("Non-Windows runtime detected; desktop attach is Windows-only")
            return
        try:
            import ctypes
            is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
            self._record_connect_diag(f"Running as administrator: {'yes' if is_admin else 'no'}")
        except Exception as e:
            self._record_connect_diag(f"Admin privilege probe failed: {e}")

    def _probe_wechat_process(self) -> None:
        if sys.platform != "win32":
            return
        process_names = ["WeChat.exe", "Weixin.exe"]
        found = []
        for proc_name in process_names:
            try:
                result = subprocess.run(
                    ["tasklist", "/FI", f"IMAGENAME eq {proc_name}", "/FO", "CSV", "/NH"],
                    capture_output=True, text=True, check=False, timeout=5,
                )
                stdout = (result.stdout or "").strip()
                if proc_name.lower() in stdout.lower():
                    found.append(proc_name)
            except Exception as e:
                self._record_connect_diag(f"Process probe for {proc_name} failed: {e}")

        self._last_process_probe = len(found) > 0
        if found:
            self._record_connect_diag(f"Detected processes: {', '.join(found)}")
        else:
            self._record_connect_diag("No WeChat/Weixin process detected")

    def _append_connect_hints(self, import_failed: bool = False) -> None:
        for hint in self._build_connect_hints(import_failed):
            self._record_connect_diag(f"Hint: {hint}")

    def _build_connect_hints(self, import_failed: bool = False) -> list[str]:
        if sys.platform != "win32":
            return ["Run this agent on Windows 10 or 11 with desktop WeChat."]
        hints: list[str] = []
        if self._last_process_probe is False:
            hints.append("Start desktop WeChat (微信) and log in before clicking Connect WeChat.")
        else:
            hints.append("Make sure WeChat is open to the main chat window, not just the login QR screen.")
        hints.append("Run WeChat and this agent at the same privilege level; admin/admin is the safest setup.")
        hints.append("Keep WeChat visible and not minimized during the initial attach.")
        if not self._vision:
            hints.append("Configure VLM API URL in settings for vision-based mode.")
        return hints
