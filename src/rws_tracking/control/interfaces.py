"""Control layer interfaces -- implement these to swap control algorithms."""

from __future__ import annotations

from typing import Protocol

from ..types import (
    BallisticSolution,
    BodyState,
    BoundingBox,
    ControlCommand,
    GimbalFeedback,
    LeadAngle,
    TargetError,
    TargetObservation,
    TrackState,
)


class GimbalController(Protocol):
    """
    Takes a target observation and gimbal feedback, returns a control command.

    To implement your own controller:
        1. Create a class with a ``compute_command`` method matching this signature.
        2. Inject it into ``VisionGimbalPipeline`` via the ``controller`` parameter.
    """

    def compute_command(
        self,
        target: TargetObservation | None,
        feedback: GimbalFeedback,
        timestamp: float,
        body_state: BodyState | None = None,
    ) -> ControlCommand: ...

    def reset(self) -> None: ...


class BallisticSolverProtocol(Protocol):
    """弹道解算：给定距离，计算飞行时间、下坠补偿、风偏等。"""

    def solve(self, distance_m: float) -> BallisticSolution: ...


class LeadCalculatorProtocol(Protocol):
    """射击提前量：根据目标运动状态计算偏航/俯仰提前角。"""

    def compute(self, target: TargetObservation) -> LeadAngle: ...


class TrajectoryPlannerProtocol(Protocol):
    """轨迹规划：对控制指令做加速度/急动度约束平滑。"""

    def plan(
        self, command: ControlCommand, feedback: GimbalFeedback, timestamp: float
    ) -> ControlCommand: ...


class DistanceFusionProtocol(Protocol):
    """距离融合：激光优先 + bbox 估距兜底。"""

    def fuse(
        self,
        laser_reading: object | None,
        bbox: BoundingBox,
        timestamp: float,
    ) -> float: ...


class StateMachineProtocol(Protocol):
    """跟踪状态机：SEARCH → TRACK → LOCK → LOST 状态转移。

    control 层定义此协议，decision 层提供实现（TrackStateMachine）。
    """

    @property
    def state(self) -> TrackState: ...

    def update(self, error: TargetError | None, timestamp: float) -> TrackState: ...
