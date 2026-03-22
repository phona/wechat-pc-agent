"""Three-layer vision perception for WeChat PC.

Layer 1: Pixel diff — per-region change detection (free, every 1.5s)
Layer 2: Lightweight model — text extraction from changed regions (cheap)
Layer 3: VLM — initial calibration + fallback for images/failures (expensive, rare)
"""

from .circuit_breaker import CircuitBreaker
from .diff_tracker import RegionDiffTracker, UnreadBadgeDetector
from .light_client import LightClient
from .perception import VisionPerception
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
from .vlm_client import VLMClient

__all__ = [
    "BoundingBox",
    "ChatEntry",
    "CircuitBreaker",
    "LightClient",
    "OCRResult",
    "RegionChangeEvent",
    "RegionDiffTracker",
    "RegionType",
    "TrackedRegion",
    "UIElement",
    "UIState",
    "UnreadBadgeDetector",
    "VLMClient",
    "VisionPerception",
]
