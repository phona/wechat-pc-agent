"""Three-layer vision orchestrator for WeChat UI perception."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import time
from typing import Any

import numpy as np

from .circuit_breaker import CircuitBreaker
from .diff_tracker import RegionDiffTracker, UnreadBadgeDetector
from .ocr_client import PaddleOCRClient
from .types import (
    BoundingBox,
    ChatEntry,
    OCRResult,
    RegionChangeEvent,
    RegionType,
    TrackedRegion,
    UIElement,
    UIState,
)
from .vlm_client import (
    CALIBRATION_PROMPT,
    CHAT_READ_PROMPT,
    IMAGE_DESCRIBE_PROMPT,
    SIDEBAR_READ_PROMPT,
    VLMClient,
)

logger = logging.getLogger(__name__)


class VisionPerception:
    """Three-layer vision orchestrator for WeChat UI perception."""

    def __init__(
        self,
        window: Any,  # WeChatWindow
        vlm_client: VLMClient | None,
        ocr_client: PaddleOCRClient | None = None,
        pixel_diff_threshold: float = 0.02,
        ocr_breaker_threshold: int = 5,
        ocr_breaker_cooldown: float = 300.0,
        vlm_breaker_threshold: int = 3,
        vlm_breaker_cooldown: float = 600.0,
    ) -> None:
        self._window = window
        self._vlm = vlm_client
        self._ocr = ocr_client
        self._region_tracker = RegionDiffTracker(threshold=pixel_diff_threshold)
        self._state: UIState = UIState()
        self._ocr_breaker = CircuitBreaker(
            fail_threshold=ocr_breaker_threshold, cooldown=ocr_breaker_cooldown,
        )
        self._vlm_breaker = CircuitBreaker(
            fail_threshold=vlm_breaker_threshold, cooldown=vlm_breaker_cooldown,
        )
        self._calibrated_rect: tuple | None = None

    @property
    def state(self) -> UIState:
        return self._state

    # --- Layer 3: VLM calibration (startup) ---

    def calibrate(self) -> UIState:
        """Take a full screenshot and calibrate UI via VLM.

        After VLM identifies the layout, compute per-chat-row bounding boxes
        and register all regions with RegionDiffTracker.
        """
        if not self._vlm:
            raise RuntimeError("VLM client required for calibration")

        self._window.activate()
        self._window.maximize()
        time.sleep(0.5)

        img = self._window.screenshot_full()
        width, height = img.size
        img_bytes = self._image_to_bytes(img)

        prompt = CALIBRATION_PROMPT.format(width=width, height=height)
        logger.info("Calibrating UI via VLM (%dx%d)...", width, height)

        response = self._vlm.call_sync(prompt, img_bytes)
        data = self._vlm.parse_json_response(response)

        self._state = self._parse_ui_state(data)
        self._state.chat_row_height = data.get("chat_row_height", 64)
        self._state.timestamp = time.time()

        # Compute per-chat-row bounding boxes
        self._setup_tracked_regions()

        # Initialize all baselines from current screenshot
        full_frame = np.array(img)
        self._region_tracker.init_baselines(full_frame)

        # Store calibrated rect for change detection
        try:
            self._calibrated_rect = self._window.get_rect()
        except Exception:
            self._calibrated_rect = None

        # Cross-validate chat names with OCR if available
        if self._ocr:
            self._ocr_validate_chat_names(full_frame)

        logger.info(
            "Calibration complete: %d elements, %d chats, %d tracked regions",
            len(self._state.elements),
            len(self._state.visible_chats),
            len(self._region_tracker.regions),
        )
        return self._state

    def _setup_tracked_regions(self) -> None:
        """Create TrackedRegion objects from calibrated UI state."""
        regions: list[TrackedRegion] = []

        # Per-chat-row regions from chat_list_area
        chat_list = self._state.elements.get("chat_list_area")
        if chat_list:
            row_h = self._state.chat_row_height
            num_rows = max(len(self._state.visible_chats),
                          chat_list.h // row_h if row_h > 0 else 0)

            for i in range(num_rows):
                y_start = chat_list.y + i * row_h
                if y_start + row_h > chat_list.y + chat_list.h:
                    break
                bbox = BoundingBox(x=chat_list.x, y=y_start, w=chat_list.w, h=row_h)

                chat_name = None
                if i < len(self._state.visible_chats):
                    chat_name = self._state.visible_chats[i].name
                    self._state.visible_chats[i].row_bbox = bbox

                regions.append(TrackedRegion(
                    id=f"sidebar_row_{i}",
                    region_type=RegionType.SIDEBAR_ROW,
                    bbox=bbox,
                    chat_name=chat_name,
                ))

        # Message area region
        msg_area = self._state.elements.get("message_area")
        if msg_area:
            regions.append(TrackedRegion(
                id="message_area",
                region_type=RegionType.MESSAGE_AREA,
                bbox=BoundingBox(x=msg_area.x, y=msg_area.y,
                                 w=msg_area.w, h=msg_area.h),
            ))

        self._region_tracker.set_regions(regions)

    def _ocr_validate_chat_names(self, full_frame: np.ndarray) -> None:
        """Use OCR to cross-validate chat names from VLM calibration."""
        for region in self._region_tracker.regions.values():
            if region.region_type != RegionType.SIDEBAR_ROW:
                continue
            if not region.chat_name:
                continue

            bb = region.bbox
            crop = full_frame[bb.y:bb.y + bb.h, bb.x:bb.x + bb.w]
            if crop.size == 0:
                continue

            try:
                img_bytes = self._numpy_to_bytes(crop)
                text, conf = self._ocr.recognize_text(img_bytes)
                if conf > 0.7 and text:
                    # Use first line as chat name (top of row = name)
                    ocr_name = text.split("\n")[0].split(" ")[0].strip()
                    if ocr_name and ocr_name != region.chat_name:
                        logger.info(
                            "OCR corrected chat name: VLM='%s' OCR='%s'",
                            region.chat_name, ocr_name,
                        )
                        region.chat_name = ocr_name
            except Exception as e:
                logger.debug("OCR validation failed for %s: %s", region.id, e)

    # --- Layer 1: Per-region pixel diff ---

    def check_regions_for_changes(
        self, full_frame: np.ndarray | None = None,
    ) -> list[RegionChangeEvent]:
        """Check all tracked regions for pixel changes.

        Args:
            full_frame: If provided, use this frame. Otherwise screenshot.
        """
        if full_frame is None:
            full_frame = np.array(self._window.screenshot_full())
        return self._region_tracker.check_all(full_frame)

    # --- Layer 2: OCR on changed regions ---

    def ocr_sidebar_row(self, event: RegionChangeEvent) -> OCRResult | None:
        """OCR a changed sidebar row + detect red badge.

        Returns OCRResult with chat name, preview text, and unread status.
        Returns None if OCR unavailable or circuit breaker open.
        """
        if not self._ocr or self._ocr_breaker.is_open:
            return None

        pixels = event.cropped_frame
        has_badge = UnreadBadgeDetector.has_badge(pixels)

        try:
            img_bytes = self._numpy_to_bytes(pixels)
            text, conf = self._ocr.recognize_text(img_bytes)
            self._ocr_breaker.record_success()
        except Exception as e:
            logger.error("OCR sidebar row failed: %s", e)
            self._ocr_breaker.record_failure()
            return None

        return OCRResult(
            text=text,
            confidence=conf,
            region_id=event.region.id,
            has_unread_badge=has_badge,
        )

    def ocr_message_area(self, event: RegionChangeEvent) -> list[OCRResult]:
        """OCR the message area to extract new messages.

        Returns list of OCRResult, one per detected message block.
        Detects image bubbles (no text, large area) and voice bubbles (duration pattern).
        """
        if not self._ocr or self._ocr_breaker.is_open:
            return []

        pixels = event.cropped_frame

        try:
            img_bytes = self._numpy_to_bytes(pixels)
            results = self._ocr.recognize(img_bytes)
            self._ocr_breaker.record_success()
        except Exception as e:
            logger.error("OCR message area failed: %s", e)
            self._ocr_breaker.record_failure()
            return []

        ocr_results = []
        for item in results:
            text = item.get("text", "")
            conf = item.get("confidence", item.get("score", 0.0))

            # Extract y position from OCR position data
            pos = item.get("position", [])
            pos_y = 0
            if pos and isinstance(pos, list) and len(pos) >= 1:
                first_point = pos[0]
                if isinstance(first_point, (list, tuple)) and len(first_point) >= 2:
                    pos_y = int(first_point[1])

            is_voice = bool(re.match(r"^\d+[:'\"]\d{2}$", text.strip()))

            ocr_results.append(OCRResult(
                text=text,
                confidence=conf,
                region_id=event.region.id,
                is_voice_bubble=is_voice,
                position_y=pos_y,
            ))

        # If OCR returned very few results but the area has significant pixel
        # changes, it might be an image bubble
        if not ocr_results and event.diff_ratio > 0.1:
            ocr_results.append(OCRResult(
                text="",
                confidence=0.0,
                region_id=event.region.id,
                is_image_bubble=True,
            ))

        # Sort by vertical position so messages are in reading order
        ocr_results.sort(key=lambda r: r.position_y)

        return ocr_results

    # --- Layer 3: VLM fallback ---

    def vlm_describe_image(self, cropped_frame: np.ndarray) -> str:
        """Use VLM to describe an image message."""
        if not self._vlm or self._vlm_breaker.is_open:
            return "[Image - VLM unavailable]"

        try:
            img_bytes = self._numpy_to_bytes(cropped_frame)
            response = self._vlm.call_sync(IMAGE_DESCRIBE_PROMPT, img_bytes)
            self._vlm_breaker.record_success()
            return response.strip()
        except Exception as e:
            logger.error("VLM describe image failed: %s", e)
            self._vlm_breaker.record_failure()
            return "[Image - VLM error]"

    def vlm_read_sidebar(self) -> list[ChatEntry]:
        """Full VLM sidebar reading (fallback)."""
        if not self._vlm or self._vlm_breaker.is_open:
            return []

        try:
            img = self._window.screenshot_full()
            img_bytes = self._image_to_bytes(img)

            prev_state_json = json.dumps(
                {
                    "visible_chats": [
                        {"name": c.name, "has_unread": c.has_unread}
                        for c in self._state.visible_chats
                    ],
                    "active_chat": self._state.active_chat,
                },
                ensure_ascii=False,
            )

            prompt = SIDEBAR_READ_PROMPT.format(prev_state=prev_state_json)
            response = self._vlm.call_sync(prompt, img_bytes)
            data = self._vlm.parse_json_response(response)

            chats = self._parse_chat_entries(data.get("visible_chats", []))
            self._state.visible_chats = chats
            self._state.timestamp = time.time()
            self._vlm_breaker.record_success()
            return chats
        except Exception as e:
            logger.error("VLM read sidebar failed: %s", e)
            self._vlm_breaker.record_failure()
            return []

    def vlm_read_chat_messages(
        self, chat_name: str, last_seen_msg: str = "",
    ) -> list[dict]:
        """Full VLM message reading (fallback)."""
        if not self._vlm or self._vlm_breaker.is_open:
            return []

        try:
            img = self._window.screenshot_full()
            img_bytes = self._image_to_bytes(img)

            prompt = CHAT_READ_PROMPT.format(
                chat_name=chat_name,
                last_seen_msg=last_seen_msg[:50] if last_seen_msg else "",
            )

            response = self._vlm.call_sync(prompt, img_bytes)
            data = self._vlm.parse_json_response(response)

            messages = data.get("messages", [])
            self._state.last_messages = messages
            self._state.active_chat = chat_name
            self._state.timestamp = time.time()

            logger.info("VLM read %d messages from '%s'", len(messages), chat_name)
            self._vlm_breaker.record_success()
            return messages
        except Exception as e:
            logger.error("VLM read chat messages failed: %s", e)
            self._vlm_breaker.record_failure()
            return []

    # --- Decision logic ---

    def needs_vlm_fallback(self, ocr_result: OCRResult) -> bool:
        """Decide if VLM fallback is needed."""
        if ocr_result.is_image_bubble:
            return True
        if ocr_result.confidence < 0.5:
            return True
        if not ocr_result.text.strip():
            return True
        return False

    def update_baseline(self, region_id: str, full_frame: np.ndarray) -> None:
        """Update baseline for a region after processing."""
        region = self._region_tracker.get_region(region_id)
        if region:
            bb = region.bbox
            crop = full_frame[bb.y:bb.y + bb.h, bb.x:bb.x + bb.w]
            if crop.size > 0:
                self._region_tracker.update_baseline(region_id, crop)

    # --- Helpers ---

    def get_element_center(self, name: str) -> tuple[int, int] | None:
        """Get the screen-absolute center of a calibrated UI element."""
        el = self._state.elements.get(name)
        if not el:
            return None
        try:
            win_rect = self._window.get_rect()
            return (win_rect[0] + el.x + el.w // 2,
                    win_rect[1] + el.y + el.h // 2)
        except Exception:
            return el.center

    @staticmethod
    def _image_to_bytes(img: "PIL.Image.Image") -> bytes:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    @staticmethod
    def _numpy_to_bytes(arr: np.ndarray) -> bytes:
        from PIL import Image
        img = Image.fromarray(arr)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    @staticmethod
    def _parse_ui_state(data: dict) -> UIState:
        state = UIState()
        for name, coords in data.get("elements", {}).items():
            if coords:
                state.elements[name] = UIElement(
                    name=name,
                    x=coords.get("x", 0),
                    y=coords.get("y", 0),
                    w=coords.get("w", 0),
                    h=coords.get("h", 0),
                )
        state.visible_chats = VisionPerception._parse_chat_entries(
            data.get("visible_chats", [])
        )
        state.active_chat = data.get("active_chat")
        return state

    @staticmethod
    def _parse_chat_entries(entries: list[dict]) -> list[ChatEntry]:
        chats = []
        for entry in entries:
            chats.append(
                ChatEntry(
                    name=entry.get("name", ""),
                    has_unread=entry.get("has_unread", False),
                    unread_count=entry.get("unread_count"),
                    position_y=entry.get("position_y", 0),
                )
            )
        return chats

    @staticmethod
    def msg_hash(content: str) -> str:
        """Create a short hash of message content for dedup."""
        return hashlib.md5(content.encode("utf-8")).hexdigest()[:12]
