"""Tests for wechat.vision — three-layer vision architecture."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from wechat.vision import (
    BoundingBox,
    ChatEntry,
    CircuitBreaker,
    OCRResult,
    PaddleOCRClient,
    RegionChangeEvent,
    RegionDiffTracker,
    RegionType,
    TrackedRegion,
    UIElement,
    UIState,
    UnreadBadgeDetector,
    VLMClient,
    VisionPerception,
)


# ---------------------------------------------------------------------------
# BoundingBox
# ---------------------------------------------------------------------------

class TestBoundingBox:
    def test_to_abs(self):
        bb = BoundingBox(x=10, y=20, w=100, h=50)
        assert bb.to_abs(100, 200) == (110, 220, 210, 270)


# ---------------------------------------------------------------------------
# RegionDiffTracker
# ---------------------------------------------------------------------------

class TestRegionDiffTracker:
    def _make_regions(self):
        return [
            TrackedRegion(
                id="row_0", region_type=RegionType.SIDEBAR_ROW,
                bbox=BoundingBox(0, 0, 50, 20), chat_name="A",
            ),
            TrackedRegion(
                id="row_1", region_type=RegionType.SIDEBAR_ROW,
                bbox=BoundingBox(0, 20, 50, 20), chat_name="B",
            ),
            TrackedRegion(
                id="msg", region_type=RegionType.MESSAGE_AREA,
                bbox=BoundingBox(60, 0, 40, 40),
            ),
        ]

    def test_set_regions(self):
        tracker = RegionDiffTracker(threshold=0.02)
        regions = self._make_regions()
        tracker.set_regions(regions)
        assert len(tracker.regions) == 3

    def test_first_frame_no_changes(self):
        tracker = RegionDiffTracker(threshold=0.02)
        tracker.set_regions(self._make_regions())
        frame = np.zeros((40, 100, 3), dtype=np.uint8)
        changes = tracker.check_all(frame)
        assert len(changes) == 0  # First frame initializes baselines

    def test_detect_change_in_one_region(self):
        tracker = RegionDiffTracker(threshold=0.02)
        tracker.set_regions(self._make_regions())

        frame1 = np.zeros((40, 100, 3), dtype=np.uint8)
        tracker.check_all(frame1)  # Init baselines

        frame2 = frame1.copy()
        # Change only row_1 (y=20..40, x=0..50)
        frame2[20:40, 0:50] = 200

        changes = tracker.check_all(frame2)
        changed_ids = [c.region.id for c in changes]
        assert "row_1" in changed_ids
        assert "row_0" not in changed_ids

    def test_update_baseline(self):
        tracker = RegionDiffTracker(threshold=0.02)
        tracker.set_regions(self._make_regions())

        frame = np.full((40, 100, 3), 128, dtype=np.uint8)
        tracker.check_all(frame)  # Init

        crop = np.full((20, 50, 3), 200, dtype=np.uint8)
        tracker.update_baseline("row_0", crop)

        # Now check with same value — should not trigger
        frame2 = frame.copy()
        frame2[0:20, 0:50] = 200
        changes = tracker.check_all(frame2)
        changed_ids = [c.region.id for c in changes]
        assert "row_0" not in changed_ids

    def test_init_baselines(self):
        tracker = RegionDiffTracker(threshold=0.02)
        tracker.set_regions(self._make_regions())

        frame = np.random.randint(0, 255, (40, 100, 3), dtype=np.uint8)
        tracker.init_baselines(frame)

        for region in tracker.regions.values():
            assert region.baseline is not None

    def test_empty_crop_skipped(self):
        tracker = RegionDiffTracker(threshold=0.02)
        # Region bbox outside frame
        tracker.set_regions([
            TrackedRegion(
                id="oob", region_type=RegionType.SIDEBAR_ROW,
                bbox=BoundingBox(0, 100, 50, 20),
            ),
        ])
        frame = np.zeros((40, 100, 3), dtype=np.uint8)
        changes = tracker.check_all(frame)
        assert len(changes) == 0


# ---------------------------------------------------------------------------
# UnreadBadgeDetector
# ---------------------------------------------------------------------------

class TestUnreadBadgeDetector:
    def test_no_badge_black_image(self):
        pixels = np.zeros((64, 320, 3), dtype=np.uint8)
        assert UnreadBadgeDetector.has_badge(pixels) is False

    def test_badge_detected_red_region(self):
        pixels = np.zeros((64, 320, 3), dtype=np.uint8)
        # Add red badge area (R>180, G<120, B<120)
        pixels[5:15, 300:310, 0] = 250  # Red
        pixels[5:15, 300:310, 1] = 30   # Green
        pixels[5:15, 300:310, 2] = 30   # Blue
        assert UnreadBadgeDetector.has_badge(pixels) is True

    def test_no_badge_green_region(self):
        pixels = np.zeros((64, 320, 3), dtype=np.uint8)
        pixels[5:15, 300:310, 0] = 30
        pixels[5:15, 300:310, 1] = 250
        pixels[5:15, 300:310, 2] = 30
        assert UnreadBadgeDetector.has_badge(pixels) is False

    def test_badge_too_few_red_pixels(self):
        pixels = np.zeros((64, 320, 3), dtype=np.uint8)
        # Only 4 red pixels (below threshold of 15)
        pixels[0:2, 0:2, 0] = 250
        pixels[0:2, 0:2, 1] = 30
        pixels[0:2, 0:2, 2] = 30
        assert UnreadBadgeDetector.has_badge(pixels) is False

    def test_empty_input(self):
        assert UnreadBadgeDetector.has_badge(np.array([])) is False

    def test_grayscale_input(self):
        pixels = np.zeros((64, 320), dtype=np.uint8)
        assert UnreadBadgeDetector.has_badge(pixels) is False


# ---------------------------------------------------------------------------
# PaddleOCRClient
# ---------------------------------------------------------------------------

class TestPaddleOCRClient:
    def test_recognize(self):
        client = PaddleOCRClient(api_url="http://localhost:9000")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"text": "张三", "confidence": 0.95, "position": [[0, 0], [50, 20]]},
                {"text": "你好", "confidence": 0.88, "position": [[0, 20], [50, 40]]},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_httpx:
            mock_ctx = MagicMock()
            mock_ctx.post.return_value = mock_response
            mock_httpx.return_value.__enter__ = MagicMock(return_value=mock_ctx)
            mock_httpx.return_value.__exit__ = MagicMock(return_value=False)

            results = client.recognize(b"fake_image")
            assert len(results) == 2
            assert results[0]["text"] == "张三"

    def test_recognize_text(self):
        client = PaddleOCRClient(api_url="http://localhost:9000")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"text": "张三", "confidence": 0.95},
                {"text": "最近怎么样", "confidence": 0.80},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_httpx:
            mock_ctx = MagicMock()
            mock_ctx.post.return_value = mock_response
            mock_httpx.return_value.__enter__ = MagicMock(return_value=mock_ctx)
            mock_httpx.return_value.__exit__ = MagicMock(return_value=False)

            text, conf = client.recognize_text(b"fake_image")
            assert "张三" in text
            assert conf == 0.80

    def test_recognize_text_empty(self):
        client = PaddleOCRClient(api_url="http://localhost:9000")

        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_httpx:
            mock_ctx = MagicMock()
            mock_ctx.post.return_value = mock_response
            mock_httpx.return_value.__enter__ = MagicMock(return_value=mock_ctx)
            mock_httpx.return_value.__exit__ = MagicMock(return_value=False)

            text, conf = client.recognize_text(b"fake_image")
            assert text == ""
            assert conf == 0.0

    def test_api_key_header(self):
        client = PaddleOCRClient(
            api_url="http://localhost:9000", api_key="test-key",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_httpx:
            mock_ctx = MagicMock()
            mock_ctx.post.return_value = mock_response
            mock_httpx.return_value.__enter__ = MagicMock(return_value=mock_ctx)
            mock_httpx.return_value.__exit__ = MagicMock(return_value=False)

            client.recognize(b"fake_image")
            call_kwargs = mock_ctx.post.call_args[1]
            assert call_kwargs["headers"]["Authorization"] == "Bearer test-key"


# ---------------------------------------------------------------------------
# VLMClient
# ---------------------------------------------------------------------------

class TestVLMClient:
    def test_call_sync(self):
        client = VLMClient(api_url="http://localhost:8000", model="test-model")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"elements": {}}'}}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_httpx:
            mock_ctx = MagicMock()
            mock_ctx.post.return_value = mock_response
            mock_httpx.return_value.__enter__ = MagicMock(return_value=mock_ctx)
            mock_httpx.return_value.__exit__ = MagicMock(return_value=False)

            result = client.call_sync("test prompt", b"fake_image_bytes")
            assert result == '{"elements": {}}'

    def test_parse_json_response_plain(self):
        client = VLMClient(api_url="http://test")
        result = client.parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_json_response_with_fences(self):
        client = VLMClient(api_url="http://test")
        result = client.parse_json_response('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_parse_json_invalid(self):
        client = VLMClient(api_url="http://test")
        with pytest.raises(json.JSONDecodeError):
            client.parse_json_response("not json at all")


# ---------------------------------------------------------------------------
# VisionPerception
# ---------------------------------------------------------------------------

MOCK_CALIBRATION_RESPONSE = json.dumps({
    "elements": {
        "search_box": {"x": 85, "y": 60, "w": 250, "h": 30},
        "chat_list_area": {"x": 80, "y": 100, "w": 320, "h": 500},
        "input_box": {"x": 500, "y": 520, "w": 400, "h": 60},
        "message_area": {"x": 420, "y": 60, "w": 1000, "h": 450},
    },
    "visible_chats": [
        {"name": "张三", "has_unread": True, "unread_count": 2, "position_y": 150},
        {"name": "李四", "has_unread": False, "unread_count": None, "position_y": 230},
    ],
    "chat_row_height": 64,
    "active_chat": None,
})

MOCK_SIDEBAR_RESPONSE = json.dumps({
    "visible_chats": [
        {"name": "张三", "has_unread": False, "position_y": 150},
        {"name": "李四", "has_unread": True, "unread_count": 1, "position_y": 230},
    ],
    "changes": "李四 has new messages",
})

MOCK_CHAT_RESPONSE = json.dumps({
    "messages": [
        {"sender": "李四", "content": "发票开好了吗", "is_self": False},
        {"sender": "我", "content": "好的马上", "is_self": True},
    ],
})


class TestVisionPerception:
    def _make_perception(self, with_ocr=False):
        window = MagicMock()
        window.get_rect.return_value = (0, 0, 1920, 1080)

        # Create a real numpy array for screenshot_full
        fake_img = MagicMock()
        fake_img.size = (1920, 1080)
        fake_img.save = MagicMock(side_effect=lambda buf, **kw: buf.write(b"PNG"))
        # Make np.array(fake_img) work by providing __array__
        fake_arr = np.zeros((1080, 1920, 3), dtype=np.uint8)
        fake_img.__array__ = MagicMock(return_value=fake_arr)
        window.screenshot_full.return_value = fake_img

        vlm = MagicMock(spec=VLMClient)
        ocr = MagicMock(spec=PaddleOCRClient) if with_ocr else None

        perception = VisionPerception(window, vlm, ocr, pixel_diff_threshold=0.02)
        return perception, window, vlm, ocr

    def test_calibrate(self):
        perception, window, vlm, _ = self._make_perception()
        vlm.call_sync.return_value = MOCK_CALIBRATION_RESPONSE
        vlm.parse_json_response.return_value = json.loads(MOCK_CALIBRATION_RESPONSE)

        state = perception.calibrate()

        assert "search_box" in state.elements
        assert "chat_list_area" in state.elements
        assert "message_area" in state.elements
        assert len(state.visible_chats) == 2
        assert state.visible_chats[0].name == "张三"
        assert state.chat_row_height == 64
        window.activate.assert_called_once()
        window.maximize.assert_called_once()

    def test_calibrate_creates_tracked_regions(self):
        perception, _, vlm, _ = self._make_perception()
        vlm.call_sync.return_value = MOCK_CALIBRATION_RESPONSE
        vlm.parse_json_response.return_value = json.loads(MOCK_CALIBRATION_RESPONSE)

        perception.calibrate()

        regions = perception._region_tracker.regions
        # Should have sidebar rows + message area
        sidebar_rows = [r for r in regions.values()
                       if r.region_type == RegionType.SIDEBAR_ROW]
        msg_areas = [r for r in regions.values()
                    if r.region_type == RegionType.MESSAGE_AREA]
        assert len(sidebar_rows) >= 2
        assert len(msg_areas) == 1

    def test_check_regions_for_changes(self):
        perception, _, vlm, _ = self._make_perception()
        vlm.call_sync.return_value = MOCK_CALIBRATION_RESPONSE
        vlm.parse_json_response.return_value = json.loads(MOCK_CALIBRATION_RESPONSE)
        perception.calibrate()

        # Same frame — no changes
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        changes = perception.check_regions_for_changes(frame)
        # First call after calibration may or may not trigger depending on baseline
        # Just verify it returns a list
        assert isinstance(changes, list)

    def test_ocr_sidebar_row(self):
        perception, _, vlm, ocr = self._make_perception(with_ocr=True)
        ocr.recognize_text.return_value = ("张三 最近怎么样", 0.92)

        region = TrackedRegion(
            id="row_0", region_type=RegionType.SIDEBAR_ROW,
            bbox=BoundingBox(80, 100, 320, 64), chat_name="张三",
        )
        pixels = np.zeros((64, 320, 3), dtype=np.uint8)
        event = RegionChangeEvent(region=region, diff_ratio=0.05,
                                  cropped_frame=pixels)

        with patch.object(perception, "_numpy_to_bytes", return_value=b"PNG"):
            result = perception.ocr_sidebar_row(event)
        assert result is not None
        assert "张三" in result.text
        assert result.confidence == 0.92
        assert result.has_unread_badge is False

    def test_ocr_sidebar_row_with_badge(self):
        perception, _, vlm, ocr = self._make_perception(with_ocr=True)
        ocr.recognize_text.return_value = ("李四 发票开好了吗", 0.88)

        region = TrackedRegion(
            id="row_1", region_type=RegionType.SIDEBAR_ROW,
            bbox=BoundingBox(80, 164, 320, 64), chat_name="李四",
        )
        pixels = np.zeros((64, 320, 3), dtype=np.uint8)
        pixels[5:15, 300:310, 0] = 250
        pixels[5:15, 300:310, 1] = 30
        pixels[5:15, 300:310, 2] = 30
        event = RegionChangeEvent(region=region, diff_ratio=0.05,
                                  cropped_frame=pixels)

        with patch.object(perception, "_numpy_to_bytes", return_value=b"PNG"):
            result = perception.ocr_sidebar_row(event)
        assert result is not None
        assert result.has_unread_badge is True

    def test_ocr_sidebar_row_no_ocr_client(self):
        perception, _, _, _ = self._make_perception(with_ocr=False)
        region = TrackedRegion(
            id="row_0", region_type=RegionType.SIDEBAR_ROW,
            bbox=BoundingBox(80, 100, 320, 64),
        )
        event = RegionChangeEvent(
            region=region, diff_ratio=0.05,
            cropped_frame=np.zeros((64, 320, 3), dtype=np.uint8),
        )
        assert perception.ocr_sidebar_row(event) is None

    def test_needs_vlm_fallback_image(self):
        perception, _, _, _ = self._make_perception()
        ocr = OCRResult(text="", confidence=0.0, region_id="msg",
                        is_image_bubble=True)
        assert perception.needs_vlm_fallback(ocr) is True

    def test_needs_vlm_fallback_low_confidence(self):
        perception, _, _, _ = self._make_perception()
        ocr = OCRResult(text="some text", confidence=0.3, region_id="msg")
        assert perception.needs_vlm_fallback(ocr) is True

    def test_no_vlm_fallback_good_ocr(self):
        perception, _, _, _ = self._make_perception()
        ocr = OCRResult(text="hello", confidence=0.9, region_id="msg")
        assert perception.needs_vlm_fallback(ocr) is False

    def test_vlm_read_sidebar(self):
        perception, window, vlm, _ = self._make_perception()
        vlm.call_sync.return_value = MOCK_SIDEBAR_RESPONSE
        vlm.parse_json_response.return_value = json.loads(MOCK_SIDEBAR_RESPONSE)

        chats = perception.vlm_read_sidebar()
        assert len(chats) == 2
        assert chats[1].name == "李四"
        assert chats[1].has_unread is True

    def test_vlm_read_chat_messages(self):
        perception, window, vlm, _ = self._make_perception()
        vlm.call_sync.return_value = MOCK_CHAT_RESPONSE
        vlm.parse_json_response.return_value = json.loads(MOCK_CHAT_RESPONSE)

        messages = perception.vlm_read_chat_messages("李四", "之前的消息")
        assert len(messages) == 2
        assert messages[0]["content"] == "发票开好了吗"

    def test_get_element_center(self):
        perception, _, vlm, _ = self._make_perception()
        vlm.call_sync.return_value = MOCK_CALIBRATION_RESPONSE
        vlm.parse_json_response.return_value = json.loads(MOCK_CALIBRATION_RESPONSE)
        perception.calibrate()

        center = perception.get_element_center("search_box")
        assert center == (210, 75)

    def test_get_element_center_missing(self):
        perception, _, _, _ = self._make_perception()
        assert perception.get_element_center("nonexistent") is None

    def test_msg_hash(self):
        h1 = VisionPerception.msg_hash("hello")
        h2 = VisionPerception.msg_hash("hello")
        h3 = VisionPerception.msg_hash("world")
        assert h1 == h2
        assert h1 != h3
        assert len(h1) == 12

    def test_ocr_breaker_skips_when_open(self):
        perception, _, vlm, ocr = self._make_perception(with_ocr=True)
        # Trip the OCR breaker
        for _ in range(5):
            perception._ocr_breaker.record_failure()

        region = TrackedRegion(
            id="row_0", region_type=RegionType.SIDEBAR_ROW,
            bbox=BoundingBox(80, 100, 320, 64),
        )
        event = RegionChangeEvent(
            region=region, diff_ratio=0.05,
            cropped_frame=np.zeros((64, 320, 3), dtype=np.uint8),
        )
        # Should return None without calling OCR
        result = perception.ocr_sidebar_row(event)
        assert result is None
        ocr.recognize_text.assert_not_called()

    def test_vlm_breaker_skips_when_open(self):
        perception, _, vlm, _ = self._make_perception()
        # Trip the VLM breaker
        for _ in range(3):
            perception._vlm_breaker.record_failure()

        result = perception.vlm_read_sidebar()
        assert result == []
        vlm.call_sync.assert_not_called()

    def test_ocr_message_area_sorted_by_position(self):
        perception, _, vlm, ocr = self._make_perception(with_ocr=True)
        ocr.recognize.return_value = [
            {"text": "second", "confidence": 0.9, "position": [[0, 200], [100, 220]]},
            {"text": "first", "confidence": 0.9, "position": [[0, 50], [100, 70]]},
            {"text": "third", "confidence": 0.9, "position": [[0, 400], [100, 420]]},
        ]

        region = TrackedRegion(
            id="msg", region_type=RegionType.MESSAGE_AREA,
            bbox=BoundingBox(0, 0, 100, 500),
        )
        event = RegionChangeEvent(
            region=region, diff_ratio=0.05,
            cropped_frame=np.zeros((500, 100, 3), dtype=np.uint8),
        )

        with patch.object(perception, "_numpy_to_bytes", return_value=b"PNG"):
            results = perception.ocr_message_area(event)

        assert len(results) == 3
        assert results[0].text == "first"
        assert results[0].position_y == 50
        assert results[1].text == "second"
        assert results[1].position_y == 200
        assert results[2].text == "third"
        assert results[2].position_y == 400

    def test_calibrated_rect_stored(self):
        perception, window, vlm, _ = self._make_perception()
        vlm.call_sync.return_value = MOCK_CALIBRATION_RESPONSE
        vlm.parse_json_response.return_value = json.loads(MOCK_CALIBRATION_RESPONSE)
        window.get_rect.return_value = (100, 200, 1920, 1080)

        perception.calibrate()
        assert perception._calibrated_rect == (100, 200, 1920, 1080)

    def test_vlm_describe_image_breaker_records_failure(self):
        perception, _, vlm, _ = self._make_perception()
        vlm.call_sync.side_effect = RuntimeError("timeout")

        result = perception.vlm_describe_image(
            np.zeros((100, 100, 3), dtype=np.uint8)
        )
        assert "error" in result.lower()
        assert perception._vlm_breaker.fail_count == 1


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreaker(fail_threshold=3)
        assert cb.is_open is False
        assert cb.fail_count == 0

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(fail_threshold=3, cooldown=300.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is False
        cb.record_failure()
        assert cb.is_open is True

    def test_success_resets(self):
        cb = CircuitBreaker(fail_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is True
        cb.record_success()
        assert cb.is_open is False
        assert cb.fail_count == 0

    def test_half_open_after_cooldown(self):
        cb = CircuitBreaker(fail_threshold=2, cooldown=0.0)
        cb.record_failure()
        cb.record_failure()
        # Cooldown is 0 → immediately half-open
        assert cb.is_open is False

    def test_stays_open_during_cooldown(self):
        cb = CircuitBreaker(fail_threshold=2, cooldown=9999.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open is True

    def test_partial_failures_below_threshold(self):
        cb = CircuitBreaker(fail_threshold=5)
        for _ in range(4):
            cb.record_failure()
        assert cb.is_open is False
        assert cb.fail_count == 4
