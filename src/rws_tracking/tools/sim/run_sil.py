"""
MuJoCo SIL (Software-In-the-Loop) Runner
==========================================

Closed-loop simulation:
    MuJoCo physics  →  offscreen render  →  YOLO detect  →  pipeline  →  gimbal command  →  MuJoCo actuators

Usage::

    # Default: circle motion, 10 seconds, headless
    python -m src.rws_tracking.tools.sim.run_sil

    # With visualization window
    python -m src.rws_tracking.tools.sim.run_sil --show

    # Custom motion pattern
    python -m src.rws_tracking.tools.sim.run_sil --pattern circle --duration 20

    # Waypoint motion
    python -m src.rws_tracking.tools.sim.run_sil --pattern waypoints --duration 30 --show
"""
from __future__ import annotations

import argparse
import time
from typing import Dict, List, Optional, Tuple

import numpy as np

from .mujoco_env import BaseDisturbance, MujocoEnv, TargetMotion


# ---------------------------------------------------------------------------
# MuJoCo-backed BodyMotionProvider — reads actual base sensors
# ---------------------------------------------------------------------------

class _MujocoBodyMotionProvider:
    """Reads body state from MuJoCo base sensors.  Implements ``BodyMotionProvider``."""

    def __init__(self, env: MujocoEnv) -> None:
        self._env = env

    def get_body_state(self, timestamp: float):
        return self._env.get_body_state()


# ---------------------------------------------------------------------------
# Pipeline factory
# ---------------------------------------------------------------------------

def build_sil_pipeline(
    env: MujocoEnv,
    use_yolo: bool = False,
    model_path: str = "yolo11n.pt",
    device: str = "",
    body_provider=None,
):
    """
    Build a VisionGimbalPipeline wired to MuJoCo.

    Default: GroundTruthDetector (reads 3D position from MuJoCo, projects to pixel).
             This isolates control-loop testing from YOLO detection quality.
    --yolo:  YoloDetector (real inference on MuJoCo rendered frames).

    Parameters
    ----------
    body_provider : BodyMotionProvider, optional
        If provided, enables feedforward body-motion compensation in the
        controller.  Pass ``None`` for stationary base (legacy behaviour).
    """
    from ...algebra import CameraModel, PixelToGimbalTransform
    from ...config import SelectorConfig, default_controller_config
    from ...control import TwoAxisGimbalController
    from ...perception import SimpleIoUTracker, WeightedTargetSelector
    from ...pipeline.pipeline import VisionGimbalPipeline
    from ...telemetry import InMemoryTelemetryLogger
    from .ground_truth_detector import DetectionNoise, GroundTruthDetector

    cam = CameraModel(
        width=env.camera.width,
        height=env.camera.height,
        fx=970.0, fy=965.0,
        cx=env.camera.width / 2.0,
        cy=env.camera.height / 2.0,
    )
    transform = PixelToGimbalTransform(cam)
    cfg = default_controller_config()

    if use_yolo:
        from ...perception import YoloDetector
        detector = YoloDetector(
            model_path=model_path,
            confidence_threshold=0.35,
            device=device,
        )
    else:
        detector = GroundTruthDetector(
            model=env.model,
            data=env.data,
            image_width=cam.width,
            image_height=cam.height,
            noise=DetectionNoise(
                bbox_jitter_px=0.5,
                size_jitter_frac=0.01,
                miss_rate=0.0,
                confidence_mean=0.95,
                confidence_std=0.02,
            ),
        )

    pipeline = VisionGimbalPipeline(
        detector=detector,
        tracker=SimpleIoUTracker(iou_threshold=0.18, max_misses=10),
        selector=WeightedTargetSelector(
            frame_width=cam.width,
            frame_height=cam.height,
            config=SelectorConfig(min_hold_time_s=0.35, delta_threshold=0.10),
        ),
        controller=TwoAxisGimbalController(transform=transform, cfg=cfg),
        driver=env.driver,
        telemetry=InMemoryTelemetryLogger(),
        body_provider=body_provider,
    )
    return pipeline


def run_sil(
    pattern: str = "circle",
    duration_s: float = 10.0,
    control_hz: float = 30.0,
    use_yolo: bool = False,
    model_path: str = "yolo11n.pt",
    device: str = "",
    show: bool = False,
    body_motion: bool = False,
) -> Dict:
    """
    Run closed-loop SIL simulation.

    Parameters
    ----------
    pattern : target motion pattern ("static", "linear", "circle", "waypoints")
    duration_s : total simulation time
    control_hz : pipeline update rate (how often we render + detect)
    model_path : YOLO model weights
    device : inference device
    show : if True, display live visualization window
    body_motion : if True, simulate robot dog gait oscillation on the base

    Returns
    -------
    metrics : dict with tracking performance metrics
    """
    # --- Configure target motion ---
    motion = _build_motion(pattern)

    # --- Optional moving-base disturbance ---
    base_dist = BaseDisturbance() if body_motion else None
    env = MujocoEnv(target_motion=motion, base_disturbance=base_dist)

    # Body motion provider reads actual base sensors from MuJoCo
    body_provider = _MujocoBodyMotionProvider(env) if body_motion else None
    pipeline = build_sil_pipeline(
        env,
        use_yolo=use_yolo,
        model_path=model_path,
        device=device,
        body_provider=body_provider,
    )
    detector_name = "YOLO" if use_yolo else "GroundTruth"

    control_dt = 1.0 / control_hz
    physics_steps_per_frame = max(1, int(round(control_dt / env.timestep)))

    print("=" * 60)
    print("  RWS MuJoCo SIL Simulation")
    print("=" * 60)
    print(f"  Pattern:      {pattern}")
    print(f"  Duration:     {duration_s}s")
    print(f"  Control rate: {control_hz} Hz")
    print(f"  Physics dt:   {env.timestep}s ({physics_steps_per_frame} steps/frame)")
    print(f"  Detector:     {detector_name}" + (f" ({model_path})" if use_yolo else ""))
    print(f"  Body motion:  {body_motion}" + (" (sinusoidal gait)" if body_motion else ""))
    print(f"  Show window:  {show}")
    print("=" * 60)

    cv2_imported = False
    if show:
        import cv2
        cv2_imported = True

    frame_count = 0
    t_start = time.monotonic()

    try:
        while env.time < duration_s:
            # 1. Advance physics
            env.step(physics_steps_per_frame)

            # 2. Render camera frame
            frame = env.camera.render()

            # 3. Run full pipeline (detect → track → select → PID → drive)
            sim_time = env.time
            output = pipeline.step(frame, sim_time)
            frame_count += 1

            # 4. Print status periodically
            if frame_count % int(control_hz) == 0:
                tgt_pos = env.get_target_position()
                state_val = output.command.metadata.get("state", -1)
                states = ["SEARCH", "TRACK", "LOCK", "LOST"]
                state_name = states[int(state_val)] if 0 <= state_val < len(states) else "?"
                yaw_err = output.command.metadata.get("yaw_error_deg", 0.0)
                pitch_err = output.command.metadata.get("pitch_error_deg", 0.0)
                ff_yaw = output.command.metadata.get("ff_yaw_dps", 0.0)
                ff_pitch = output.command.metadata.get("ff_pitch_dps", 0.0)
                body_info = ""
                if body_motion:
                    bs = env.get_body_state()
                    body_info = (
                        f"  body=({bs.roll_deg:+.1f}°,{bs.pitch_deg:+.1f}°,{bs.yaw_deg:+.1f}°)"
                        f"  ff=({ff_yaw:+.1f},{ff_pitch:+.1f})dps"
                    )
                print(
                    f"  t={sim_time:6.1f}s  state={state_name:6s}  "
                    f"err=({yaw_err:+5.1f}°, {pitch_err:+5.1f}°)  "
                    f"target=({tgt_pos[0]:.1f}, {tgt_pos[1]:.1f}, {tgt_pos[2]:.1f})"
                    f"{body_info}"
                )

            # 5. Visualization
            if show and cv2_imported:
                display = _draw_overlay(frame, output, env)
                cv2.imshow("RWS MuJoCo SIL", display)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    print("\n  [User pressed 'q', stopping.]")
                    break

    finally:
        if show and cv2_imported:
            cv2.destroyAllWindows()
        env.close()

    elapsed = time.monotonic() - t_start
    metrics = pipeline.telemetry.snapshot_metrics()

    print("\n" + "=" * 60)
    print("  Simulation Complete")
    print("=" * 60)
    print(f"  Sim time:   {env.time:.1f}s")
    print(f"  Wall time:  {elapsed:.1f}s  ({elapsed / max(env.time, 1e-6):.1f}x realtime)")
    print(f"  Frames:     {frame_count}")
    print(f"  Metrics:")
    for k, v in metrics.items():
        print(f"    {k}: {v:.4f}")
    print("=" * 60)

    return metrics


def _build_motion(pattern: str) -> TargetMotion:
    """Create a TargetMotion config for the given pattern name.

    Note: humanoid target z=0 means feet on ground, body center ~0.85m.
    Gimbal camera is at ~1.30m height, so z=0 makes the person stand on ground.
    """
    if pattern == "static":
        return TargetMotion(pattern="static", start_pos=(5.0, 0.0, 1.5))

    elif pattern == "linear":
        return TargetMotion(
            pattern="linear",
            start_pos=(5.0, -3.0, 1.5),
            velocity_mps=(0.0, 0.6, 0.0),
        )

    elif pattern == "circle":
        return TargetMotion(
            pattern="circle",
            center=(5.0, 0.0, 1.5),
            radius_m=2.0,
            omega_dps=25.0,
        )

    elif pattern == "waypoints":
        return TargetMotion(
            pattern="waypoints",
            start_pos=(5.0, -2.0, 1.5),
            waypoints=[
                (5.0, -2.0, 1.5),
                (5.0, 2.0, 1.5),
                (7.0, 2.0, 1.5),
                (7.0, -2.0, 1.5),
            ],
            waypoint_speed_mps=1.0,
        )

    else:
        raise ValueError(f"Unknown motion pattern: {pattern!r}")


def _draw_overlay(frame: np.ndarray, output, env: MujocoEnv) -> np.ndarray:
    """Draw tracking info on the frame for visualization."""
    import cv2

    display = frame.copy()

    # Draw crosshair at image center
    h, w = display.shape[:2]
    cx, cy = w // 2, h // 2
    cv2.line(display, (cx - 20, cy), (cx + 20, cy), (0, 255, 255), 1)
    cv2.line(display, (cx, cy - 20), (cx, cy + 20), (0, 255, 255), 1)

    # Draw selected target bbox
    if output.selected_target is not None:
        t = output.selected_target
        x, y, bw, bh = int(t.bbox.x), int(t.bbox.y), int(t.bbox.w), int(t.bbox.h)
        cv2.rectangle(display, (x, y), (x + bw, y + bh), (0, 255, 0), 2)
        label = f"ID:{t.track_id} {t.class_id} {t.confidence:.2f}"
        cv2.putText(display, label, (x, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

    # Draw status info
    cmd = output.command
    states = ["SEARCH", "TRACK", "LOCK", "LOST"]
    state_val = int(cmd.metadata.get("state", -1))
    state_name = states[state_val] if 0 <= state_val < len(states) else "?"
    yaw_err = cmd.metadata.get("yaw_error_deg", 0.0)
    pitch_err = cmd.metadata.get("pitch_error_deg", 0.0)

    color_map = {"SEARCH": (0, 200, 255), "TRACK": (255, 200, 0), "LOCK": (0, 255, 0), "LOST": (0, 0, 255)}
    color = color_map.get(state_name, (255, 255, 255))

    info = f"{state_name} | err:({yaw_err:+.1f}, {pitch_err:+.1f}) | t={env.time:.1f}s"
    cv2.putText(display, info, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

    return display


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="RWS MuJoCo SIL closed-loop simulation.")
    p.add_argument("--pattern", type=str, default="circle",
                   choices=["static", "linear", "circle", "waypoints"],
                   help="Target motion pattern (default: circle)")
    p.add_argument("--duration", type=float, default=10.0,
                   help="Simulation duration in seconds (default: 10)")
    p.add_argument("--hz", type=float, default=30.0,
                   help="Control loop rate in Hz (default: 30)")
    p.add_argument("--yolo", action="store_true",
                   help="Use YOLO detector instead of ground truth (default: ground truth)")
    p.add_argument("--model", type=str, default="yolo11n.pt",
                   help="YOLO model path, only used with --yolo (default: yolo11n.pt)")
    p.add_argument("--device", type=str, default="",
                   help="Inference device (default: auto)")
    p.add_argument("--show", action="store_true",
                   help="Show live visualization window")
    p.add_argument("--body-motion", action="store_true",
                   help="Simulate robot dog gait oscillation on base (test feedforward compensation)")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_sil(
        pattern=args.pattern,
        duration_s=args.duration,
        control_hz=args.hz,
        use_yolo=args.yolo,
        model_path=args.model,
        device=args.device,
        show=args.show,
        body_motion=args.body_motion,
    )
