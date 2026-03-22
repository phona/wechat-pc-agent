"""Win32 window management for WeChat PC.

Pure ctypes implementation — no pywin32 dependency.
Handles window discovery, focus management, and screenshots.
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Win32 constants
SW_MAXIMIZE = 3
SW_RESTORE = 9


class WeChatWindow:
    """Manages the WeChat desktop window via Win32 API."""

    # Process names to search for (WeChat 3.x and 4.x)
    PROCESS_NAMES = ("WeChat.exe", "Weixin.exe")
    # Window title keywords
    TITLE_KEYWORDS = ("WeChat", "Weixin", "微信")

    def __init__(self) -> None:
        self.hwnd: int = 0

    def find(self) -> bool:
        """Find the WeChat main window by enumerating visible windows.

        Looks for windows belonging to WeChat/Weixin processes.
        Returns True if a suitable window was found.
        """
        if sys.platform != "win32":
            logger.warning("Win32 window management requires Windows")
            return False

        import ctypes
        import ctypes.wintypes

        user32 = ctypes.windll.user32

        # First, find WeChat PIDs via tasklist
        wechat_pids = self._find_wechat_pids()

        # Enumerate windows to find the main WeChat window
        WNDENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
        )

        candidates: list[tuple[int, str, str]] = []  # (hwnd, title, class)

        def _enum_callback(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            # Get PID
            pid = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            # Get title and class
            title_buf = ctypes.create_unicode_buffer(256)
            class_buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title_buf, 256)
            user32.GetClassNameW(hwnd, class_buf, 256)
            title = title_buf.value
            cls = class_buf.value

            # Match by PID if we found WeChat processes
            if wechat_pids and pid.value in wechat_pids:
                candidates.append((hwnd, title, cls))
                return True

            # Fallback: match by title keywords
            for keyword in self.TITLE_KEYWORDS:
                if keyword.lower() in title.lower():
                    # Skip our own agent window
                    if "Agent" not in title:
                        candidates.append((hwnd, title, cls))
                    break
            return True

        user32.EnumWindows(WNDENUMPROC(_enum_callback), 0)

        if not candidates:
            logger.warning("No WeChat window found")
            return False

        # Prefer the one with the most recognizable title
        best = candidates[0]
        for hwnd, title, cls in candidates:
            for keyword in self.TITLE_KEYWORDS:
                if keyword.lower() in title.lower():
                    best = (hwnd, title, cls)
                    break

        self.hwnd = best[0]
        logger.info("Found WeChat window: hwnd=%d title='%s' class='%s'", *best)
        return True

    def _find_wechat_pids(self) -> set[int]:
        """Find PIDs of WeChat/Weixin processes via tasklist."""
        import subprocess

        pids: set[int] = set()
        for proc_name in self.PROCESS_NAMES:
            try:
                result = subprocess.run(
                    ["tasklist", "/FI", f"IMAGENAME eq {proc_name}", "/FO", "CSV", "/NH"],
                    capture_output=True, text=True, check=False, timeout=5,
                )
                for line in (result.stdout or "").strip().splitlines():
                    parts = line.strip().strip('"').split('","')
                    if len(parts) >= 2 and parts[0].lower() == proc_name.lower():
                        try:
                            pids.add(int(parts[1]))
                        except ValueError:
                            pass
            except Exception:
                pass
        return pids

    def activate(self) -> bool:
        """Bring the WeChat window to the foreground."""
        if not self.hwnd:
            return False
        try:
            import ctypes
            user32 = ctypes.windll.user32
            # Restore if minimized
            if user32.IsIconic(self.hwnd):
                user32.ShowWindow(self.hwnd, SW_RESTORE)
                time.sleep(0.2)
            user32.SetForegroundWindow(self.hwnd)
            time.sleep(0.2)
            return True
        except Exception as e:
            logger.error("Failed to activate window: %s", e)
            return False

    def maximize(self) -> bool:
        """Maximize the WeChat window."""
        if not self.hwnd:
            return False
        try:
            import ctypes
            ctypes.windll.user32.ShowWindow(self.hwnd, SW_MAXIMIZE)
            time.sleep(0.5)  # Wait for maximize animation
            return True
        except Exception as e:
            logger.error("Failed to maximize window: %s", e)
            return False

    def get_rect(self) -> tuple[int, int, int, int]:
        """Get window rectangle (left, top, right, bottom)."""
        if not self.hwnd:
            raise RuntimeError("No WeChat window found")
        import ctypes
        import ctypes.wintypes

        rect = ctypes.wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(self.hwnd, ctypes.byref(rect)):
            raise RuntimeError("GetWindowRect failed")
        return (rect.left, rect.top, rect.right, rect.bottom)

    def screenshot_full(self) -> "PIL.Image.Image":
        """Capture a screenshot of the full WeChat window."""
        from PIL import ImageGrab

        rect = self.get_rect()
        return ImageGrab.grab(bbox=rect)

    def screenshot_region(
        self, left: int, top: int, right: int, bottom: int
    ) -> "PIL.Image.Image":
        """Capture a screenshot of a specific screen region."""
        from PIL import ImageGrab

        return ImageGrab.grab(bbox=(left, top, right, bottom))

    def is_visible(self) -> bool:
        """Check if the WeChat window is visible and not minimized."""
        if not self.hwnd:
            return False
        try:
            import ctypes
            user32 = ctypes.windll.user32
            return bool(user32.IsWindowVisible(self.hwnd)) and not bool(
                user32.IsIconic(self.hwnd)
            )
        except Exception:
            return False
