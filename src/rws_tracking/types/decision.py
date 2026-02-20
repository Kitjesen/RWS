"""决策层数据类型：威胁评估结果。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThreatAssessment:
    """单目标威胁评估结果。"""

    track_id: int = 0
    threat_score: float = 0.0
    distance_score: float = 0.0
    velocity_score: float = 0.0
    class_score: float = 0.0
    heading_score: float = 0.0
    priority_rank: int = 0
