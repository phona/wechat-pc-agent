import logging
import time
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class WeChatSession:
    """Wraps wxauto.WeChat() with login detection and health checks."""

    def __init__(self):
        self._wx = None
        self._listen_callbacks: dict[str, Callable] = {}

    def connect(self) -> bool:
        """Attach to the running WeChat PC window. Returns True if successful."""
        try:
            from wxauto import WeChat
            self._wx = WeChat()
            logger.info("Connected to WeChat PC window")
            return True
        except Exception as e:
            logger.error("Failed to connect to WeChat: %s", e)
            self._wx = None
            return False

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
