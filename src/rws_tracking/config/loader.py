"""SystemConfig 顶层聚合 + YAML load/save。"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from .api import VideoStreamCfg
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
from .perception import DetectorConfig, SelectorConfig, SelectorWeights
from .safety import SafetyConfig, SafetyInterlockCfg, SafetyZoneConfig
from .session import ClipConfig, LifecycleConfig, SessionConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Top-level system config
# ---------------------------------------------------------------------------


@dataclass
class SystemConfig:
    camera: CameraConfig = CameraConfig()
    detector: DetectorConfig = DetectorConfig()
    selector: SelectorConfig = SelectorConfig()
    controller: GimbalControllerConfig | None = None
    driver_limits: DriverLimitsConfig = DriverLimitsConfig()
    projectile: ProjectileConfig = ProjectileConfig()
    environment: EnvironmentConfig = EnvironmentConfig()
    lead_angle: LeadAngleConfig = LeadAngleConfig()
    trajectory: TrajectoryPlannerConfig = TrajectoryPlannerConfig()
    engagement: EngagementConfig = EngagementConfig()
    safety: SafetyConfig = SafetyConfig()
    rangefinder: RangefinderConfig = RangefinderConfig()
    video_stream: VideoStreamCfg = VideoStreamCfg()
    session: SessionConfig = SessionConfig()
    lifecycle: LifecycleConfig = LifecycleConfig()
    clip: ClipConfig = ClipConfig()

    def __post_init__(self) -> None:
        if self.controller is None:
            self.controller = default_controller_config()


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def default_controller_config() -> GimbalControllerConfig:
    return GimbalControllerConfig(
        yaw_pid=PIDConfig(
            kp=5.0,
            ki=0.4,
            kd=0.35,
            integral_limit=40.0,
            output_limit=180.0,
            derivative_lpf_alpha=0.4,
            feedforward_kv=0.75,
        ),
        pitch_pid=PIDConfig(
            kp=5.5,
            ki=0.35,
            kd=0.35,
            integral_limit=40.0,
            output_limit=180.0,
            derivative_lpf_alpha=0.4,
            feedforward_kv=0.70,
        ),
        command_lpf_alpha=0.75,
        latency_compensation_s=0.033,
    )


# ---------------------------------------------------------------------------
# YAML load / save
# ---------------------------------------------------------------------------


def _warn_unknown_keys(section: str, data: dict[str, Any], cls: type) -> None:
    known = set(cls.__dataclass_fields__.keys())
    for k in data:
        if k not in known:
            logger.warning("config.yaml [%s]: unknown key '%s' (ignored)", section, k)


def _nested_dict_to_config(data: dict[str, Any]) -> SystemConfig:
    """Convert a flat/nested dict (from YAML) into SystemConfig."""
    cam_d = data.get("camera", {})
    det_d = data.get("detector", {})
    sel_d = data.get("selector", {})
    ctrl_d = data.get("controller", {})
    drv_d = data.get("driver_limits", {})

    _warn_unknown_keys("camera", cam_d, CameraConfig)
    camera = CameraConfig(
        **{k: v for k, v in cam_d.items() if k in CameraConfig.__dataclass_fields__}
    )

    wl = det_d.pop("class_whitelist", ())
    if isinstance(wl, list):
        wl = tuple(wl)
    _warn_unknown_keys("detector", det_d, DetectorConfig)
    detector = DetectorConfig(
        **{k: v for k, v in det_d.items() if k in DetectorConfig.__dataclass_fields__},
        class_whitelist=wl,
    )

    weights_d = sel_d.pop("weights", {})
    _warn_unknown_keys("selector.weights", weights_d, SelectorWeights)
    weights = SelectorWeights(
        **{k: v for k, v in weights_d.items() if k in SelectorWeights.__dataclass_fields__}
    )
    preferred = sel_d.pop("preferred_classes", None)
    _warn_unknown_keys("selector", sel_d, SelectorConfig)
    selector = SelectorConfig(
        weights=weights,
        preferred_classes=preferred,
        **{
            k: v
            for k, v in sel_d.items()
            if k in SelectorConfig.__dataclass_fields__
            and k not in ("weights", "preferred_classes")
        },
    )

    yaw_d = ctrl_d.pop("yaw_pid", {})
    pitch_d = ctrl_d.pop("pitch_pid", {})
    scan = ctrl_d.pop("scan_pattern", [40.0, 20.0])
    if isinstance(scan, list):
        scan = tuple(scan)

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

    adaptive_d = ctrl_d.pop("adaptive_pid", {})
    _warn_unknown_keys("controller.adaptive_pid", adaptive_d, AdaptivePIDConfig)
    adaptive_pid = AdaptivePIDConfig(
        **{k: v for k, v in adaptive_d.items() if k in AdaptivePIDConfig.__dataclass_fields__}
    )

    mpc_d = ctrl_d.pop("mpc", {})
    _warn_unknown_keys("controller.mpc", mpc_d, MPCConfig)
    mpc = MPCConfig(**{k: v for k, v in mpc_d.items() if k in MPCConfig.__dataclass_fields__})

    _warn_unknown_keys("controller.yaw_pid", yaw_d, PIDConfig)
    _warn_unknown_keys("controller.pitch_pid", pitch_d, PIDConfig)
    yaw_pid = PIDConfig(**{k: v for k, v in yaw_d.items() if k in PIDConfig.__dataclass_fields__})
    pitch_pid = PIDConfig(
        **{k: v for k, v in pitch_d.items() if k in PIDConfig.__dataclass_fields__}
    )
    _warn_unknown_keys("controller", ctrl_d, GimbalControllerConfig)
    controller = GimbalControllerConfig(
        yaw_pid=yaw_pid,
        pitch_pid=pitch_pid,
        scan_pattern=scan,
        ballistic=ballistic,
        adaptive_pid=adaptive_pid,
        mpc=mpc,
        **{
            k: v
            for k, v in ctrl_d.items()
            if k in GimbalControllerConfig.__dataclass_fields__
            and k
            not in ("yaw_pid", "pitch_pid", "scan_pattern", "ballistic", "adaptive_pid", "mpc")
        },
    )

    _warn_unknown_keys("driver_limits", drv_d, DriverLimitsConfig)
    driver_limits = DriverLimitsConfig(
        **{k: v for k, v in drv_d.items() if k in DriverLimitsConfig.__dataclass_fields__}
    )

    proj_d = data.get("projectile", {})
    _warn_unknown_keys("projectile", proj_d, ProjectileConfig)
    projectile = ProjectileConfig(
        **{k: v for k, v in proj_d.items() if k in ProjectileConfig.__dataclass_fields__}
    )

    env_d = data.get("environment", {})
    _warn_unknown_keys("environment", env_d, EnvironmentConfig)
    environment = EnvironmentConfig(
        **{k: v for k, v in env_d.items() if k in EnvironmentConfig.__dataclass_fields__}
    )

    lead_d = data.get("lead_angle", {})
    _warn_unknown_keys("lead_angle", lead_d, LeadAngleConfig)
    lead_angle = LeadAngleConfig(
        **{k: v for k, v in lead_d.items() if k in LeadAngleConfig.__dataclass_fields__}
    )

    traj_d = data.get("trajectory", {})
    _warn_unknown_keys("trajectory", traj_d, TrajectoryPlannerConfig)
    trajectory = TrajectoryPlannerConfig(
        **{k: v for k, v in traj_d.items() if k in TrajectoryPlannerConfig.__dataclass_fields__}
    )

    engage_d = data.get("engagement", {})
    engage_weights_d = engage_d.pop("weights", {})
    _warn_unknown_keys("engagement.weights", engage_weights_d, ThreatWeightsConfig)
    engage_weights = ThreatWeightsConfig(
        **{
            k: v
            for k, v in engage_weights_d.items()
            if k in ThreatWeightsConfig.__dataclass_fields__
        }
    )
    _warn_unknown_keys("engagement", engage_d, EngagementConfig)
    engagement = EngagementConfig(
        weights=engage_weights,
        **{
            k: v
            for k, v in engage_d.items()
            if k in EngagementConfig.__dataclass_fields__ and k != "weights"
        },
    )

    safety_d = data.get("safety", {})
    safety_interlock_d = safety_d.pop("interlock", {})
    _warn_unknown_keys("safety.interlock", safety_interlock_d, SafetyInterlockCfg)
    safety_interlock = SafetyInterlockCfg(
        **{
            k: v
            for k, v in safety_interlock_d.items()
            if k in SafetyInterlockCfg.__dataclass_fields__
        }
    )
    safety_zones_d = safety_d.pop("zones", ())
    safety_zones = tuple(
        SafetyZoneConfig(
            **{k: v for k, v in z.items() if k in SafetyZoneConfig.__dataclass_fields__}
        )
        for z in (safety_zones_d if isinstance(safety_zones_d, list) else [])
    )
    _warn_unknown_keys("safety", safety_d, SafetyConfig)
    safety = SafetyConfig(
        interlock=safety_interlock,
        zones=safety_zones,
        **{
            k: v
            for k, v in safety_d.items()
            if k in SafetyConfig.__dataclass_fields__ and k not in ("interlock", "zones")
        },
    )

    rf_d = data.get("rangefinder", {})
    _warn_unknown_keys("rangefinder", rf_d, RangefinderConfig)
    rangefinder = RangefinderConfig(
        **{k: v for k, v in rf_d.items() if k in RangefinderConfig.__dataclass_fields__}
    )

    vs_d = data.get("video_stream", {})
    _warn_unknown_keys("video_stream", vs_d, VideoStreamCfg)
    video_stream = VideoStreamCfg(
        **{k: v for k, v in vs_d.items() if k in VideoStreamCfg.__dataclass_fields__}
    )

    sess_d = data.get("session", {})
    _warn_unknown_keys("session", sess_d, SessionConfig)
    session = SessionConfig(
        **{k: v for k, v in sess_d.items() if k in SessionConfig.__dataclass_fields__}
    )

    lc_d = data.get("lifecycle", {})
    _warn_unknown_keys("lifecycle", lc_d, LifecycleConfig)
    lifecycle = LifecycleConfig(
        **{k: v for k, v in lc_d.items() if k in LifecycleConfig.__dataclass_fields__}
    )

    clip_d = data.get("clip", {})
    _warn_unknown_keys("clip", clip_d, ClipConfig)
    clip = ClipConfig(**{k: v for k, v in clip_d.items() if k in ClipConfig.__dataclass_fields__})

    return SystemConfig(
        camera=camera,
        detector=detector,
        selector=selector,
        controller=controller,
        driver_limits=driver_limits,
        projectile=projectile,
        environment=environment,
        lead_angle=lead_angle,
        trajectory=trajectory,
        engagement=engagement,
        safety=safety,
        rangefinder=rangefinder,
        video_stream=video_stream,
        session=session,
        lifecycle=lifecycle,
        clip=clip,
    )


def load_config(path: str | Path) -> SystemConfig:
    """Load SystemConfig from a YAML file."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return _nested_dict_to_config(data)


def _tuples_to_lists(obj: object) -> object:
    """Recursively convert all tuples to lists for YAML-safe serialization."""
    if isinstance(obj, dict):
        return {k: _tuples_to_lists(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_tuples_to_lists(item) for item in obj]
    return obj


def save_config(cfg: SystemConfig, path: str | Path) -> None:
    """Save SystemConfig to a YAML file."""
    d = _tuples_to_lists(asdict(cfg))
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(d, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
