"""跨领域共享的基础类型。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TrackState(str, Enum):
    """跟踪状态枚举，跨 decision/control/pipeline 共享。"""

    SEARCH = "search"
    TRACK = "track"
    LOCK = "lock"
    LOST = "lost"


@dataclass(frozen=True)
class BoundingBox:
    x: float
    y: float
    w: float
    h: float

    @property
    def area(self) -> float:
        return max(self.w, 0.0) * max(self.h, 0.0)

    @property
    def center(self) -> tuple[float, float]:
        return self.x + self.w * 0.5, self.y + self.h * 0.5
