import logging
import math
import platform
import random
import subprocess
import sys
import time
from typing import Optional

logger = logging.getLogger(__name__)


class WeChatSession:
    """Wraps wxauto4/wxauto WeChat() with login detection and health checks."""

    def __init__(self):
        self._wx = None
        self.last_connect_error = ""
        self.last_connect_diagnostics: list[str] = []
        self._last_process_probe: bool | None = None
        self.ui_simulator = None  # Optional UISimulator for advanced human sim

    def connect(self) -> bool:
        """Attach to the running WeChat PC window. Returns True if successful."""
        self._wx = None
        self.last_connect_error = ""
        self.last_connect_diagnostics = []
        self._last_process_probe = None
        self._record_connect_diag(f"Starting attach on {platform.platform()}")
        self._record_connect_diag(f"Python {platform.python_version()} at {sys.executable}")
        self._probe_admin_status()
        self._probe_wechat_process()

        try:
            try:
                import wxauto4 as _wxmod
                self._record_connect_diag("Using wxauto4 (WeChat 4.x)")
            except ImportError:
                import wxauto as _wxmod
                self._record_connect_diag("Using wxauto (WeChat 3.x)")
            self._record_wxauto_details(_wxmod)
            WeChat = _wxmod.WeChat
        except Exception as e:
            self.last_connect_error = f"wxauto import failed: {e}"
            self._record_connect_diag(self.last_connect_error)
            self._append_connect_hints(import_failed=True)
            logger.exception("Failed to import wxauto/wxauto4 while connecting to WeChat")
            return False

        try:
            self._wx = WeChat()
            self._record_connect_diag("WeChat() attached successfully")
            logger.info("Connected to WeChat PC window")
            return True
        except Exception as e:
            self._wx = None
            self.last_connect_error = str(e) or e.__class__.__name__
            self._record_connect_diag(
                f"WeChat() raised {e.__class__.__name__}: {self.last_connect_error}"
            )
            self._append_connect_hints()
            logger.exception("Failed to connect to WeChat")
            return False

    def _record_connect_diag(self, message: str) -> None:
        self.last_connect_diagnostics.append(message)
        logger.info("WeChat connect: %s", message)

    def _record_wxauto_details(self, wxauto_module) -> None:
        module_file = getattr(wxauto_module, "__file__", None)
        module_version = getattr(wxauto_module, "__version__", None)
        if isinstance(module_file, str) and module_file:
            self._record_connect_diag(f"wxauto module: {module_file}")
        if isinstance(module_version, str) and module_version:
            self._record_connect_diag(f"wxauto version: {module_version}")

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

        # Check multiple possible process names (WeChat renamed to Weixin in some versions)
        process_names = ["WeChat.exe", "Weixin.exe"]
        found = []
        for proc_name in process_names:
            try:
                result = subprocess.run(
                    ["tasklist", "/FI", f"IMAGENAME eq {proc_name}", "/FO", "CSV", "/NH"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=5,
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

        # Try to enumerate WeChat-related windows for extra diagnostics
        self._probe_wechat_windows()

    def _probe_wechat_windows(self) -> None:
        """Enumerate top-level windows to find WeChat-related ones."""
        try:
            import ctypes
            import ctypes.wintypes

            EnumWindows = ctypes.windll.user32.EnumWindows
            GetWindowTextW = ctypes.windll.user32.GetWindowTextW
            GetClassNameW = ctypes.windll.user32.GetClassNameW  # noqa: N806
            IsWindowVisible = ctypes.windll.user32.IsWindowVisible

            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

            wechat_windows: list[str] = []

            def enum_callback(hwnd, _lparam):
                if not IsWindowVisible(hwnd):
                    return True
                title_buf = ctypes.create_unicode_buffer(256)
                class_buf = ctypes.create_unicode_buffer(256)
                GetWindowTextW(hwnd, title_buf, 256)
                GetClassNameW(hwnd, class_buf, 256)
                title = title_buf.value
                cls = class_buf.value
                # Look for WeChat/Weixin related windows
                for keyword in ("WeChat", "Weixin", "微信", "WeChatMainWndForPC", "WeChatLoginWndForPC"):
                    if keyword.lower() in title.lower() or keyword.lower() in cls.lower():
                        wechat_windows.append(f"hwnd={hwnd} title='{title}' class='{cls}'")
                        break
                return True

            EnumWindows(WNDENUMPROC(enum_callback), 0)

            if wechat_windows:
                for w in wechat_windows:
                    self._record_connect_diag(f"Found window: {w}")
            else:
                self._record_connect_diag("No WeChat-related windows found")
        except Exception as e:
            self._record_connect_diag(f"Window enumeration failed: {e}")

    def _append_connect_hints(self, import_failed: bool = False) -> None:
        for hint in self._build_connect_hints(import_failed):
            self._record_connect_diag(f"Hint: {hint}")

    def _build_connect_hints(self, import_failed: bool) -> list[str]:
        if sys.platform != "win32":
            return ["Run this agent on Windows 10 or 11 with desktop WeChat."]

        hints: list[str] = []
        if import_failed:
            if "No module named 'PIL'" in self.last_connect_error:
                hints.append("This build is missing Pillow/PIL; rebuild the Windows package with Pillow included.")
            hints.append("Verify wxauto4 (or wxauto) is installed: pip install wxauto4")
            return hints

        if self._last_process_probe is False:
            hints.append("Start desktop WeChat (微信) and log in before clicking Connect WeChat.")
            hints.append("If using a newer WeChat version, the process may be named Weixin.exe instead of WeChat.exe.")
        else:
            hints.append("Make sure WeChat is open to the main chat window, not just the login QR screen.")
        hints.append("Run WeChat and this agent at the same privilege level; admin/admin is the safest setup.")
        hints.append("Keep WeChat visible and not minimized during the initial attach.")
        hints.append("For WeChat 4.x, install wxauto4: pip install wxauto4")
        hints.append("For WeChat 3.x, install wxauto: pip install wxauto")
        return hints

    @property
    def wx(self):
        """Access the underlying wxauto/wxauto4 WeChat instance."""
        if self._wx is None:
            raise RuntimeError("WeChat not connected")
        return self._wx

    def is_ready(self) -> bool:
        """Check if WeChat window is responsive."""
        if self._wx is None:
            return False
        try:
            self._wx.GetSessionList()
            return True
        except Exception:
            return False

    def get_session_list(self) -> list[str]:
        """Get list of recent chat names."""
        try:
            sessions = self._wx.GetSessionList()
            return [s if isinstance(s, str) else str(s) for s in sessions]
        except Exception as e:
            logger.error("Failed to get session list: %s", e)
            return []

    def send_text(self, chat_name: str, message: str) -> bool:
        """Send a text message to a chat."""
        try:
            self._wx.SendMsg(message, chat_name)
            logger.info("Sent message to %s", chat_name)
            return True
        except Exception as e:
            logger.error("Failed to send to %s: %s", chat_name, e)
            return False

    def send_text_human(self, chat_name: str, message: str) -> bool:
        """Send text via UI simulation: navigate, click input, type/paste, press Enter.

        Falls back to send_text() on any failure.
        """
        try:
            import pyautogui
            import pyperclip
        except ImportError:
            logger.warning("pyautogui/pyperclip not available, falling back to SendMsg")
            return self.send_text(chat_name, message)

        message_entered = False
        try:
            # Step 1: Navigate to chat via wxauto
            self._wx.ChatWith(chat_name)
            time.sleep(random.uniform(0.2, 0.5))

            # Step 2: Click the input box with human-like mouse movement
            ix, iy = self._get_input_box_position()
            if self.ui_simulator:
                self.ui_simulator.bezier_move_click(ix, iy, pyautogui)
            else:
                self._bezier_move_click(ix, iy, pyautogui)
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
                # Chinese/mixed text: clipboard paste
                pyperclip.copy(message)
                time.sleep(random.uniform(0.1, 0.3))
                pyautogui.hotkey("ctrl", "v")
                time.sleep(random.uniform(0.1, 0.2))
            message_entered = True

            # Step 4: Press Enter to send
            time.sleep(random.uniform(0.1, 0.4))
            pyautogui.press("enter")
            logger.info("Sent message (human sim) to %s", chat_name)
            return True
        except Exception as e:
            logger.error("Human send failed for %s: %s", chat_name, e)
            if message_entered:
                # Message was typed/pasted — don't fall back to avoid double-send
                return False
            logger.info("Falling back to SendMsg for %s", chat_name)
            return self.send_text(chat_name, message)

    def _get_input_box_position(self) -> tuple[int, int]:
        """Get the screen coordinates of the WeChat input box.

        Strategy (most robust first):
        1. UIA: find the actual Edit control in the chat panel
        2. Cached position from a previous successful UIA lookup
        3. Fallback: window rect with hardcoded offset
        """
        # Strategy 1: UIA tree search for the Edit control
        pos = self._find_edit_control_via_uia()
        if pos:
            self._cached_input_box = pos
            return pos

        # Strategy 2: cached position from a previous lookup
        if hasattr(self, "_cached_input_box") and self._cached_input_box:
            logger.debug("Using cached input box position")
            return self._cached_input_box

        # Strategy 3: window rect fallback
        return self._get_input_box_from_window_rect()

    def _find_edit_control_via_uia(self) -> tuple[int, int] | None:
        """Walk the UIA tree to find the message input Edit control."""
        try:
            import uiautomation as uia

            # The WeChat chat window has an Edit control for message input.
            # It's typically the last/deepest Edit control in the main window.
            wechat_window = uia.ControlFromHandle(self._wx.UiaAPI.handle)
            if not wechat_window:
                return None

            # Search for Edit controls — the message input box
            edit = wechat_window.EditControl(searchDepth=10)
            if edit and edit.BoundingRectangle.width() > 0:
                rect = edit.BoundingRectangle
                x = rect.left + rect.width() // 2
                y = rect.top + rect.height() // 2
                logger.debug("UIA Edit control found at (%d, %d)", x, y)
                return (x, y)
        except ImportError:
            logger.debug("uiautomation not available, skipping UIA lookup")
        except Exception as e:
            logger.debug("UIA Edit search failed: %s", e)
        return None

    def _get_input_box_from_window_rect(self) -> tuple[int, int]:
        """Fallback: estimate input box position from window rectangle."""
        try:
            import win32gui
            hwnd = self._wx.UiaAPI.handle
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            x = (left + right) // 2
            y = bottom - 80
            return x, y
        except Exception:
            try:
                rect = self._wx.UiaAPI.BoundingRectangle
                x = rect.left + (rect.right - rect.left) // 2
                y = rect.bottom - 80
                return x, y
            except Exception as e:
                logger.warning("Cannot determine input box position: %s", e)
                raise

    def get_window_rect(self) -> tuple[int, int, int, int] | None:
        """Get the WeChat window rectangle (left, top, right, bottom)."""
        try:
            import win32gui
            hwnd = self._wx.UiaAPI.handle
            return win32gui.GetWindowRect(hwnd)
        except Exception:
            try:
                r = self._wx.UiaAPI.BoundingRectangle
                return (r.left, r.top, r.right, r.bottom)
            except Exception:
                return None

    def _bezier_move_click(self, x: int, y: int, pyautogui) -> None:
        """Move mouse along a cubic Bézier curve to (x, y) and click."""
        start_x, start_y = pyautogui.position()
        dx = x - start_x
        dy = y - start_y
        distance = math.hypot(dx, dy)
        steps = max(10, int(distance / 5))

        # Two random control points offset perpendicular to the line
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
            # Cubic Bézier: B(t) = (1-t)^3*P0 + 3(1-t)^2*t*P1 + 3(1-t)*t^2*P2 + t^3*P3
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
            # Variable delay: mostly fast, occasional pause
            if random.random() < 0.05:
                time.sleep(random.uniform(0.2, 0.5))
            else:
                time.sleep(random.uniform(0.03, 0.15))

    def send_file(self, chat_name: str, file_path: str) -> bool:
        """Send a file to a chat."""
        try:
            self._wx.SendFiles(file_path, chat_name)
            logger.info("Sent file to %s: %s", chat_name, file_path)
            return True
        except Exception as e:
            logger.error("Failed to send file to %s: %s", chat_name, e)
            return False

    def search_contact(self, name: str) -> list[str]:
        """
        Search for a contact by name using WeChat's search box.
        Uses pyautogui to: Ctrl+F → type name → read results.
        Returns list of matching contact names.
        """
        try:
            import pyautogui
            # Open search box
            pyautogui.hotkey("ctrl", "f")
            time.sleep(0.3)
            # Clear any previous text and type the search query
            pyautogui.hotkey("ctrl", "a")
            pyautogui.typewrite(name, interval=0.05) if name.isascii() else pyautogui.write(name)
            time.sleep(0.5)
            # wxauto can read the search results from the session list
            sessions = self.get_session_list()
            # Press Escape to close search
            pyautogui.press("escape")
            time.sleep(0.2)
            # Filter results that match the search query
            matches = [s for s in sessions if name.lower() in s.lower()]
            logger.info("Search '%s': found %d matches", name, len(matches))
            return matches
        except Exception as e:
            logger.error("Search failed for '%s': %s", name, e)
            return []

    def open_chat(self, chat_name: str) -> bool:
        """Open a chat window by name."""
        try:
            self._wx.ChatWith(chat_name)
            logger.info("Opened chat: %s", chat_name)
            return True
        except Exception as e:
            logger.error("Failed to open chat '%s': %s", chat_name, e)
            return False

