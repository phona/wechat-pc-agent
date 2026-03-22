"""Tests for wechat.win32_utils — Win32 window management.

These tests mock ctypes.windll (Windows-only) so they can run on Linux CI.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from wechat.win32_utils import WeChatWindow


@pytest.fixture(autouse=True)
def _force_win32():
    """Pretend we're on Windows for all tests."""
    with patch.object(sys, "platform", "win32"):
        yield


@pytest.fixture
def window():
    return WeChatWindow()


def _patch_windll():
    """Patch ctypes.windll (doesn't exist on Linux) with create=True."""
    return patch("ctypes.windll", create=True)


def _patch_wintypes():
    """Patch ctypes.wintypes for Linux compat."""
    return patch("ctypes.wintypes", create=True)


class TestFind:
    def test_find_by_pid(self, window):
        """Should find window by matching WeChat PID."""
        mock_user32 = MagicMock()
        mock_user32.IsWindowVisible.return_value = True

        pid_instance = MagicMock()
        pid_instance.value = 1234

        def mock_enum(callback, lparam):
            callback(12345, 0)
            return True

        mock_user32.EnumWindows.side_effect = mock_enum

        with patch.object(window, "_find_wechat_pids", return_value={1234}):
            with _patch_windll() as mock_windll, \
                 _patch_wintypes() as mock_wt, \
                 patch("ctypes.WINFUNCTYPE", create=True) as mock_ft, \
                 patch("ctypes.create_unicode_buffer", create=True) as mock_buf, \
                 patch("ctypes.byref", create=True):

                mock_windll.user32 = mock_user32
                mock_ft.return_value = lambda f: f

                # title and class buffers
                title_buf = MagicMock()
                title_buf.value = "Weixin"
                class_buf = MagicMock()
                class_buf.value = "Qt51514QWindowIcon"
                mock_buf.side_effect = [title_buf, class_buf]

                mock_wt.BOOL = int
                mock_wt.HWND = int
                mock_wt.LPARAM = int
                pid_mock = MagicMock()
                pid_mock.return_value = pid_instance
                mock_wt.DWORD = pid_mock

                assert window.find() is True
                assert window.hwnd == 12345

    def test_find_no_window(self, window):
        """Should return False when no WeChat window exists."""
        with patch.object(window, "_find_wechat_pids", return_value=set()):
            with _patch_windll() as mock_windll, \
                 _patch_wintypes() as mock_wt, \
                 patch("ctypes.WINFUNCTYPE", create=True) as mock_ft:

                mock_windll.user32.EnumWindows.side_effect = lambda cb, lp: True
                mock_ft.return_value = lambda f: f
                mock_wt.BOOL = int
                mock_wt.HWND = int
                mock_wt.LPARAM = int

                assert window.find() is False
                assert window.hwnd == 0

    def test_find_not_windows(self):
        """Should return False on non-Windows platform."""
        with patch.object(sys, "platform", "linux"):
            w = WeChatWindow()
            assert w.find() is False


class TestActivate:
    def test_activate_success(self, window):
        window.hwnd = 12345
        with _patch_windll() as mock_windll, patch("time.sleep"):
            mock_windll.user32.IsIconic.return_value = False
            mock_windll.user32.SetForegroundWindow.return_value = True
            assert window.activate() is True
            mock_windll.user32.SetForegroundWindow.assert_called_once_with(12345)

    def test_activate_restores_minimized(self, window):
        window.hwnd = 12345
        with _patch_windll() as mock_windll, patch("time.sleep"):
            mock_windll.user32.IsIconic.return_value = True
            mock_windll.user32.ShowWindow.return_value = True
            mock_windll.user32.SetForegroundWindow.return_value = True
            assert window.activate() is True
            mock_windll.user32.ShowWindow.assert_called_once_with(12345, 9)

    def test_activate_no_hwnd(self, window):
        assert window.activate() is False


class TestMaximize:
    def test_maximize_success(self, window):
        window.hwnd = 12345
        with _patch_windll() as mock_windll, patch("time.sleep"):
            mock_windll.user32.ShowWindow.return_value = True
            assert window.maximize() is True
            mock_windll.user32.ShowWindow.assert_called_once_with(12345, 3)

    def test_maximize_no_hwnd(self, window):
        assert window.maximize() is False


class TestGetRect:
    def test_get_rect_success(self, window):
        window.hwnd = 12345
        rect_instance = MagicMock()
        rect_instance.left = 0
        rect_instance.top = 0
        rect_instance.right = 1920
        rect_instance.bottom = 1080

        with _patch_windll() as mock_windll, \
             _patch_wintypes() as mock_wt, \
             patch("ctypes.byref", create=True):
            mock_windll.user32.GetWindowRect.return_value = True
            mock_wt.RECT.return_value = rect_instance
            result = window.get_rect()
            assert result == (0, 0, 1920, 1080)

    def test_get_rect_no_hwnd(self, window):
        with pytest.raises(RuntimeError, match="No WeChat window"):
            window.get_rect()


class TestScreenshot:
    def test_screenshot_full(self, window):
        window.hwnd = 12345
        mock_image = MagicMock()
        mock_imagegrab = MagicMock()
        mock_imagegrab.grab.return_value = mock_image

        with patch.object(window, "get_rect", return_value=(0, 0, 1920, 1080)), \
             patch.dict("sys.modules", {"PIL": MagicMock(ImageGrab=mock_imagegrab),
                                        "PIL.ImageGrab": mock_imagegrab}):
            result = window.screenshot_full()
            assert result is mock_image
            mock_imagegrab.grab.assert_called_once_with(bbox=(0, 0, 1920, 1080))

    def test_screenshot_region(self, window):
        mock_image = MagicMock()
        mock_imagegrab = MagicMock()
        mock_imagegrab.grab.return_value = mock_image

        with patch.dict("sys.modules", {"PIL": MagicMock(ImageGrab=mock_imagegrab),
                                        "PIL.ImageGrab": mock_imagegrab}):
            result = window.screenshot_region(100, 200, 500, 600)
            assert result is mock_image
            mock_imagegrab.grab.assert_called_once_with(bbox=(100, 200, 500, 600))


class TestIsVisible:
    def test_visible(self, window):
        window.hwnd = 12345
        with _patch_windll() as mock_windll:
            mock_windll.user32.IsWindowVisible.return_value = True
            mock_windll.user32.IsIconic.return_value = False
            assert window.is_visible() is True

    def test_minimized(self, window):
        window.hwnd = 12345
        with _patch_windll() as mock_windll:
            mock_windll.user32.IsWindowVisible.return_value = True
            mock_windll.user32.IsIconic.return_value = True
            assert window.is_visible() is False

    def test_no_hwnd(self, window):
        assert window.is_visible() is False
