"""控制层数据类型：反馈、指令、误差、相机/安装参数。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AxisFeedback:
    """单轴（yaw 或 pitch）反馈，用于双轴云台两路独立通信。"""

    angle_deg: float
    rate_dps: float


@dataclass
class GimbalFeedback:
    timestamp: float
    yaw_deg: float
    pitch_deg: float
    yaw_rate_dps: float
    pitch_rate_dps: float


@dataclass
class ControlCommand:
    timestamp: float
    yaw_rate_cmd_dps: float
    pitch_rate_cmd_dps: float
    metadata: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class TargetError:
    timestamp: float
    yaw_error_deg: float
    pitch_error_deg: float
    target_id: int | None


@dataclass(frozen=True)
class CameraIntrinsics:
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float


@dataclass(frozen=True)
class MountCalibration:
    yaw_bias_deg: float = 0.0
    pitch_bias_deg: float = 0.0
