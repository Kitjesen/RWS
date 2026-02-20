"""
配置包 — 按领域拆分，此 __init__ 保持向后兼容。

所有 ``from ..config import X`` 的既有代码无需修改。
"""

from .api import VideoStreamCfg
from .control import (
    AdaptivePIDConfig,
    BallisticConfig,
    GimbalControllerConfig,
    LeadAngleConfig,
    PIDConfig,
    TrajectoryPlannerConfig,
)
from .decision import EngagementConfig, ThreatWeightsConfig
from .environment import CameraConfig, EnvironmentConfig, ProjectileConfig
from .hardware import DriverLimitsConfig, RangefinderConfig
from .loader import SystemConfig, default_controller_config, load_config, save_config
from .perception import DetectorConfig, SelectorConfig, SelectorWeights
from .safety import SafetyConfig, SafetyInterlockCfg, SafetyZoneConfig

__all__ = [
    "AdaptivePIDConfig",
    "BallisticConfig",
    "CameraConfig",
    "DetectorConfig",
    "DriverLimitsConfig",
    "EngagementConfig",
    "EnvironmentConfig",
    "GimbalControllerConfig",
    "LeadAngleConfig",
    "PIDConfig",
    "ProjectileConfig",
    "RangefinderConfig",
    "SafetyConfig",
    "SafetyInterlockCfg",
    "SafetyZoneConfig",
    "SelectorConfig",
    "SelectorWeights",
    "SystemConfig",
    "ThreatWeightsConfig",
    "TrajectoryPlannerConfig",
    "VideoStreamCfg",
    "default_controller_config",
    "load_config",
    "save_config",
]
