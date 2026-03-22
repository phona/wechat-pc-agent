"""Tests for wechat.ui_state — multi-chat state manager."""

import time
from wechat.ui_state import ChatState, UIStateManager


class TestUIStateManager:
    def test_empty_no_unread(self):
        mgr = UIStateManager()
        assert mgr.has_unread() is False
        assert mgr.get_next_unread() is None
        assert mgr.get_unread_count() == 0

    def test_mark_unread(self):
        mgr = UIStateManager()
        mgr.mark_unread("张三", count=3)
        assert mgr.has_unread() is True
        assert mgr.get_next_unread() == "张三"
        assert mgr.get_unread_count() == 1

    def test_mark_processed(self):
        mgr = UIStateManager()
        mgr.mark_unread("张三")
        mgr.mark_processed("张三", msg_hash="abc123", msg_preview="你好")
        assert mgr.has_unread() is False
        assert mgr.get_next_unread() is None
        assert mgr.get_last_seen_hash("张三") == "abc123"
        assert mgr.get_last_seen_preview("张三") == "你好"

    def test_priority_oldest_first(self):
        mgr = UIStateManager()
        # 张三 checked earlier than 李四
        mgr.mark_unread("张三")
        mgr.get_or_create("张三").last_checked = 100.0
        mgr.mark_unread("李四")
        mgr.get_or_create("李四").last_checked = 200.0
        # Should return 张三 first (oldest last_checked)
        assert mgr.get_next_unread() == "张三"

    def test_priority_never_checked_first(self):
        mgr = UIStateManager()
        mgr.mark_unread("张三")
        mgr.get_or_create("张三").last_checked = 100.0
        mgr.mark_unread("新客户")
        # 新客户 has last_checked=0 (never checked), should be first
        assert mgr.get_next_unread() == "新客户"

    def test_update_from_sidebar(self):
        mgr = UIStateManager()
        mgr.mark_processed("张三", "hash1", "旧消息")

        sidebar = [
            {"name": "张三", "has_unread": True, "unread_count": 2},
            {"name": "李四", "has_unread": False},
            {"name": "王五", "has_unread": True, "unread_count": None},
        ]
        mgr.update_from_sidebar(sidebar)

        assert mgr.has_unread() is True
        assert mgr.get_unread_count() == 2  # 张三 and 王五
        # 张三 still has its last_seen_hash
        assert mgr.get_last_seen_hash("张三") == "hash1"

    def test_update_clears_unread(self):
        mgr = UIStateManager()
        mgr.mark_unread("张三")
        sidebar = [{"name": "张三", "has_unread": False}]
        mgr.update_from_sidebar(sidebar)
        assert mgr.has_unread() is False

    def test_mark_read(self):
        mgr = UIStateManager()
        mgr.mark_unread("张三", count=5)
        mgr.mark_read("张三")
        assert mgr.has_unread() is False

    def test_get_all_chat_names(self):
        mgr = UIStateManager()
        mgr.mark_unread("A")
        mgr.mark_unread("B")
        mgr.mark_read("C")
        names = mgr.get_all_chat_names()
        assert sorted(names) == ["A", "B", "C"]

    def test_get_last_seen_unknown_chat(self):
        mgr = UIStateManager()
        assert mgr.get_last_seen_preview("unknown") == ""
        assert mgr.get_last_seen_hash("unknown") == ""

    def test_long_preview_truncated(self):
        mgr = UIStateManager()
        long_msg = "x" * 100
        mgr.mark_processed("张三", "hash", long_msg)
        assert len(mgr.get_last_seen_preview("张三")) == 50

    def test_multiple_rounds(self):
        """Simulate multiple rounds of processing."""
        mgr = UIStateManager()

        # Round 1: 张三 and 李四 have messages
        mgr.update_from_sidebar([
            {"name": "张三", "has_unread": True},
            {"name": "李四", "has_unread": True},
        ])

        # Process 张三
        chat = mgr.get_next_unread()
        mgr.mark_processed(chat, "hash1", "msg1")

        # Process 李四
        chat = mgr.get_next_unread()
        assert chat == "李四"
        mgr.mark_processed(chat, "hash2", "msg2")

        assert mgr.has_unread() is False

        # Round 2: 张三 has new message, 王五 is new
        mgr.update_from_sidebar([
            {"name": "张三", "has_unread": True},
            {"name": "李四", "has_unread": False},
            {"name": "王五", "has_unread": True},
        ])

        # 王五 never checked, should come first
        assert mgr.get_next_unread() == "王五"

    def test_update_from_ocr_marks_unread(self):
        mgr = UIStateManager()
        mgr.update_from_ocr("张三", preview="你好", has_unread=True, count=2)
        assert mgr.has_unread() is True
        state = mgr.get_or_create("张三")
        assert state.pending_count == 2
        assert state.last_seen_msg_preview == "你好"

    def test_update_from_ocr_marks_read(self):
        mgr = UIStateManager()
        mgr.mark_unread("张三", 3)
        mgr.update_from_ocr("张三", preview="已读", has_unread=False)
        assert mgr.has_unread() is False

    def test_row_bbox_field(self):
        state = ChatState(row_bbox=(10, 20, 300, 64))
        assert state.row_bbox == (10, 20, 300, 64)
