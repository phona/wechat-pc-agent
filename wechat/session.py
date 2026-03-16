import logging
import platform
import subprocess
import sys
import time
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class WeChatSession:
    """Wraps wxauto.WeChat() with login detection and health checks."""

    def __init__(self):
        self._wx = None
        self._listen_callbacks: dict[str, Callable] = {}
        self.last_connect_error = ""
        self.last_connect_diagnostics: list[str] = []
        self._last_process_probe: bool | None = None

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
            import wxauto
            self._record_wxauto_details(wxauto)
            WeChat = wxauto.WeChat
        except Exception as e:
            self.last_connect_error = f"wxauto import failed: {e}"
            self._record_connect_diag(self.last_connect_error)
            self._append_connect_hints(import_failed=True)
            logger.exception("Failed to import wxauto while connecting to WeChat")
            return False

        try:
            self._wx = WeChat()
            self._record_connect_diag("wxauto.WeChat() attached successfully")
            logger.info("Connected to WeChat PC window")
            return True
        except Exception as e:
            self._wx = None
            self.last_connect_error = str(e) or e.__class__.__name__
            self._record_connect_diag(
                f"wxauto.WeChat() raised {e.__class__.__name__}: {self.last_connect_error}"
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
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq WeChat.exe", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except Exception as e:
            self._record_connect_diag(f"WeChat process probe failed: {e}")
            return

        stdout = (result.stdout or "").strip()
        self._last_process_probe = "WeChat.exe" in stdout
        if self._last_process_probe:
            self._record_connect_diag("WeChat.exe process detected")
        else:
            self._record_connect_diag("WeChat.exe process not detected")

    def _append_connect_hints(self, import_failed: bool = False) -> None:
        for hint in self._build_connect_hints(import_failed):
            self._record_connect_diag(f"Hint: {hint}")

    def _build_connect_hints(self, import_failed: bool) -> list[str]:
        if sys.platform != "win32":
            return ["Run this agent on Windows 10 or 11 with desktop WeChat."]

        hints: list[str] = []
        if import_failed:
            hints.append("Verify wxauto is installed in the same Python environment as this app.")
            return hints

        if self._last_process_probe is False:
            hints.append("Start desktop WeChat and log in before clicking Connect WeChat.")
        else:
            hints.append("Make sure WeChat is open to the main chat window, not just the login QR screen.")
        hints.append("Run WeChat and this agent at the same privilege level; admin/admin is the safest setup.")
        hints.append("Keep WeChat visible and not minimized during the initial attach.")
        hints.append("If WeChat recently updated, wxauto may not match the current UI layout.")
        return hints

    @property
    def wx(self):
        """Access the underlying wxauto.WeChat instance."""
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

    def get_chat_messages(self, chat_name: Optional[str] = None) -> list:
        """Get messages from current or specified chat."""
        try:
            if chat_name:
                self._wx.ChatWith(chat_name)
            msgs = self._wx.GetAllMessage()
            return msgs if msgs else []
        except Exception as e:
            logger.error("Failed to get messages from %s: %s", chat_name, e)
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

    def send_file(self, chat_name: str, file_path: str) -> bool:
        """Send a file to a chat."""
        try:
            self._wx.SendFiles(file_path, chat_name)
            logger.info("Sent file to %s: %s", chat_name, file_path)
            return True
        except Exception as e:
            logger.error("Failed to send file to %s: %s", chat_name, e)
            return False

    def scroll_up(self) -> None:
        """Scroll the current chat window up to load older messages."""
        try:
            import pyautogui
            pyautogui.scroll(10)
        except Exception as e:
            logger.error("Failed to scroll up: %s", e)

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

    def add_listen_chat(self, chat_name: str, callback: Callable) -> bool:
        """Register event-driven listener for a chat using wxauto 3.9 AddListenChat."""
        try:
            self._wx.AddListenChat(who=chat_name, savepic=True)
            self._listen_callbacks[chat_name] = callback
            logger.info("Listening to chat: %s", chat_name)
            return True
        except Exception as e:
            logger.error("Failed to add listen for '%s': %s", chat_name, e)
            return False

    def remove_listen_chat(self, chat_name: str) -> None:
        """Remove listener for a chat."""
        try:
            self._wx.RemoveListenChat(who=chat_name)
            self._listen_callbacks.pop(chat_name, None)
            logger.info("Removed listener: %s", chat_name)
        except Exception as e:
            logger.error("Failed to remove listen for '%s': %s", chat_name, e)

    def get_listen_messages(self) -> dict[str, list]:
        """
        Get new messages from all listened chats.
        Returns {chat_name: [messages]} for chats that have new messages.
        """
        try:
            msgs = self._wx.GetListenMessage()
            return msgs if msgs else {}
        except Exception as e:
            logger.error("Failed to get listen messages: %s", e)
            return {}
