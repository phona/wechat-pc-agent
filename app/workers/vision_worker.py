"""Vision worker — three-layer polling for WeChat message detection.

Layer 1: Pixel diff per-region (free, every poll cycle)
Layer 2: PaddleOCR on changed regions (cheap)
Layer 3: VLM fallback for images / OCR failures (expensive, rare)
"""

from __future__ import annotations

import logging
import time

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from wechat.vision import RegionType, RegionChangeEvent, OCRResult, VisionPerception

logger = logging.getLogger(__name__)

SCROLL_SETTLE_TIME = 0.3


class VisionWorker(QThread):
    """Monitors WeChat for new messages using three-layer vision detection."""

    new_messages = pyqtSignal(list)
    change_detected = pyqtSignal()
    log_message = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        vision: VisionPerception,
        session,      # WeChatSession
        bridge,       # WebSocketBridge
        state_mgr,    # UIStateManager
        poll_interval: float = 1.5,
        max_scroll_rounds: int = 3,
    ) -> None:
        super().__init__()
        self._vision = vision
        self._session = session
        self._bridge = bridge
        self._state_mgr = state_mgr
        self._poll_interval = poll_interval
        self._max_scroll_rounds = max_scroll_rounds
        self._running = True

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        self.log_message.emit("Vision worker started (three-layer mode)")
        while self._running:
            try:
                self._poll_cycle()
            except Exception as e:
                logger.exception("Vision worker error")
                self.error_occurred.emit(f"Vision error: {e}")
                self._interruptible_sleep(5.0)

    def _poll_cycle(self) -> None:
        """One polling cycle: rect check → pixel diff → OCR → VLM fallback → process unread."""

        # P0: Detect window rect changes → recalibrate
        self._check_rect_and_recalibrate()

        # Layer 1: Take one full screenshot, per-region pixel diff
        full_frame = np.array(self._vision._window.screenshot_full())
        changes = self._vision.check_regions_for_changes(full_frame)
        has_pending = self._state_mgr.has_unread()

        if not changes and not has_pending:
            self._interruptible_sleep(self._poll_interval)
            return

        if changes:
            self.change_detected.emit()

        # Layer 2 + 3: Process changed regions
        vlm_queue: list[RegionChangeEvent] = []

        for event in changes:
            if not self._running:
                return

            if event.region.region_type == RegionType.SIDEBAR_ROW:
                self._process_sidebar_change(event, vlm_queue)

            elif event.region.region_type == RegionType.MESSAGE_AREA:
                self._process_message_change(event, vlm_queue)

            # Update baseline after processing
            self._vision.update_baseline(event.region.id, full_frame)

        # Layer 3: VLM fallback for queued items
        for event in vlm_queue:
            if not self._running:
                return
            self._vlm_fallback(event)

        # Process unread chats (navigate + read)
        self._process_all_unread()

    def _check_rect_and_recalibrate(self) -> None:
        """Recalibrate if the WeChat window moved or resized."""
        try:
            current_rect = self._vision._window.get_rect()
        except Exception:
            return

        calibrated = self._vision._calibrated_rect
        if calibrated is None or current_rect == calibrated:
            return

        self.log_message.emit(
            f"Window rect changed {calibrated} → {current_rect}, recalibrating..."
        )
        try:
            self._vision.calibrate()
            self.log_message.emit("Recalibration complete")
        except Exception as e:
            self.error_occurred.emit(f"Recalibration failed: {e}")

    def _process_sidebar_change(
        self, event: RegionChangeEvent, vlm_queue: list,
    ) -> None:
        """Layer 2: OCR a changed sidebar row."""
        ocr = self._vision.light_sidebar_row(event)

        if ocr is None or self._vision.needs_vlm_fallback(ocr):
            vlm_queue.append(event)
            return

        # Always derive chat name from OCR (handles list scrolling)
        ocr_name = ""
        if ocr.text:
            ocr_name = ocr.text.split("\n")[0].split(" ")[0].strip()

        if ocr_name:
            if ocr_name != event.region.chat_name:
                logger.info(
                    "Row %s name changed: '%s' → '%s'",
                    event.region.id, event.region.chat_name, ocr_name,
                )
                event.region.chat_name = ocr_name

        chat_name = event.region.chat_name or ocr_name
        if chat_name:
            self._state_mgr.update_from_ocr(
                name=chat_name,
                preview=ocr.text,
                has_unread=ocr.has_unread_badge,
            )
            if ocr.has_unread_badge:
                self.log_message.emit(f"Unread detected: {chat_name}")

    def _process_message_change(
        self, event: RegionChangeEvent, vlm_queue: list,
    ) -> None:
        """Layer 2: OCR the message area for new messages."""
        ocr_results = self._vision.light_message_area(event)

        for ocr in ocr_results:
            if not self._running:
                return

            if ocr.is_image_bubble:
                vlm_queue.append(event)
            elif ocr.is_voice_bubble:
                self._handle_voice_message(ocr)
            elif self._vision.needs_vlm_fallback(ocr):
                vlm_queue.append(event)
            else:
                self._forward_text_message(ocr)

    def _vlm_fallback(self, event: RegionChangeEvent) -> None:
        """Layer 3: Use VLM for regions that OCR couldn't handle."""
        try:
            if event.region.region_type == RegionType.SIDEBAR_ROW:
                # Full sidebar read via VLM
                chats = self._vision.vlm_read_sidebar()
                sidebar_data = [
                    {"name": c.name, "has_unread": c.has_unread,
                     "unread_count": c.unread_count}
                    for c in chats
                ]
                self._state_mgr.update_from_sidebar(sidebar_data)
                self.log_message.emit("VLM fallback: sidebar read complete")

            elif event.region.region_type == RegionType.MESSAGE_AREA:
                # Check if it's an image bubble
                if hasattr(event, 'cropped_frame') and event.cropped_frame.size > 0:
                    description = self._vision.vlm_describe_image(
                        event.cropped_frame
                    )
                    active = self._state_mgr.active_chat or "unknown"
                    self._forward_to_bridge(
                        sender=active,
                        conversation_id=active,
                        content=f"[Image: {description}]",
                        msg_type="image",
                    )
                    self.log_message.emit("VLM fallback: image described")
        except Exception as e:
            logger.error("VLM fallback failed: %s", e)
            self.error_occurred.emit(f"VLM fallback error: {e}")

    def _forward_text_message(self, ocr: OCRResult) -> None:
        """Forward an OCR-extracted text message to the cloud bridge."""
        text = ocr.text.strip()
        if not text:
            return

        active = self._state_mgr.active_chat or "unknown"
        self._forward_to_bridge(
            sender=active,
            conversation_id=active,
            content=text,
            msg_type="text",
        )

    def _handle_voice_message(self, ocr: OCRResult) -> None:
        """Handle a detected voice message — mark for human attention."""
        active = self._state_mgr.active_chat or "unknown"
        self._forward_to_bridge(
            sender=active,
            conversation_id=active,
            content="[Voice message — requires human attention]",
            msg_type="voice",
        )
        self.log_message.emit(f"Voice message detected in {active}")

    def _forward_to_bridge(
        self, sender: str, conversation_id: str,
        content: str, msg_type: str = "text",
    ) -> None:
        """Send a message to the WebSocket bridge."""
        try:
            if self._bridge:
                self._bridge.forward_message(
                    sender_id=sender,
                    conversation_id=conversation_id,
                    msg_type=msg_type,
                    content=content,
                )
        except Exception as e:
            logger.error("Failed to forward message: %s", e)

    def _process_all_unread(self) -> None:
        """Process all unread chats: navigate into each and read messages."""
        while self._running:
            chat_name = self._state_mgr.get_next_unread()
            if not chat_name:
                break

            try:
                self._process_one_chat(chat_name)
            except Exception as e:
                logger.error("Failed to process chat '%s': %s", chat_name, e)
                self.error_occurred.emit(f"Chat '{chat_name}' error: {e}")
                self._state_mgr.mark_processed(chat_name, "", "")

    def _process_one_chat(self, chat_name: str) -> None:
        """Click into a chat, read messages via OCR (VLM fallback), forward."""
        import pyautogui
        import pyperclip

        self.log_message.emit(f"Reading messages from: {chat_name}")

        # Click into the chat (requires window lock)
        with self._session.window_lock:
            chat_entry = None
            for c in self._vision.state.visible_chats:
                if c.name == chat_name:
                    chat_entry = c
                    break

            if chat_entry and chat_entry.position_y > 0:
                win_rect = self._session.get_window_rect()
                if win_rect:
                    chat_list = self._vision.state.elements.get("chat_list_area")
                    click_x = win_rect[0] + (
                        chat_list.x + chat_list.w // 2 if chat_list else 200
                    )
                    click_y = win_rect[1] + chat_entry.position_y
                    if self._session.ui_simulator:
                        self._session.ui_simulator.bezier_move_click(
                            click_x, click_y, pyautogui
                        )
                    else:
                        self._session._bezier_move_click(
                            click_x, click_y, pyautogui
                        )
                else:
                    self._session._navigate_to_chat(
                        chat_name, pyautogui, pyperclip
                    )
            else:
                self._session._navigate_to_chat(
                    chat_name, pyautogui, pyperclip
                )

            time.sleep(0.5)

        self._state_mgr.active_chat = chat_name

        # Read messages — try OCR with scroll, then VLM fallback
        last_preview = self._state_mgr.get_last_seen_preview(chat_name)
        messages = self._read_messages_with_scroll(chat_name, last_preview)

        # VLM fallback if OCR produced nothing
        if not messages:
            messages = self._vision.vlm_read_chat_messages(
                chat_name, last_seen_msg=last_preview,
            )

        # Forward new messages (with index-based dedup)
        forwarded = 0
        last_content = ""
        for idx, msg in enumerate(messages):
            if msg.get("is_self"):
                continue
            content = msg.get("content", "")
            if not content:
                continue
            last_content = content
            self._forward_to_bridge(
                sender=msg.get("sender", chat_name),
                conversation_id=chat_name,
                content=content,
            )
            forwarded += 1

        # Update state — hash includes last content + total count for dedup
        if last_content:
            dedup_key = f"{last_content}:{forwarded}"
            msg_hash = VisionPerception.msg_hash(dedup_key)
            self._state_mgr.mark_processed(chat_name, msg_hash, last_content)
        else:
            self._state_mgr.mark_processed(chat_name, "", "")

        if forwarded > 0:
            self.log_message.emit(
                f"Forwarded {forwarded} messages from '{chat_name}'"
            )
            self.new_messages.emit(messages)

    def _read_messages_with_scroll(
        self, chat_name: str, last_preview: str,
    ) -> list[dict]:
        """Read messages from current screen, scroll up if needed to find last_seen.

        Returns all messages after last_preview, in chronological order.
        """
        msg_area = self._vision._region_tracker.get_region("message_area")
        if not msg_area or not self._vision._ocr:
            return []

        all_messages: list[dict] = []
        found_last_seen = not last_preview  # If no last_preview, take everything

        for scroll_round in range(self._max_scroll_rounds):
            if not self._running:
                return []

            full_frame = np.array(self._vision._window.screenshot_full())
            bb = msg_area.bbox
            crop = full_frame[bb.y:bb.y + bb.h, bb.x:bb.x + bb.w]
            if crop.size == 0:
                break

            screen_messages = []
            try:
                img_bytes = self._vision._numpy_to_bytes(crop)
                text, conf = self._vision._ocr.recognize_text(img_bytes)
                if conf >= 0.5 and text:
                    for line in text.split("\n"):
                        line = line.strip()
                        if line:
                            screen_messages.append({
                                "sender": chat_name,
                                "content": line,
                                "is_self": False,
                            })
            except Exception as e:
                logger.debug("OCR message read failed: %s", e)
                break

            if not screen_messages:
                break

            # Check if we found the last seen message
            if last_preview:
                for i, msg in enumerate(screen_messages):
                    if last_preview in msg.get("content", ""):
                        # Take only messages after this one
                        new_msgs = screen_messages[i + 1:]
                        all_messages = new_msgs + all_messages
                        found_last_seen = True
                        break

            if found_last_seen:
                if scroll_round == 0:
                    # First round and found → messages are already correct
                    # (all_messages was set above)
                    pass
                break

            # Haven't found last_seen yet → prepend this screen and scroll up
            all_messages = screen_messages + all_messages

            # Scroll up to reveal earlier messages
            try:
                import pyautogui
                # Move mouse to message area center before scrolling
                win_rect = self._session.get_window_rect()
                if win_rect:
                    scroll_x = win_rect[0] + bb.x + bb.w // 2
                    scroll_y = win_rect[1] + bb.y + bb.h // 2
                    pyautogui.moveTo(scroll_x, scroll_y)
                pyautogui.scroll(5)  # Scroll up
                time.sleep(SCROLL_SETTLE_TIME)
            except Exception as e:
                logger.debug("Scroll failed: %s", e)
                break

        # If we never found last_seen after scrolling, return everything
        # (better to have duplicates than miss messages)
        if not found_last_seen and all_messages:
            self.log_message.emit(
                f"Could not find last seen message in '{chat_name}', "
                f"returning all {len(all_messages)} visible messages"
            )

        return all_messages

    def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep in small increments to allow stopping."""
        end = time.time() + seconds
        while self._running and time.time() < end:
            time.sleep(min(0.5, max(0, end - time.time())))
