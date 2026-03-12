"""
配置包 — 按领域拆分，此 __init__ 保持向后兼容。

所有 ``from ..config import X`` 的既有代码无需修改。
"""

from .api import VideoStreamCfg, VideoStreamConfig
from .control import (
    AdaptivePIDConfig,
    BallisticConfig,
    GimbalControllerConfig,
    LeadAngleConfig,
    MPCConfig,
    PIDConfig,
    TrajectoryPlannerConfig,
)
from .decision import EngagementConfig, ThreatWeightsConfig
from .environment import CameraConfig, EnvironmentConfig, ProjectileConfig
from .hardware import DriverLimitsConfig, RangefinderConfig
from .loader import SystemConfig, default_controller_config, load_config, save_config
from .perception import DetectorConfig, SelectorConfig, SelectorWeights
from .safety import SafetyConfig, SafetyInterlockCfg, SafetyInterlockConfig, SafetyZoneConfig
from .session import ClipConfig, LifecycleConfig, SessionConfig

__all__ = [
    "AdaptivePIDConfig",
    "ClipConfig",
    "LifecycleConfig",
    "SessionConfig",
    "BallisticConfig",
    "CameraConfig",
    "DetectorConfig",
    "DriverLimitsConfig",
    "EngagementConfig",
    "EnvironmentConfig",
    "GimbalControllerConfig",
    "LeadAngleConfig",
    "MPCConfig",
    "PIDConfig",
    "ProjectileConfig",
    "RangefinderConfig",
    "SafetyConfig",
    "SafetyInterlockCfg",
    "SafetyInterlockConfig",
    "SafetyZoneConfig",
    "SelectorConfig",
    "SelectorWeights",
    "SystemConfig",
    "ThreatWeightsConfig",
    "TrajectoryPlannerConfig",
    "VideoStreamCfg",
    "VideoStreamConfig",
    "default_controller_config",
    "load_config",
    "save_config",
]
