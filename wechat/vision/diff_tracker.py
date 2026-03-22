"""Layer 1: Per-region pixel diff tracking and unread badge detection."""

from __future__ import annotations

import numpy as np

from .types import BoundingBox, RegionChangeEvent, RegionType, TrackedRegion


class RegionDiffTracker:
    """Per-region pixel diff tracking."""

    def __init__(self, threshold: float = 0.02) -> None:
        self._threshold = threshold
        self._regions: dict[str, TrackedRegion] = {}

    def set_regions(self, regions: list[TrackedRegion]) -> None:
        """Register regions to track."""
        self._regions = {r.id: r for r in regions}

    def add_region(self, region: TrackedRegion) -> None:
        self._regions[region.id] = region

    def get_region(self, region_id: str) -> TrackedRegion | None:
        return self._regions.get(region_id)

    @property
    def regions(self) -> dict[str, TrackedRegion]:
        return self._regions

    def check_all(self, full_frame: np.ndarray) -> list[RegionChangeEvent]:
        """Compare all tracked regions against their baselines.

        Args:
            full_frame: Full screenshot as numpy array (RGB).

        Returns:
            List of regions that changed beyond threshold.
        """
        changed = []
        for region in self._regions.values():
            bb = region.bbox
            # Crop from full frame (numpy slice is free)
            crop = full_frame[bb.y:bb.y + bb.h, bb.x:bb.x + bb.w]
            if crop.size == 0:
                continue

            diff = self._compute_diff(region, crop)
            if diff > self._threshold:
                changed.append(RegionChangeEvent(
                    region=region,
                    diff_ratio=diff,
                    cropped_frame=crop.copy(),
                ))
        return changed

    def update_baseline(self, region_id: str, frame: np.ndarray) -> None:
        """Set or update the pixel baseline for a region."""
        region = self._regions.get(region_id)
        if region:
            region.baseline = self._to_gray(frame).copy()

    def init_baselines(self, full_frame: np.ndarray) -> None:
        """Initialize all baselines from a full screenshot."""
        for region in self._regions.values():
            bb = region.bbox
            crop = full_frame[bb.y:bb.y + bb.h, bb.x:bb.x + bb.w]
            if crop.size > 0:
                region.baseline = self._to_gray(crop).copy()

    def _compute_diff(self, region: TrackedRegion, crop: np.ndarray) -> float:
        """Compute mean diff ratio between crop and baseline."""
        if region.baseline is None:
            region.baseline = self._to_gray(crop).copy()
            return 0.0

        gray = self._to_gray(crop)
        baseline = region.baseline

        if gray.shape != baseline.shape:
            region.baseline = gray.copy()
            return 1.0

        diff = np.abs(gray.astype(np.float32) - baseline.astype(np.float32))
        return float(np.mean(diff) / 255.0)

    @staticmethod
    def _to_gray(img: np.ndarray) -> np.ndarray:
        if len(img.shape) == 3 and img.shape[2] >= 3:
            return np.mean(img[:, :, :3], axis=2).astype(np.uint8)
        return img


class UnreadBadgeDetector:
    """Detect WeChat red unread badges via RGB color thresholding."""

    # WeChat badge color is approximately #FA5151
    HUE_LOW = 0
    HUE_HIGH = 10
    SAT_MIN = 120
    VAL_MIN = 150
    MIN_PIXEL_COUNT = 15

    @staticmethod
    def has_badge(pixels: np.ndarray) -> bool:
        """Check if a cropped sidebar row contains a red unread badge.

        Args:
            pixels: RGB numpy array of the sidebar row.
        """
        if pixels.size == 0 or len(pixels.shape) < 3:
            return False

        r, g, b = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]

        # Simple RGB thresholding for red badge
        # Red channel high, green and blue low
        red_mask = (r > 180) & (g < 120) & (b < 120)
        red_count = int(np.sum(red_mask))
        return red_count >= UnreadBadgeDetector.MIN_PIXEL_COUNT

    @staticmethod
    def estimate_count(pixels: np.ndarray) -> int | None:
        """Estimate badge count from pixel area. None = just a dot."""
        if pixels.size == 0 or len(pixels.shape) < 3:
            return None
        r, g, b = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
        red_mask = (r > 180) & (g < 120) & (b < 120)
        red_count = int(np.sum(red_mask))
        if red_count < UnreadBadgeDetector.MIN_PIXEL_COUNT:
            return None
        # Large badge = has number, small = just dot
        if red_count > 100:
            return None  # Has number but we can't read it without OCR
        return None
