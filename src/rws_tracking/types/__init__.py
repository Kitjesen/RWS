"""
类型定义包 — 按领域拆分，此 __init__ 保持向后兼容。

所有 ``from ..types import X`` 的既有代码无需修改。
"""

from .ballistic import BallisticSolution, EnvironmentParams, LeadAngle, ProjectileParams
from .common import BoundingBox, TrackState
from .control import (
    AxisFeedback,
    CameraIntrinsics,
    ControlCommand,
    GimbalFeedback,
    MountCalibration,
    TargetError,
)
from .decision import ThreatAssessment
from .hardware import BodyState, RangefinderReading
from .perception import Detection, TargetObservation, Track
from .safety import SafetyStatus, SafetyZone

__all__ = [
    "AxisFeedback",
    "BallisticSolution",
    "BodyState",
    "BoundingBox",
    "CameraIntrinsics",
    "ControlCommand",
    "Detection",
    "EnvironmentParams",
    "GimbalFeedback",
    "LeadAngle",
    "MountCalibration",
    "ProjectileParams",
    "RangefinderReading",
    "SafetyStatus",
    "SafetyZone",
    "TargetError",
    "TargetObservation",
    "ThreatAssessment",
    "Track",
    "TrackState",
]
