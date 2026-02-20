"""Decision layer interfaces -- implement these to swap threat/engagement strategies."""

from __future__ import annotations

from typing import Protocol

from ..types import ThreatAssessment, Track


class ThreatAssessorProtocol(Protocol):
    """评估跟踪目标的威胁等级。"""

    def assess(self, tracks: list[Track]) -> list[ThreatAssessment]: ...


class EngagementQueueProtocol(Protocol):
    """根据威胁评估结果维护交战优先队列。"""

    def update(self, assessments: list[ThreatAssessment]) -> None: ...
