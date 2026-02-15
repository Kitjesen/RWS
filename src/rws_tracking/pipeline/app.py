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
        # Get current gimbal position
        gimbal_yaw = pipeline.driver._yaw
        gimbal_pitch = pipeline.driver._pitch

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
