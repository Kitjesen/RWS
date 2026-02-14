"""
Configuration dataclasses with YAML load/save support.

Usage:
    cfg = load_config("config.yaml")
    save_config(cfg, "config_backup.yaml")
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

logger = logging.getLogger(__name__)

import yaml


# ---------------------------------------------------------------------------
# Selector
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SelectorWeights:
    confidence: float = 0.35
    size: float = 0.20
    center_proximity: float = 0.20
    track_age: float = 0.15
    class_weight: float = 0.10
    switch_penalty: float = 0.30


@dataclass(frozen=True)
class SelectorConfig:
    weights: SelectorWeights = SelectorWeights()
    min_hold_time_s: float = 0.4
    delta_threshold: float = 0.12
    preferred_classes: Optional[Dict[str, float]] = None
    age_norm_frames: int = 60  # 年龄归一化帧数

    def class_weights(self) -> Dict[str, float]:
        if self.preferred_classes is None:
            return {}
        return self.preferred_classes


# ---------------------------------------------------------------------------
# PID
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PIDConfig:
    kp: float
    ki: float
    kd: float
    integral_limit: float
    output_limit: float
    derivative_lpf_alpha: float = 0.3
    feedforward_kv: float = 0.0  # velocity feedforward gain (deg/s per deg/s)


# ---------------------------------------------------------------------------
# Ballistic Compensation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BallisticConfig:
    enabled: bool = False
    model_type: str = "simple"  # "simple" | "table"
    # Simple 模型参数
    target_height_m: float = 1.8
    quadratic_a: float = 0.001
    quadratic_b: float = 0.01
    quadratic_c: float = 0.0
    # Table 模型参数
    distance_table: Tuple[float, ...] = (5.0, 10.0, 15.0, 20.0, 25.0, 30.0)
    compensation_table: Tuple[float, ...] = (0.1, 0.4, 0.9, 1.6, 2.5, 3.6)


# ---------------------------------------------------------------------------
# Adaptive PID
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AdaptivePIDConfig:
    enabled: bool = False
    scheduler_type: str = "error_based"  # "error_based" | "distance_based"
    # Error-based 参数
    low_error_threshold_deg: float = 2.0
    high_error_threshold_deg: float = 10.0
    low_error_multiplier: float = 0.8
    high_error_multiplier: float = 1.5
    # Distance-based 参数
    near_distance_m: float = 5.0
    far_distance_m: float = 30.0
    near_multiplier: float = 1.0
    far_multiplier: float = 1.3
    bbox_area_max: float = 50000.0  # bbox 面积归一化上限 (px^2)
    ki_distance_scale: float = 0.8  # 远距离时 ki 缩放系数


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GimbalControllerConfig:
    yaw_pid: PIDConfig
    pitch_pid: PIDConfig
    max_rate_dps: float = 180.0
    command_lpf_alpha: float = 0.4
    lock_error_threshold_deg: float = 0.8
    lock_hold_time_s: float = 0.4
    predict_timeout_s: float = 0.25
    lost_timeout_s: float = 1.5
    max_track_error_timeout_s: float = 5.0
    high_error_multiplier: float = 5.0  # 判断"误差过大"的倍数 (× lock_error_threshold_deg)
    scan_pattern: Tuple[float, float] = (40.0, 20.0)
    scan_freq_hz: float = 0.15  # 扫描正弦波频率 (Hz)
    scan_yaw_scale: float = 1.0  # yaw 幅度相对 scan_pattern[0] 的系数
    scan_pitch_scale: float = 0.3  # pitch 幅度相对 scan_pattern[1] 的系数
    scan_pitch_freq_ratio: float = 0.7  # pitch 频率相对 yaw 的比例
    latency_compensation_s: float = 0.0  # estimated pipeline latency
    ballistic: BallisticConfig = BallisticConfig()
    adaptive_pid: AdaptivePIDConfig = AdaptivePIDConfig()


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CameraConfig:
    width: int = 1280
    height: int = 720
    fx: float = 970.0
    fy: float = 965.0
    cx: float = 640.0
    cy: float = 360.0
    distortion_k1: float = 0.0
    distortion_k2: float = 0.0
    distortion_p1: float = 0.0
    distortion_p2: float = 0.0
    distortion_k3: float = 0.0
    mount_roll_deg: float = 0.0
    mount_pitch_deg: float = 0.0
    mount_yaw_deg: float = 0.0


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DetectorConfig:
    model_path: str = "yolo11n.pt"
    confidence_threshold: float = 0.45
    nms_iou_threshold: float = 0.45
    img_size: int = 640
    device: str = ""
    tracker: str = "botsort.yaml"  # BoT-SORT | ByteTrack tracker config
    class_whitelist: Tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Hardware / Driver limits
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DriverLimitsConfig:
    yaw_min_deg: float = -160.0
    yaw_max_deg: float = 160.0
    pitch_min_deg: float = -45.0
    pitch_max_deg: float = 75.0
    max_rate_dps: float = 240.0
    deadband_dps: float = 0.2
    inertia_time_constant_s: float = 0.05
    static_friction_dps: float = 0.5
    coulomb_friction_dps: float = 2.0


# ---------------------------------------------------------------------------
# Top-level system config
# ---------------------------------------------------------------------------

@dataclass
class SystemConfig:
    camera: CameraConfig = CameraConfig()
    detector: DetectorConfig = DetectorConfig()
    selector: SelectorConfig = SelectorConfig()
    controller: Optional[GimbalControllerConfig] = None
    driver_limits: DriverLimitsConfig = DriverLimitsConfig()

    def __post_init__(self) -> None:
        if self.controller is None:
            self.controller = default_controller_config()


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

def default_controller_config() -> GimbalControllerConfig:
    return GimbalControllerConfig(
        yaw_pid=PIDConfig(
            kp=5.0, ki=0.4, kd=0.35,
            integral_limit=40.0, output_limit=180.0,
            derivative_lpf_alpha=0.4,
            feedforward_kv=0.75,
        ),
        pitch_pid=PIDConfig(
            kp=5.5, ki=0.35, kd=0.35,
            integral_limit=40.0, output_limit=180.0,
            derivative_lpf_alpha=0.4,
            feedforward_kv=0.70,
        ),
        command_lpf_alpha=0.75,
        latency_compensation_s=0.033,  # ~1 frame at 30Hz
    )


# ---------------------------------------------------------------------------
# YAML load / save
# ---------------------------------------------------------------------------

def _warn_unknown_keys(section: str, data: Dict[str, Any], cls: type) -> None:
    """Warn about keys in YAML that don't match any dataclass field."""
    known = set(cls.__dataclass_fields__.keys())
    for k in data:
        if k not in known:
            logger.warning("config.yaml [%s]: unknown key '%s' (ignored)", section, k)


def _nested_dict_to_config(data: Dict[str, Any]) -> SystemConfig:
    """Convert a flat/nested dict (from YAML) into SystemConfig."""
    cam_d = data.get("camera", {})
    det_d = data.get("detector", {})
    sel_d = data.get("selector", {})
    ctrl_d = data.get("controller", {})
    drv_d = data.get("driver_limits", {})

    _warn_unknown_keys("camera", cam_d, CameraConfig)
    camera = CameraConfig(**{k: v for k, v in cam_d.items() if k in CameraConfig.__dataclass_fields__})

    wl = det_d.pop("class_whitelist", ())
    if isinstance(wl, list):
        wl = tuple(wl)
    _warn_unknown_keys("detector", det_d, DetectorConfig)
    detector = DetectorConfig(**{k: v for k, v in det_d.items() if k in DetectorConfig.__dataclass_fields__}, class_whitelist=wl)

    weights_d = sel_d.pop("weights", {})
    _warn_unknown_keys("selector.weights", weights_d, SelectorWeights)
    weights = SelectorWeights(**{k: v for k, v in weights_d.items() if k in SelectorWeights.__dataclass_fields__})
    preferred = sel_d.pop("preferred_classes", None)
    _warn_unknown_keys("selector", sel_d, SelectorConfig)
    selector = SelectorConfig(
        weights=weights,
        preferred_classes=preferred,
        **{k: v for k, v in sel_d.items() if k in SelectorConfig.__dataclass_fields__ and k not in ("weights", "preferred_classes")},
    )

    yaw_d = ctrl_d.pop("yaw_pid", {})
    pitch_d = ctrl_d.pop("pitch_pid", {})
    scan = ctrl_d.pop("scan_pattern", [40.0, 20.0])
    if isinstance(scan, list):
        scan = tuple(scan)

    # Parse ballistic config
    ballistic_d = ctrl_d.pop("ballistic", {})
    dist_table = ballistic_d.pop("distance_table", (5.0, 10.0, 15.0, 20.0, 25.0, 30.0))
    comp_table = ballistic_d.pop("compensation_table", (0.1, 0.4, 0.9, 1.6, 2.5, 3.6))
    if isinstance(dist_table, list):
        dist_table = tuple(dist_table)
    if isinstance(comp_table, list):
        comp_table = tuple(comp_table)
    _warn_unknown_keys("controller.ballistic", ballistic_d, BallisticConfig)
    ballistic = BallisticConfig(
        **{k: v for k, v in ballistic_d.items() if k in BallisticConfig.__dataclass_fields__},
        distance_table=dist_table,
        compensation_table=comp_table,
    )

    # Parse adaptive PID config
    adaptive_d = ctrl_d.pop("adaptive_pid", {})
    _warn_unknown_keys("controller.adaptive_pid", adaptive_d, AdaptivePIDConfig)
    adaptive_pid = AdaptivePIDConfig(**{k: v for k, v in adaptive_d.items() if k in AdaptivePIDConfig.__dataclass_fields__})

    _warn_unknown_keys("controller.yaw_pid", yaw_d, PIDConfig)
    _warn_unknown_keys("controller.pitch_pid", pitch_d, PIDConfig)
    yaw_pid = PIDConfig(**{k: v for k, v in yaw_d.items() if k in PIDConfig.__dataclass_fields__})
    pitch_pid = PIDConfig(**{k: v for k, v in pitch_d.items() if k in PIDConfig.__dataclass_fields__})
    _warn_unknown_keys("controller", ctrl_d, GimbalControllerConfig)
    controller = GimbalControllerConfig(
        yaw_pid=yaw_pid, pitch_pid=pitch_pid, scan_pattern=scan,
        ballistic=ballistic, adaptive_pid=adaptive_pid,
        **{k: v for k, v in ctrl_d.items() if k in GimbalControllerConfig.__dataclass_fields__ and k not in ("yaw_pid", "pitch_pid", "scan_pattern", "ballistic", "adaptive_pid")},
    )

    # Parse driver limits config
    _warn_unknown_keys("driver_limits", drv_d, DriverLimitsConfig)
    driver_limits = DriverLimitsConfig(**{k: v for k, v in drv_d.items() if k in DriverLimitsConfig.__dataclass_fields__})

    return SystemConfig(
        camera=camera, detector=detector, selector=selector,
        controller=controller, driver_limits=driver_limits,
    )


def load_config(path: Union[str, Path]) -> SystemConfig:
    """Load SystemConfig from a YAML file."""
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return _nested_dict_to_config(data)


def save_config(cfg: SystemConfig, path: Union[str, Path]) -> None:
    """Save SystemConfig to a YAML file."""
    d = asdict(cfg)
    # Convert tuples to lists for YAML readability
    if "scan_pattern" in d.get("controller", {}):
        d["controller"]["scan_pattern"] = list(d["controller"]["scan_pattern"])
    if "class_whitelist" in d.get("detector", {}):
        d["detector"]["class_whitelist"] = list(d["detector"]["class_whitelist"])

    # Convert ballistic config tuples to lists
    if "ballistic" in d.get("controller", {}):
        ballistic = d["controller"]["ballistic"]
        if "distance_table" in ballistic:
            ballistic["distance_table"] = list(ballistic["distance_table"])
        if "compensation_table" in ballistic:
            ballistic["compensation_table"] = list(ballistic["compensation_table"])

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(d, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
