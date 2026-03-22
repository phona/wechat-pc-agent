"""Data types for the three-layer vision architecture."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

import numpy as np


class RegionType(Enum):
    SIDEBAR_ROW = auto()
    MESSAGE_AREA = auto()


@dataclass
class BoundingBox:
    """Pixel rectangle relative to the WeChat window."""
    x: int
    y: int
    w: int
    h: int

    def to_abs(self, win_x: int, win_y: int) -> tuple[int, int, int, int]:
        """Convert to absolute screen coords (left, top, right, bottom)."""
        return (win_x + self.x, win_y + self.y,
                win_x + self.x + self.w, win_y + self.y + self.h)


@dataclass
class UIElement:
    """A UI element with pixel coordinates."""
    name: str
    x: int
    y: int
    w: int
    h: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)


@dataclass
class ChatEntry:
    """A chat item in the sidebar."""
    name: str
    has_unread: bool = False
    unread_count: int | None = None
    position_y: int = 0
    row_bbox: BoundingBox | None = None
    last_preview: str = ""


@dataclass
class UIState:
    """Snapshot of the WeChat UI state."""
    elements: dict[str, UIElement] = field(default_factory=dict)
    visible_chats: list[ChatEntry] = field(default_factory=list)
    active_chat: str | None = None
    last_messages: list[dict] = field(default_factory=list)
    chat_row_height: int = 64
    timestamp: float = 0.0


@dataclass
class TrackedRegion:
    """A region tracked by pixel diff with its own baseline."""
    id: str
    region_type: RegionType
    bbox: BoundingBox
    chat_name: str | None = None
    baseline: np.ndarray | None = None


@dataclass
class RegionChangeEvent:
    """Output of Layer 1: a region that changed."""
    region: TrackedRegion
    diff_ratio: float
    cropped_frame: np.ndarray


@dataclass
class OCRResult:
    """Output of Layer 2: text extracted from a region."""
    text: str
    confidence: float
    region_id: str
    has_unread_badge: bool = False
    is_image_bubble: bool = False
    is_voice_bubble: bool = False
    position_y: int = 0
