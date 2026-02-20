"""Safety layer interfaces -- implement these to swap safety evaluation strategies."""

from __future__ import annotations

from typing import Protocol

from ..types import SafetyStatus


class SafetyEvaluatorProtocol(Protocol):
    """安全系统统一评估接口。"""

    def evaluate(
        self,
        yaw_deg: float,
        pitch_deg: float,
        target_locked: bool,
        lock_duration_s: float,
        target_distance_m: float,
    ) -> SafetyStatus: ...

    def get_speed_factor(self, yaw_deg: float, pitch_deg: float) -> float: ...
