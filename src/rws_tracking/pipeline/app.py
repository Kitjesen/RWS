"""
Application entry points
========================

- ``build_sim_pipeline``       : synthetic scene + PassthroughDetector (for tuning / CI).
- ``build_yolo_pipeline``      : YOLO11n real inference + PixelToGimbalTransform (production).
- ``build_yolo_seg_pipeline``  : YOLO11n-Seg + BoT-SORT combined tracker (production, recommended).
- ``run_demo``                 : quick synthetic demo (no camera needed).
- ``run_camera_demo``          : live camera + YOLO + gimbal control loop.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..algebra import CameraModel, DistortionCoeffs, MountExtrinsics, PixelToGimbalTransform
from ..config import (
    CameraConfig,
    SelectorConfig,
    SystemConfig,
    default_controller_config,
)
from ..control import TwoAxisGimbalController
from ..hardware import SimulatedGimbalDriver
from ..hardware.driver import DriverLimits
from ..hardware.imu_interface import BodyMotionProvider
from ..perception import (
    PassthroughDetector,
    SimpleIoUTracker,
    WeightedTargetSelector,
    YoloSegTracker,
)
from ..telemetry import InMemoryTelemetryLogger
from ..tools.simulation import WorldCoordinateScene, WorldSimTarget
from ..tools.tuning import grid_search_pid
from .pipeline import VisionGimbalPipeline

# ---------------------------------------------------------------------------
# Camera model helper
# ---------------------------------------------------------------------------


def camera_model_from_config(cfg: CameraConfig) -> CameraModel:
    """Build CameraModel from CameraConfig dataclass."""
    dist = DistortionCoeffs(
        k1=cfg.distortion_k1,
        k2=cfg.distortion_k2,
        p1=cfg.distortion_p1,
        p2=cfg.distortion_p2,
        k3=cfg.distortion_k3,
    )
    has_distortion = any(
        v != 0.0
        for v in (
            cfg.distortion_k1,
            cfg.distortion_k2,
            cfg.distortion_p1,
            cfg.distortion_p2,
            cfg.distortion_k3,
        )
    )
    return CameraModel(
        width=cfg.width,
        height=cfg.height,
        fx=cfg.fx,
        fy=cfg.fy,
        cx=cfg.cx,
        cy=cfg.cy,
        distortion=dist if has_distortion else None,
    )


def default_camera_model() -> CameraModel:
    """1280x720 pinhole model with typical webcam intrinsics."""
    return camera_model_from_config(CameraConfig())


# ---------------------------------------------------------------------------
# Simulation pipeline (for tuning / CI)
# ---------------------------------------------------------------------------


def build_sim_pipeline(camera: CameraModel | None = None) -> VisionGimbalPipeline:
    cam = camera or default_camera_model()
    transform = PixelToGimbalTransform(cam)
    base_cfg = default_controller_config()
    tuned_cfg, _ = grid_search_pid(base_cfg, cam, duration_s=4.0, dt_s=0.04)

    return VisionGimbalPipeline(
        detector=PassthroughDetector(),
        tracker=SimpleIoUTracker(iou_threshold=0.18, max_misses=10),
        selector=WeightedTargetSelector(
            frame_width=cam.width,
            frame_height=cam.height,
            config=SelectorConfig(
                preferred_classes={"person": 1.0, "vehicle": 0.6},
                min_hold_time_s=0.35,
                delta_threshold=0.10,
            ),
        ),
        controller=TwoAxisGimbalController(transform=transform, cfg=tuned_cfg),
        driver=SimulatedGimbalDriver(),
        telemetry=InMemoryTelemetryLogger(),
    )


# ---------------------------------------------------------------------------
# YOLO pipeline (for production / real camera)
# ---------------------------------------------------------------------------


def build_yolo_pipeline(
    camera: CameraModel | None = None,
    mount: MountExtrinsics = MountExtrinsics(),
    model_path: str = "yolo11n.pt",
    class_whitelist: Sequence[str] | None = None,
    confidence: float = 0.45,
    device: str = "",
) -> VisionGimbalPipeline:
    from ..perception import YoloDetector

    cam = camera or default_camera_model()
    transform = PixelToGimbalTransform(cam, mount)
    cfg = default_controller_config()

    return VisionGimbalPipeline(
        detector=YoloDetector(
            model_path=model_path,
            confidence_threshold=confidence,
            class_whitelist=list(class_whitelist) if class_whitelist else None,
            device=device,
        ),
        tracker=SimpleIoUTracker(iou_threshold=0.18, max_misses=10),
        selector=WeightedTargetSelector(
            frame_width=cam.width,
            frame_height=cam.height,
            config=SelectorConfig(
                preferred_classes={"person": 1.0, "car": 0.6},
                min_hold_time_s=0.35,
                delta_threshold=0.10,
            ),
        ),
        controller=TwoAxisGimbalController(transform=transform, cfg=cfg),
        driver=SimulatedGimbalDriver(),
        telemetry=InMemoryTelemetryLogger(),
    )


# ---------------------------------------------------------------------------
# YOLO-Seg + BoT-SORT pipeline (recommended for production)
# ---------------------------------------------------------------------------


def build_yolo_seg_pipeline(
    camera: CameraModel | None = None,
    mount: MountExtrinsics = MountExtrinsics(),
    model_path: str = "yolo11n-seg.pt",
    tracker: str = "botsort.yaml",
    class_whitelist: Sequence[str] | None = None,
    confidence: float = 0.40,
    device: str = "",
    body_provider: BodyMotionProvider | None = None,
) -> VisionGimbalPipeline:
    """
    Build a pipeline using YOLO11n-Seg + BoT-SORT combined tracker.

    Advantages over ``build_yolo_pipeline``:
      - Kalman-smoothed bboxes (no jitter).
      - Instance segmentation masks (tight contours, no oversized boxes).
      - Stable track IDs with re-identification (BoT-SORT).
      - Single model call per frame (simpler & faster).

    Parameters
    ----------
    body_provider : BodyMotionProvider, optional
        If provided, enables feedforward body-motion compensation.
        Pass ``None`` (default) for stationary base.
    """
    cam = camera or default_camera_model()
    transform = PixelToGimbalTransform(cam, mount)
    cfg = default_controller_config()

    seg_tracker = YoloSegTracker(
        model_path=model_path,
        confidence_threshold=confidence,
        tracker=tracker,
        class_whitelist=list(class_whitelist) if class_whitelist else None,
        device=device,
    )

    # Provide a dummy detector/tracker pair for the constructor signature;
    # they are unused when combined_tracker is set.
    return VisionGimbalPipeline(
        detector=PassthroughDetector(),
        tracker=SimpleIoUTracker(iou_threshold=0.18, max_misses=10),
        selector=WeightedTargetSelector(
            frame_width=cam.width,
            frame_height=cam.height,
            config=SelectorConfig(
                preferred_classes={"person": 1.0, "car": 0.6},
                min_hold_time_s=0.35,
                delta_threshold=0.10,
            ),
        ),
        controller=TwoAxisGimbalController(transform=transform, cfg=cfg),
        driver=SimulatedGimbalDriver(),
        telemetry=InMemoryTelemetryLogger(),
        combined_tracker=seg_tracker,
        body_provider=body_provider,
    )


# ---------------------------------------------------------------------------
# Config-driven pipeline (recommended entry point)
# ---------------------------------------------------------------------------


def build_pipeline_from_config(
    cfg: SystemConfig,
    body_provider: BodyMotionProvider | None = None,
) -> VisionGimbalPipeline:
    """Build a complete pipeline from a SystemConfig (loaded from config.yaml).

    Uses YOLO-Seg + BoT-SORT combined tracker.  Camera intrinsics, detector
    parameters, selector weights, controller PID, and driver limits are all
    sourced from *cfg*.

    Automatically creates and injects all v1.1 extension components
    (threat assessment, distance fusion, ballistic solver, lead angle,
    safety system, trajectory planner, video stream) when their config
    sections are enabled.
    """
    cam = camera_model_from_config(cfg.camera)
    mount = MountExtrinsics(
        roll_deg=cfg.camera.mount_roll_deg,
        pitch_deg=cfg.camera.mount_pitch_deg,
        yaw_deg=cfg.camera.mount_yaw_deg,
    )
    transform = PixelToGimbalTransform(cam, mount)

    det = cfg.detector
    seg_tracker = YoloSegTracker(
        model_path=det.model_path,
        confidence_threshold=det.confidence_threshold,
        nms_iou_threshold=det.nms_iou_threshold,
        tracker=det.tracker,
        class_whitelist=list(det.class_whitelist) if det.class_whitelist else None,
        device=det.device,
        img_size=det.img_size,
    )

    # ---- v1.1 扩展组件 (按 config 启用) ----

    # 威胁评估 (桥接 config 层类型 → engagement 模块类型)
    threat_assessor = None
    engagement_queue = None
    if cfg.engagement.enabled:
        from ..decision.engagement import EngagementConfig as EConfig
        from ..decision.engagement import EngagementQueue, ThreatAssessor, ThreatWeights

        eng_cfg = EConfig(
            weights=ThreatWeights(
                distance=cfg.engagement.weights.distance,
                velocity=cfg.engagement.weights.velocity,
                class_threat=cfg.engagement.weights.class_threat,
                heading=cfg.engagement.weights.heading,
                size=cfg.engagement.weights.size,
            ),
            strategy=cfg.engagement.strategy,
            max_engagement_range_m=cfg.engagement.max_engagement_range_m,
            min_threat_threshold=cfg.engagement.min_threat_threshold,
            distance_decay_m=cfg.engagement.distance_decay_m,
            velocity_norm_px_s=cfg.engagement.velocity_norm_px_s,
            target_height_m=cfg.engagement.target_height_m,
            sector_size_deg=cfg.engagement.sector_size_deg,
        )
        threat_assessor = ThreatAssessor(
            frame_width=cam.width,
            frame_height=cam.height,
            camera_fy=cam.fy,
            config=eng_cfg,
        )
        engagement_queue = EngagementQueue(config=eng_cfg)

    # 测距仪 + 距离融合
    rangefinder = None
    distance_fusion = None
    if cfg.rangefinder.enabled:
        from ..hardware.rangefinder import (
            DistanceFusion,
            SimulatedRangefinder,
            SimulatedRangefinderConfig,
        )

        rf_cfg = SimulatedRangefinderConfig(
            noise_std_m=cfg.rangefinder.noise_std_m,
            max_range_m=cfg.rangefinder.max_range_m,
            min_range_m=cfg.rangefinder.min_range_m,
            failure_rate=cfg.rangefinder.failure_rate,
        )
        rangefinder = SimulatedRangefinder(
            config=rf_cfg,
            camera_fy=cam.fy,
            target_height_m=cfg.rangefinder.target_height_m,
        )
        distance_fusion = DistanceFusion(
            max_laser_age_s=cfg.rangefinder.max_laser_age_s,
            camera_fy=cam.fy,
            target_height_m=cfg.rangefinder.target_height_m,
        )

    # 物理弹道解算 (独立于 controller 内置弹道, 用于 pipeline 级别的完整解)
    ballistic_solver = None
    if cfg.projectile.enabled:
        from ..control.ballistic import PhysicsBallisticModel
        from ..types import ProjectileParams

        ballistic_solver = PhysicsBallisticModel(
            projectile=ProjectileParams(
                muzzle_velocity_mps=cfg.projectile.muzzle_velocity_mps,
                bc_g7=cfg.projectile.ballistic_coefficient,
                mass_kg=cfg.projectile.projectile_mass_kg,
                caliber_m=cfg.projectile.projectile_diameter_m,
            ),
            target_height_m=cfg.controller.ballistic.target_height_m,
        )

    # 射击提前量 (需要弹道模型作为 FlightTimeProvider)
    lead_calculator = None
    if cfg.lead_angle.enabled:
        from ..control.lead_angle import LeadAngleCalculator
        from ..control.lead_angle import LeadAngleConfig as LAConfig

        la_cfg = LAConfig(
            enabled=cfg.lead_angle.enabled,
            use_acceleration=cfg.lead_angle.use_acceleration,
            max_lead_deg=cfg.lead_angle.max_lead_deg,
            min_confidence=cfg.lead_angle.min_confidence,
            velocity_smoothing_alpha=cfg.lead_angle.velocity_smoothing_alpha,
            target_height_m=cfg.lead_angle.target_height_m,
            convergence_iterations=cfg.lead_angle.convergence_iterations,
        )

        # 如果有弹道解算器, 用它作为飞行时间源; 否则用简单估算
        if ballistic_solver is not None and hasattr(ballistic_solver, "compute_flight_time"):
            ftp = ballistic_solver
        else:
            from ..control.lead_angle import SimpleFlightTimeProvider

            ftp = SimpleFlightTimeProvider(muzzle_velocity_mps=900.0)

        lead_calculator = LeadAngleCalculator(
            transform=transform,
            flight_time_provider=ftp,
            config=la_cfg,
        )

    # 安全系统 (桥接 config 层的 SafetyConfig → safety 模块的 SafetyManagerConfig)
    safety_manager = None
    if cfg.safety.enabled:
        from ..safety.interlock import SafetyInterlockConfig
        from ..safety.manager import SafetyManager, SafetyManagerConfig
        from ..types import SafetyZone

        interlock_cfg = SafetyInterlockConfig(
            require_operator_auth=cfg.safety.interlock.require_operator_auth,
            min_lock_time_s=cfg.safety.interlock.min_lock_time_s,
            min_engagement_range_m=cfg.safety.interlock.min_engagement_range_m,
            max_engagement_range_m=cfg.safety.interlock.max_engagement_range_m,
            system_check_interval_s=cfg.safety.interlock.system_check_interval_s,
            heartbeat_timeout_s=cfg.safety.interlock.heartbeat_timeout_s,
        )
        zones = tuple(
            SafetyZone(
                zone_id=z.zone_id,
                center_yaw_deg=z.center_yaw_deg,
                center_pitch_deg=z.center_pitch_deg,
                radius_deg=z.radius_deg,
                zone_type=z.zone_type,
            )
            for z in cfg.safety.zones
        )
        safety_manager = SafetyManager(
            SafetyManagerConfig(
                interlock=interlock_cfg,
                nfz_slow_down_margin_deg=cfg.safety.nfz_slow_down_margin_deg,
                zones=zones,
            )
        )

    # 轨迹规划
    trajectory_planner = None
    if cfg.trajectory.enabled:
        from ..control.trajectory import GimbalTrajectoryPlanner
        from ..control.trajectory import TrajectoryConfig as TConfig

        tc = TConfig(
            max_rate_dps=cfg.trajectory.max_rate_dps,
            max_acceleration_dps2=cfg.trajectory.max_acceleration_dps2,
            settling_threshold_deg=cfg.trajectory.settling_threshold_deg,
            use_s_curve=cfg.trajectory.use_s_curve,
            max_jerk_dps3=cfg.trajectory.max_jerk_dps3,
            min_switch_interval_s=cfg.trajectory.min_switch_interval_s,
        )
        trajectory_planner = GimbalTrajectoryPlanner(tc)

    # 视频流
    frame_buffer = None
    frame_annotator = None
    if cfg.video_stream.enabled:
        from ..api.video_stream import FrameAnnotator, FrameBuffer
        from ..api.video_stream import VideoStreamConfig as VSConfig

        vs_cfg = VSConfig(
            enabled=cfg.video_stream.enabled,
            jpeg_quality=cfg.video_stream.jpeg_quality,
            max_fps=cfg.video_stream.max_fps,
            scale_factor=cfg.video_stream.scale_factor,
            buffer_size=cfg.video_stream.buffer_size,
            annotate_detections=cfg.video_stream.annotate_detections,
            annotate_tracks=cfg.video_stream.annotate_tracks,
            annotate_crosshair=cfg.video_stream.annotate_crosshair,
        )
        frame_buffer = FrameBuffer(max_size=cfg.video_stream.buffer_size)
        frame_annotator = FrameAnnotator(config=vs_cfg)

    # ---- v2 extension components ----

    from ..safety.shooting_chain import ShootingChain
    from ..telemetry.audit import AuditLogger
    from ..health.monitor import HealthMonitor
    from ..decision.lifecycle import TargetLifecycleManager

    shooting_chain = ShootingChain(
        cooldown_s=getattr(cfg, "fire_cooldown_s", 3.0)
    )
    audit_logger = AuditLogger(
        log_path=getattr(cfg, "audit_log_path", "logs/audit.jsonl")
    )
    health_monitor = HealthMonitor()
    lifecycle_manager = TargetLifecycleManager(
        confirm_age_frames=getattr(cfg, "lifecycle_confirm_frames", 3),
        archive_after_s=getattr(cfg, "lifecycle_archive_s", 10.0),
    )

    return VisionGimbalPipeline(
        detector=PassthroughDetector(),
        tracker=SimpleIoUTracker(),
        selector=WeightedTargetSelector(
            frame_width=cam.width,
            frame_height=cam.height,
            config=cfg.selector,
        ),
        controller=TwoAxisGimbalController(transform=transform, cfg=cfg.controller),
        driver=SimulatedGimbalDriver(DriverLimits.from_config(cfg.driver_limits)),
        telemetry=InMemoryTelemetryLogger(),
        combined_tracker=seg_tracker,
        body_provider=body_provider,
        threat_assessor=threat_assessor,
        engagement_queue=engagement_queue,
        distance_fusion=distance_fusion,
        rangefinder=rangefinder,
        ballistic_solver=ballistic_solver,
        lead_calculator=lead_calculator,
        safety_manager=safety_manager,
        trajectory_planner=trajectory_planner,
        frame_buffer=frame_buffer,
        frame_annotator=frame_annotator,
        shooting_chain=shooting_chain,
        audit_logger=audit_logger,
        health_monitor=health_monitor,
        lifecycle_manager=lifecycle_manager,
    )


# ---------------------------------------------------------------------------
# Quick demos
# ---------------------------------------------------------------------------


def run_demo(duration_s: float = 10.0, dt_s: float = 0.03) -> dict:
    """Run synthetic scene demo (no camera/YOLO needed).

    Uses WorldCoordinateScene for realistic simulation where targets
    move in world coordinates and gimbal rotation affects their position
    in the camera frame.
    """
    cam = default_camera_model()
    pipeline = build_sim_pipeline(cam)

    # Create realistic world-coordinate scene
    scene = WorldCoordinateScene(
        cam_width=cam.width,
        cam_height=cam.height,
        fx=cam.fx,
        fy=cam.fy,
        cx=cam.cx,
        cy=cam.cy,
        seed=11,
    )

    # Add targets in world coordinates (angular position)
    scene.add_target(
        WorldSimTarget(
            world_yaw_deg=5.0,
            world_pitch_deg=2.0,
            vel_yaw_dps=2.0,  # 2 degrees per second
            vel_pitch_dps=1.0,
            bbox_width=75,
            bbox_height=100,
            confidence=0.92,
            class_id="person",
        )
    )
    scene.add_target(
        WorldSimTarget(
            world_yaw_deg=-8.0,
            world_pitch_deg=-3.0,
            vel_yaw_dps=-1.5,
            vel_pitch_dps=0.8,
            bbox_width=110,
            bbox_height=90,
            confidence=0.85,
            class_id="vehicle",
        )
    )

    ts = 0.0
    while ts < duration_s:
        fb = pipeline.driver.get_feedback(ts)
        gimbal_yaw = fb.yaw_deg
        gimbal_pitch = fb.pitch_deg

        # Generate detections considering gimbal rotation
        frame = scene.step(dt_s, gimbal_yaw, gimbal_pitch)
        pipeline.step(frame, ts)
        ts += dt_s

    return pipeline.telemetry.snapshot_metrics()


def run_camera_demo(
    source: int = 0,
    model_path: str = "yolo11n.pt",
    class_whitelist: Sequence[str] | None = ("person",),
    show_window: bool = True,
) -> None:
    """Live camera demo: YOLO11n detect + gimbal control loop."""
    import time

    import cv2

    cam = default_camera_model()
    pipeline = build_yolo_pipeline(
        camera=cam,
        model_path=model_path,
        class_whitelist=class_whitelist,
    )

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open camera source {source}")

    print(f"[RWS] Camera opened (source={source}). Press 'q' to quit or Ctrl+C to stop.")
    pipeline.install_signal_handlers()

    try:
        while not pipeline.should_stop():
            ret, frame = cap.read()
            if not ret:
                break
            ts = time.monotonic()
            output = pipeline.step(frame, ts)

            if show_window:
                display = frame.copy()
                if output.selected_target is not None:
                    t = output.selected_target
                    x, y, w, h = int(t.bbox.x), int(t.bbox.y), int(t.bbox.w), int(t.bbox.h)
                    cv2.rectangle(display, (x, y), (x + w, y + h), (0, 255, 0), 2)
                    label = f"ID:{t.track_id} {t.class_id} {t.confidence:.2f}"
                    cv2.putText(
                        display, label, (x, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2
                    )

                cmd = output.command
                info = (
                    f"Yaw:{cmd.yaw_rate_cmd_dps:+.1f} dps  "
                    f"Pitch:{cmd.pitch_rate_cmd_dps:+.1f} dps  "
                    f"State:{cmd.metadata.get('state', -1):.0f}"
                )
                cv2.putText(
                    display, info, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2
                )
                cv2.imshow("RWS Tracking", display)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    pipeline.stop()
    finally:
        cap.release()
        if show_window:
            cv2.destroyAllWindows()
        pipeline.cleanup()
        metrics = pipeline.telemetry.snapshot_metrics()
        print("\n[RWS] Session metrics:")
        for k, v in metrics.items():
            print(f"  {k}: {v:.4f}")
