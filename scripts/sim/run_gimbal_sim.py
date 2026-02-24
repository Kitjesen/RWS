"""
RWS 2-DOF Gimbal Simulation Demo
=================================

Runs the complete VisionGimbalPipeline against a synthetic world-coordinate
scene of moving targets.  The gimbal posture is visualised in real-time with:

  • Matplotlib 3D viewer  (zero-extra-deps, default)
  • PyBullet physics GUI  (requires: pip install pybullet pybullet_data)

The demo uses WorldCoordinateScene — targets are placed in world angular
coordinates (yaw/pitch degrees).  When the gimbal rotates, targets move in
the camera frame exactly as they would with a real gimbal, giving realistic
lag, lead-angle, and lock-on behaviour.

Usage::

    python scripts/sim/run_gimbal_sim.py                  # Matplotlib viz
    python scripts/sim/run_gimbal_sim.py --pybullet       # PyBullet GUI
    python scripts/sim/run_gimbal_sim.py --no-window      # headless / benchmark
    python scripts/sim/run_gimbal_sim.py --duration 60    # longer run
    python scripts/sim/run_gimbal_sim.py --targets 6      # more targets
"""
from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

# ── project root on path so we can run from anywhere ─────────────────────────
_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))

import numpy as np

from src.rws_tracking.algebra import CameraModel, PixelToGimbalTransform
from src.rws_tracking.config import SelectorConfig, default_controller_config
from src.rws_tracking.control import TwoAxisGimbalController
from src.rws_tracking.hardware.driver import DriverLimits, SimulatedGimbalDriver
from src.rws_tracking.perception import (
    PassthroughDetector,
    SimpleIoUTracker,
    WeightedTargetSelector,
)
from src.rws_tracking.pipeline import VisionGimbalPipeline
from src.rws_tracking.telemetry import InMemoryTelemetryLogger
from src.rws_tracking.tools.simulation import WorldCoordinateScene, WorldSimTarget

# ── camera intrinsics (1280×720, moderate telephoto) ─────────────────────────
CAM_W, CAM_H   = 1280, 720
CAM_FX, CAM_FY = 970.0, 965.0
CAM_CX, CAM_CY = 640.0, 360.0

# ── colours for OpenCV annotation ────────────────────────────────────────────
_COLORS = [
    (  0, 200, 255),   # cyan
    ( 80, 255,  80),   # green
    (255, 150,  30),   # orange
    (200,  60, 255),   # purple
    (255,  60, 100),   # rose
    ( 40, 220, 180),   # teal
]
_WHITE  = (255, 255, 255)
_YELLOW = ( 40, 220, 255)
_RED    = ( 40,  40, 255)
_GRAY   = (160, 160, 160)


# ─────────────────────────────────────────────────────────────────────────────
# Target definitions
# ─────────────────────────────────────────────────────────────────────────────

def make_targets(n: int) -> list[WorldSimTarget]:
    """Return up to 6 pre-defined interesting target trajectories."""
    catalog = [
        # Slow crossing target — tests lock acquisition
        WorldSimTarget(
            world_yaw_deg=-18.0, world_pitch_deg=3.0,
            vel_yaw_dps=4.5,  vel_pitch_dps=0.4,
            bbox_width=80,  bbox_height=140,
            confidence=0.92, class_id="person",
        ),
        # Fast lateral — tests lead-angle prediction
        WorldSimTarget(
            world_yaw_deg=12.0, world_pitch_deg=-2.0,
            vel_yaw_dps=-9.0, vel_pitch_dps=0.8,
            bbox_width=70,  bbox_height=130,
            confidence=0.88, class_id="person",
        ),
        # Diagonal approach — tests pitch+yaw combined
        WorldSimTarget(
            world_yaw_deg=5.0, world_pitch_deg=8.0,
            vel_yaw_dps=3.0,  vel_pitch_dps=-3.5,
            bbox_width=90,  bbox_height=160,
            confidence=0.94, class_id="person",
        ),
        # Counter-clockwise orbit
        WorldSimTarget(
            world_yaw_deg=-25.0, world_pitch_deg=-5.0,
            vel_yaw_dps=6.0,  vel_pitch_dps=1.5,
            bbox_width=60,  bbox_height=110,
            confidence=0.83, class_id="person",
        ),
        # Near-stationary target — tests stability / deadband
        WorldSimTarget(
            world_yaw_deg=2.0, world_pitch_deg=1.0,
            vel_yaw_dps=0.8,  vel_pitch_dps=0.3,
            bbox_width=100, bbox_height=180,
            confidence=0.96, class_id="person",
        ),
        # Fast far-field target — low confidence, smaller bbox
        WorldSimTarget(
            world_yaw_deg=-10.0, world_pitch_deg=4.0,
            vel_yaw_dps=7.5,  vel_pitch_dps=-1.2,
            bbox_width=40,  bbox_height=75,
            confidence=0.72, class_id="person",
        ),
    ]
    return catalog[:max(1, min(n, len(catalog)))]


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline construction helper
# ─────────────────────────────────────────────────────────────────────────────

def build_pipeline(driver) -> tuple[VisionGimbalPipeline, PassthroughDetector]:
    """Build a lightweight sim pipeline (no YOLO, no grid-search)."""
    cam = CameraModel(
        width=CAM_W, height=CAM_H,
        fx=CAM_FX, fy=CAM_FY,
        cx=CAM_CX, cy=CAM_CY,
    )
    transform  = PixelToGimbalTransform(cam)
    ctrl_cfg   = default_controller_config()
    detector   = PassthroughDetector()
    tracker    = SimpleIoUTracker(iou_threshold=0.18, max_misses=12)
    selector   = WeightedTargetSelector(
        frame_width=cam.width,
        frame_height=cam.height,
        config=SelectorConfig(
            preferred_classes={"person": 1.0},
            min_hold_time_s=0.30,
            delta_threshold=0.12,
        ),
    )
    controller = TwoAxisGimbalController(transform=transform, cfg=ctrl_cfg)
    telemetry  = InMemoryTelemetryLogger()

    pipeline = VisionGimbalPipeline(
        detector=detector,
        tracker=tracker,
        selector=selector,
        controller=controller,
        driver=driver,
        telemetry=telemetry,
    )
    return pipeline, detector


# ─────────────────────────────────────────────────────────────────────────────
# OpenCV annotation helper
# ─────────────────────────────────────────────────────────────────────────────

def _try_import_cv2():
    try:
        import cv2
        return cv2
    except ImportError:
        return None


def annotate_frame(
    frame: np.ndarray,
    detections,
    outputs,
    yaw_deg: float,
    pitch_deg: float,
    elapsed: float,
    state: str = "?",
) -> np.ndarray:
    """Draw bboxes, crosshair, HUD text onto the synthetic frame."""
    cv2 = _try_import_cv2()
    if cv2 is None:
        return frame

    FONT = cv2.FONT_HERSHEY_SIMPLEX

    # Draw detection boxes
    for i, det in enumerate(detections):
        b = det.bbox
        x1, y1 = int(b.x), int(b.y)
        x2, y2 = int(b.x + b.w), int(b.y + b.h)
        color = _COLORS[i % len(_COLORS)]
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 1)

    # Highlight selected target
    if outputs.selected_target is not None:
        obs = outputs.selected_target
        b = obs.bbox
        x1, y1 = int(b.x), int(b.y)
        x2, y2 = int(b.x + b.w), int(b.y + b.h)
        cv2.rectangle(frame, (x1, y1), (x2, y2), _YELLOW, 2)
        # Target centre dot
        cx, cy = int(b.x + b.w / 2), int(b.y + b.h / 2)
        cv2.circle(frame, (cx, cy), 5, _YELLOW, -1)
        # Boresight → target line
        cv2.line(frame, (CAM_W // 2, CAM_H // 2), (cx, cy), _YELLOW, 1,
                 cv2.LINE_AA)

    # Crosshair (frame centre = boresight)
    cx0, cy0 = CAM_W // 2, CAM_H // 2
    cv2.line(frame, (cx0 - 25, cy0), (cx0 + 25, cy0), _WHITE, 1)
    cv2.line(frame, (cx0, cy0 - 25), (cx0, cy0 + 25), _WHITE, 1)
    cv2.circle(frame, (cx0, cy0), 30, _WHITE, 1)

    # HUD — top-left
    state_color = _YELLOW if state == "lock" else (_WHITE if state == "track" else _GRAY)
    lines = [
        (f"T={elapsed:5.1f}s", _WHITE),
        (f"Yaw  {yaw_deg:+7.2f}", _WHITE),
        (f"Pitch{pitch_deg:+7.2f}", _WHITE),
        (f"State: {state}", state_color),
        (f"Tracks: {len(outputs.tracks)}", _WHITE),
    ]
    for row, (txt, col) in enumerate(lines):
        cv2.putText(frame, txt, (12, 22 + row * 22),
                    FONT, 0.55, col, 1, cv2.LINE_AA)

    return frame


# ─────────────────────────────────────────────────────────────────────────────
# Main simulation loop
# ─────────────────────────────────────────────────────────────────────────────

def run_sim(
    duration_s: float = 30.0,
    dt_s: float = 1.0 / 30.0,
    n_targets: int = 4,
    use_pybullet: bool = False,
    show_window: bool = True,
) -> None:
    # ── choose driver ─────────────────────────────────────────────────────────
    limits = DriverLimits(
        yaw_min_deg=-160.0, yaw_max_deg=160.0,
        pitch_min_deg=-45.0, pitch_max_deg=75.0,
        max_rate_dps=240.0, deadband_dps=0.2,
    )

    if use_pybullet:
        try:
            from src.rws_tracking.hardware.pybullet_driver import PyBulletGimbalDriver
            gui = show_window   # headless when --no-window; GUI when window requested
            driver = PyBulletGimbalDriver(gui=gui, limits=limits)
            print(f"[SIM] Driver: PyBullet ({'GUI' if gui else 'headless DIRECT'})")
        except (ImportError, FileNotFoundError) as exc:
            print(f"[SIM] PyBullet unavailable ({exc}), falling back to Matplotlib")
            use_pybullet = False

    if not use_pybullet:
        if show_window:
            try:
                from src.rws_tracking.hardware.viz_driver import MatplotlibGimbalDriver
                driver = MatplotlibGimbalDriver(
                    limits=limits,
                    viz_fps=25.0,
                    window_title="RWS 2-DOF Gimbal — Simulation",
                )
                print("[SIM] Driver: Matplotlib 3D visualizer")
            except Exception as exc:
                print(f"[SIM] Matplotlib viz unavailable ({exc}), using SimulatedGimbalDriver")
                driver = SimulatedGimbalDriver(limits)
        else:
            driver = SimulatedGimbalDriver(limits)
            print("[SIM] Driver: SimulatedGimbalDriver (headless)")

    # ── build pipeline ────────────────────────────────────────────────────────
    pipeline, detector = build_pipeline(driver)

    # ── world-coordinate scene ────────────────────────────────────────────────
    scene = WorldCoordinateScene(
        cam_width=CAM_W, cam_height=CAM_H,
        fx=CAM_FX, fy=CAM_FY,
        cx=CAM_CX, cy=CAM_CY,
    )
    for tgt in make_targets(n_targets):
        scene.add_target(tgt)

    print(f"[SIM] {n_targets} targets  |  duration={duration_s:.0f}s  |  "
          f"dt={dt_s*1000:.1f}ms  ({1/dt_s:.0f} Hz)")
    print("[SIM] Press Ctrl-C to stop early.\n")

    # ── OpenCV window ─────────────────────────────────────────────────────────
    cv2 = _try_import_cv2() if show_window else None
    if cv2 is not None:
        cv2.namedWindow("RWS Sim — Camera View", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("RWS Sim — Camera View", 960, 540)

    # ── metrics ───────────────────────────────────────────────────────────────
    n_frames = 0
    n_lock   = 0
    n_track  = 0
    t_start  = time.monotonic()
    last_fb  = None   # cached last feedback for summary

    prev_state = ""

    try:
        while True:
            t_now   = time.monotonic()
            elapsed = t_now - t_start
            if elapsed > duration_s:
                break

            # Get current gimbal feedback for scene projection
            fb = driver.get_feedback(t_now)
            last_fb = fb

            # World-coordinate scene → detections visible in current gimbal frame
            detections = scene.step(dt=dt_s,
                                    gimbal_yaw_deg=fb.yaw_deg,
                                    gimbal_pitch_deg=fb.pitch_deg)

            # Inject into passthrough detector before pipeline step
            detector.inject(detections)

            # Create a synthetic "frame" (black canvas with grid)
            if cv2 is not None:
                frame = np.zeros((CAM_H, CAM_W, 3), dtype=np.uint8)
                # Subtle grid
                for x in range(0, CAM_W, 160):
                    cv2.line(frame, (x, 0), (x, CAM_H), (20, 20, 20), 1)
                for y in range(0, CAM_H, 120):
                    cv2.line(frame, (0, y), (CAM_W, y), (20, 20, 20), 1)
            else:
                frame = None

            # Pipeline step
            outputs = pipeline.step(frame, t_now)

            # Metrics
            n_frames += 1
            state = pipeline._last_track_state  # e.g. "SEARCH", "TRACK", "LOCK", "LOST"
            if state == "lock":
                n_lock += 1
            elif state == "track":
                n_track += 1

            # State-change log
            if state != prev_state:
                yaw, pitch = fb.yaw_deg, fb.pitch_deg
                target_info = ""
                if outputs.selected_target is not None:
                    obs = outputs.selected_target
                    target_info = (f"  target_id={obs.track_id}"
                                   f"  cmd=({outputs.command.yaw_rate_cmd_dps:+.1f},"
                                   f"{outputs.command.pitch_rate_cmd_dps:+.1f})dps")
                print(f"  [{elapsed:5.1f}s] {prev_state:8s} -> {state:8s}"
                      f"  gimbal=({yaw:+6.1f},{pitch:+5.1f})deg"
                      f"  tracks={len(outputs.tracks)}{target_info}")
                prev_state = state

            # Annotate and show CV2 window
            if cv2 is not None and frame is not None:
                frame = annotate_frame(
                    frame, detections, outputs,
                    fb.yaw_deg, fb.pitch_deg, elapsed,
                    state=state,
                )
                cv2.imshow("RWS Sim — Camera View", frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q") or key == 27:   # Q or Esc to quit
                    break

            # Pace control — keep real-time
            t_next = t_start + (n_frames * dt_s)
            sleep  = t_next - time.monotonic()
            if sleep > 0:
                time.sleep(sleep)

    except KeyboardInterrupt:
        print("\n[SIM] Interrupted by user.")
    finally:
        if cv2 is not None:
            cv2.destroyAllWindows()
        if hasattr(driver, "close"):
            driver.close()

    # ── summary ───────────────────────────────────────────────────────────────
    total_s = time.monotonic() - t_start
    lock_pct  = 100.0 * n_lock  / max(n_frames, 1)
    track_pct = 100.0 * n_track / max(n_frames, 1)
    fps_actual = n_frames / max(total_s, 0.001)

    if last_fb is not None:
        final_pos = f"yaw={last_fb.yaw_deg:+.1f}deg  pitch={last_fb.pitch_deg:+.1f}deg"
    else:
        final_pos = "(no frames processed)"

    print(f"\n{'='*55}")
    print(f" RWS Gimbal Simulation - Summary")
    print(f"{'='*55}")
    print(f"  Duration    : {total_s:.1f}s  ({n_frames} frames, {fps_actual:.1f} fps)")
    print(f"  LOCK  time  : {lock_pct:.1f}%  ({n_lock} frames)")
    print(f"  TRACK time  : {track_pct:.1f}%  ({n_track} frames)")
    print(f"  Final gimbal: {final_pos}")
    print(f"{'='*55}")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="RWS 2-DOF Gimbal Simulation Demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--pybullet", action="store_true",
        help="Use PyBullet physics GUI (requires: pip install pybullet pybullet_data)",
    )
    parser.add_argument(
        "--no-window", action="store_true",
        help="Headless mode — no Matplotlib or OpenCV windows (for benchmarking)",
    )
    parser.add_argument(
        "--duration", type=float, default=30.0, metavar="SECONDS",
        help="Simulation duration in seconds (default: 30)",
    )
    parser.add_argument(
        "--targets", type=int, default=4, metavar="N",
        help="Number of synthetic targets 1–6 (default: 4)",
    )
    parser.add_argument(
        "--dt", type=float, default=1.0/30.0, metavar="DT",
        help="Control-loop timestep in seconds (default: 0.0333 = 30 Hz)",
    )
    args = parser.parse_args()

    run_sim(
        duration_s=args.duration,
        dt_s=args.dt,
        n_targets=args.targets,
        use_pybullet=args.pybullet,
        show_window=not args.no_window,
    )


if __name__ == "__main__":
    main()
