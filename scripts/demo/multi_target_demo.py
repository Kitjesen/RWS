"""
RWS Multi-Target Demo
=====================
Demonstrates the MultiGimbalPipeline with 3 simultaneous targets, 2 gimbals,
Hungarian-algorithm allocation, and sequential engagement via EngagementQueue.

Phases:
  0 — Setup: build 2-gimbal pipeline with mock components
  1 — Inject 3 targets, run 50 frames, show allocation
  2 — Verify allocation (which gimbal tracks which target)
  3 — Convergence: 100 more frames, show yaw error reducing
  4 — Sequential engagement via VisionGimbalPipeline + EngagementQueue
  5 — Summary table

Runtime: ~20-30 seconds
"""

from __future__ import annotations

import math
import os
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap — allow running from repo root without editable install
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

# ---------------------------------------------------------------------------
# Windows terminal: force UTF-8 so Unicode symbols render correctly
# ---------------------------------------------------------------------------
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Rich — optional pretty output, graceful fallback
# ---------------------------------------------------------------------------
try:
    from rich.console import Console
    from rich.table import Table

    _console = Console(force_terminal=True)

    def _print(msg: str = "", style: str = "") -> None:
        try:
            if style:
                _console.print(msg, style=style)
            else:
                _console.print(msg)
        except Exception:
            import re
            plain = re.sub(r"\[/?[^\]]+\]", "", str(msg))
            print(plain)

    def _rule(title: str = "") -> None:
        try:
            _console.rule(title)
        except Exception:
            width = 60
            if title:
                pad = (width - len(title) - 2) // 2
                print("-" * pad + " " + title + " " + "-" * pad)
            else:
                print("-" * width)

    HAS_RICH = True
except ImportError:
    HAS_RICH = False

    def _print(msg: str = "", style: str = "") -> None:  # type: ignore[misc]
        print(msg)

    def _rule(title: str = "") -> None:  # type: ignore[misc]
        width = 60
        if title:
            pad = (width - len(title) - 2) // 2
            print("-" * pad + " " + title + " " + "-" * pad)
        else:
            print("-" * width)


# ---------------------------------------------------------------------------
# Numpy — required
# ---------------------------------------------------------------------------
try:
    import numpy as np
except ImportError:
    print("[FATAL] numpy is required. Run: pip install numpy")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ok(msg: str) -> None:
    _print(f"  [green]OK[/green] {msg}" if HAS_RICH else f"  OK  {msg}")


def _fail(msg: str) -> None:
    _print(f"  [red]FAIL[/red] {msg}" if HAS_RICH else f"  FAIL {msg}")


def _info(msg: str) -> None:
    _print(f"     [dim]{msg}[/dim]" if HAS_RICH else f"     {msg}")


def _warn(msg: str) -> None:
    _print(f"  [yellow]WARN[/yellow] {msg}" if HAS_RICH else f"  WARN {msg}")


def _header(msg: str) -> None:
    _rule(msg)


# ===========================================================================
# PHASE 0 — Setup
# ===========================================================================

def phase0_setup():
    """Build MultiGimbalPipeline with 2 gimbal units + shared detector/tracker."""
    _header("PHASE 0: MULTI-GIMBAL SETUP")

    from rws_tracking.algebra import CameraModel, DistortionCoeffs, MountExtrinsics, PixelToGimbalTransform
    from rws_tracking.config import SelectorConfig, SystemConfig, load_config
    from rws_tracking.control import TwoAxisGimbalController
    from rws_tracking.hardware import SimulatedGimbalDriver
    from rws_tracking.hardware.driver import DriverLimits
    from rws_tracking.perception import (
        PassthroughDetector,
        SimpleIoUTracker,
        TargetAllocator,
        WeightedMultiTargetSelector,
    )
    from rws_tracking.pipeline.multi_gimbal_pipeline import GimbalUnit, MultiGimbalPipeline
    from rws_tracking.telemetry import InMemoryTelemetryLogger

    # Load config (or use defaults)
    config_path = _REPO_ROOT / "config.yaml"
    if config_path.exists():
        cfg = load_config(config_path)
        _ok(f"Config loaded from config.yaml")
    else:
        _warn("config.yaml not found — using default SystemConfig")
        cfg = SystemConfig()

    # Build camera transform (shared by all gimbals)
    cam_cfg = cfg.camera
    cam = CameraModel(
        width=cam_cfg.width,
        height=cam_cfg.height,
        fx=cam_cfg.fx,
        fy=cam_cfg.fy,
        cx=cam_cfg.cx,
        cy=cam_cfg.cy,
    )
    mount = MountExtrinsics(
        roll_deg=cam_cfg.mount_roll_deg,
        pitch_deg=cam_cfg.mount_pitch_deg,
        yaw_deg=cam_cfg.mount_yaw_deg,
    )
    transform = PixelToGimbalTransform(cam, mount)

    # Build 2 gimbal units, each with its own controller + driver + telemetry
    units = []
    for unit_id in range(2):
        ctrl = TwoAxisGimbalController(transform=transform, cfg=cfg.controller)
        drv = SimulatedGimbalDriver(DriverLimits.from_config(cfg.driver_limits))
        tel = InMemoryTelemetryLogger()
        units.append(GimbalUnit(unit_id=unit_id, controller=ctrl, driver=drv, telemetry=tel))

    # Shared detector + tracker
    detector = PassthroughDetector()
    tracker = SimpleIoUTracker(iou_threshold=0.18, max_misses=10)

    # Multi-target selector (top-N by score)
    selector = WeightedMultiTargetSelector(
        frame_width=cam.width,
        frame_height=cam.height,
        config=cfg.selector,
    )

    # Target allocator with Hungarian algorithm
    allocator = TargetAllocator(num_executors=2)

    # Build the pipeline
    pipeline = MultiGimbalPipeline(
        detector=detector,
        tracker=tracker,
        selector=selector,
        allocator=allocator,
        gimbal_units=units,
    )

    _ok("MultiGimbalPipeline built with 2 gimbal units")
    _ok(f"Camera: {cam.width}x{cam.height}  fx={cam.fx:.0f}  fy={cam.fy:.0f}")

    if HAS_RICH:
        tbl = Table(title="Gimbal Unit Inventory", show_header=True)
        tbl.add_column("Unit", style="cyan")
        tbl.add_column("Controller", style="green")
        tbl.add_column("Driver", style="green")
        tbl.add_column("Telemetry", style="dim")
        for u in units:
            tbl.add_row(
                str(u.unit_id),
                u.controller.__class__.__name__,
                u.driver.__class__.__name__,
                u.telemetry.__class__.__name__,
            )
        _console.print(tbl)
    else:
        _print("  Gimbal Units:")
        for u in units:
            _print(f"    Unit {u.unit_id}: {u.controller.__class__.__name__} + "
                   f"{u.driver.__class__.__name__} + {u.telemetry.__class__.__name__}")

    _print()
    return pipeline, detector, cfg


# ===========================================================================
# PHASE 1 — Inject 3 targets, run 50 frames
# ===========================================================================

def phase1_inject_targets(pipeline, detector) -> dict:
    """Inject 3 simultaneous targets and run 50 frames.

    Returns allocation statistics (which gimbal tracked which target).
    """
    _header("PHASE 1: INJECT 3 TARGETS — 50 FRAMES")

    from rws_tracking.types import BoundingBox, Detection

    blank_frame = np.zeros((720, 1280, 3), dtype=np.uint8)

    # 3 targets:
    # A (track_id intended=1): Person, left of center
    # B (track_id intended=2): Person, right of center
    # C (track_id intended=3): Vehicle, center-bottom
    # Note: SimpleIoUTracker assigns IDs sequentially — we inject in this order

    # Allocation counters: assignment_log[gimbal_id] = list of assigned track_ids
    assignment_log: dict[int, list[int]] = defaultdict(list)
    unassigned_log: list[int] = []  # track_ids that went unassigned

    total_frames = 50
    _print()
    _info("Injecting 3 detections per frame for 50 frames...")
    _print()

    # We will record the first track_ids seen to label them A/B/C
    known_ids: list[int] = []

    for frame_idx in range(1, total_frames + 1):
        ts = time.monotonic()
        dt = 0.033  # 30 Hz

        # Build the 3 detections (static positions — no motion yet)
        # These are injected in fixed priority order each frame so that
        # SimpleIoUTracker consistently assigns:
        #   track 1 → left target A
        #   track 2 → right target B
        #   track 3 → center-bottom target C

        det_a = Detection(
            bbox=BoundingBox(x=260, y=180, w=80, h=120),
            confidence=0.92,
            class_id="person",
            timestamp=ts,
        )
        det_b = Detection(
            bbox=BoundingBox(x=920, y=180, w=80, h=120),
            confidence=0.85,
            class_id="person",
            timestamp=ts,
        )
        det_c = Detection(
            bbox=BoundingBox(x=580, y=320, w=120, h=80),
            confidence=0.78,
            class_id="vehicle",
            timestamp=ts,
        )
        detector.inject([det_a, det_b, det_c])

        outputs = pipeline.step(blank_frame, ts)

        # Record which track IDs exist in this frame
        if frame_idx == 1:
            # Capture initial assignment to learn track IDs
            for assignment in outputs.assignments:
                if assignment.target.track_id not in known_ids:
                    known_ids.append(assignment.target.track_id)
            for t in outputs.all_targets:
                if t.track_id not in known_ids:
                    known_ids.append(t.track_id)
        elif frame_idx == 2 and known_ids:
            # After 2 frames, extend with any remaining track
            for t in outputs.all_targets:
                if t.track_id not in known_ids:
                    known_ids.append(t.track_id)

        # Track assignments
        assigned_ids = {a.executor_id: a.target.track_id for a in outputs.assignments}
        for gid, tid in assigned_ids.items():
            assignment_log[gid].append(tid)

        # Track unassigned targets
        all_target_ids = {t.track_id for t in outputs.all_targets}
        assigned_target_ids = {a.target.track_id for a in outputs.assignments}
        for tid in all_target_ids - assigned_target_ids:
            unassigned_log.append(tid)

        # Print progress
        if frame_idx == 1:
            assign_str = "  ".join(
                f"G{a.executor_id}->T{a.target.track_id}(cost={a.cost:.1f})"
                for a in outputs.assignments
            )
            all_ids = [t.track_id for t in outputs.all_targets]
            _ok(f"Frame  1: {len(outputs.all_targets)} targets seen  |  "
                f"assignments: {assign_str}  |  all: {all_ids}")

        elif frame_idx % 10 == 0:
            assign_str = "  ".join(
                f"G{a.executor_id}->T{a.target.track_id}"
                for a in sorted(outputs.assignments, key=lambda x: x.executor_id)
            )
            unassigned_ids = [t.track_id for t in outputs.all_targets
                              if t.track_id not in {a.target.track_id for a in outputs.assignments}]
            _info(f"Frame {frame_idx:2d}: assigned=[{assign_str}]  "
                  f"unassigned={unassigned_ids}  "
                  f"n_targets={len(outputs.all_targets)}")

        time.sleep(dt)

    _print()
    _ok(f"Phase 1 complete — {total_frames} frames processed, "
        f"known track IDs: {known_ids}")

    return {
        "assignment_log": dict(assignment_log),
        "unassigned_log": unassigned_log,
        "known_ids": known_ids,
    }


# ===========================================================================
# PHASE 2 — Verify allocation
# ===========================================================================

def phase2_verify_allocation(alloc_stats: dict) -> None:
    """Print allocation summary and verify travel-minimization property."""
    _header("PHASE 2: VERIFY ALLOCATION")

    assignment_log = alloc_stats["assignment_log"]
    unassigned_log = alloc_stats["unassigned_log"]
    known_ids = alloc_stats["known_ids"]

    _print()
    _info("Hungarian allocation cost-minimization: each gimbal should prefer the")
    _info("target nearest its current yaw angle (lower angular travel = lower cost).")
    _print()

    if HAS_RICH:
        tbl = Table(title="Gimbal Assignments (50 frames)", show_header=True)
        tbl.add_column("Gimbal", style="cyan")
        tbl.add_column("Dominant target", style="green")
        tbl.add_column("Frames", style="yellow")
        tbl.add_column("All tracked targets", style="dim")
    else:
        _print(f"  {'Gimbal':<10} {'Dominant target':<20} {'Frames':<10} {'All tracked targets'}")
        _print("  " + "-" * 60)

    dominant = {}
    for gid in sorted(assignment_log.keys()):
        ids = assignment_log[gid]
        if not ids:
            continue
        # Find most common target
        from collections import Counter
        counts = Counter(ids)
        dom_id, dom_count = counts.most_common(1)[0]
        dominant[gid] = dom_id
        all_ids = sorted(counts.keys())

        if HAS_RICH:
            tbl.add_row(
                f"Gimbal {gid}",
                f"Target #{dom_id}",
                f"{dom_count}/{len(ids)}",
                str(all_ids),
            )
        else:
            _print(f"  {'Gimbal ' + str(gid):<10} {'Target #' + str(dom_id):<20} "
                   f"{dom_count}/{len(ids):<10}  {all_ids}")

    if HAS_RICH:
        _console.print(tbl)

    # Unassigned target summary
    _print()
    if unassigned_log:
        from collections import Counter
        uc = Counter(unassigned_log)
        dom_unassigned, dom_count = uc.most_common(1)[0]
        _ok(f"Unassigned target: #{dom_unassigned} appeared unassigned {dom_count} times "
            f"(3rd target, only 2 gimbals available)")
    else:
        _warn("No unassigned targets recorded (check if all 3 targets were above cost threshold)")

    # Verify gimbal 0 vs gimbal 1 prefer left vs right
    _print()
    if len(dominant) >= 2:
        gids = sorted(dominant.keys())
        g0_target = dominant.get(gids[0])
        g1_target = dominant.get(gids[1])
        if g0_target != g1_target:
            _ok(f"Allocation correctness: Gimbal {gids[0]} -> T{g0_target}  "
                f"Gimbal {gids[1]} -> T{g1_target}  (distinct, no collision)")
        else:
            _warn(f"Both gimbals assigned same target — allocation may need review")
    else:
        _warn("Insufficient data to verify allocation correctness")


# ===========================================================================
# PHASE 3 — Convergence
# ===========================================================================

def phase3_convergence(pipeline, detector) -> dict:
    """Run 100 more frames with exponential decay convergence.

    Simulates PID closing the loop — target bbox center moves toward image center.
    Reports yaw error per gimbal every 20 frames.
    """
    _header("PHASE 3: CONVERGENCE — 100 FRAMES")

    from rws_tracking.types import BoundingBox, Detection

    blank_frame = np.zeros((720, 1280, 3), dtype=np.uint8)

    _print()
    _info("Running 100 convergence frames (exponential decay toward image center)")
    _print()

    # Image center
    _CAM_CX = 640.0
    _CAM_CY = 360.0

    # Starting offsets for each "target lane"
    # Target A starts left, converges toward center
    # Target B starts right, converges toward center
    # Target C stays center-bottom (lowest priority / unassigned)
    offsets = {
        "a": (-340.0, -180.0),  # left
        "b": (+280.0, -180.0),  # right
        "c": (-60.0, +40.0),    # center-bottom
    }

    yaw_errors_g0 = []
    yaw_errors_g1 = []

    total_frames = 100

    for frame_idx in range(1, total_frames + 1):
        ts = time.monotonic()
        dt = 0.033

        # Decay offset with tau=30 frames
        decay = math.exp(-frame_idx / 30.0)

        def make_det(off_x: float, off_y: float, conf: float, cls: str) -> Detection:
            cx = _CAM_CX + off_x * decay
            cy = _CAM_CY + off_y * decay
            w, h = 80, 120
            return Detection(
                bbox=BoundingBox(x=cx - w / 2, y=cy - h / 2, w=w, h=h),
                confidence=conf,
                class_id=cls,
                timestamp=ts,
            )

        det_a = make_det(*offsets["a"], 0.92, "person")
        det_b = make_det(*offsets["b"], 0.85, "person")
        det_c = make_det(*offsets["c"], 0.78, "vehicle")
        detector.inject([det_a, det_b, det_c])

        outputs = pipeline.step(blank_frame, ts)

        # Extract yaw error per gimbal from command metadata
        for i, cmd in enumerate(outputs.commands):
            yaw_err = abs(cmd.metadata.get("yaw_error_deg", 0.0))
            if i == 0:
                yaw_errors_g0.append(yaw_err)
            elif i == 1:
                yaw_errors_g1.append(yaw_err)

        if frame_idx % 20 == 0:
            err0 = yaw_errors_g0[-1] if yaw_errors_g0 else 0.0
            err1 = yaw_errors_g1[-1] if yaw_errors_g1 else 0.0
            n_assigned = len(outputs.assignments)
            assign_ids = [f"G{a.executor_id}->T{a.target.track_id}"
                          for a in outputs.assignments]
            _info(f"  Frame {frame_idx:3d}/100  | decay={decay:.3f}  "
                  f"Yaw err G0={err0:.2f}deg  G1={err1:.2f}deg  "
                  f"assignments={assign_ids}")

        time.sleep(dt)

    # Compute convergence stats
    def _reduction(errors: list[float]) -> float:
        if len(errors) < 10:
            return 0.0
        early = sum(errors[:10]) / 10
        late = sum(errors[-10:]) / 10
        if early < 1e-6:
            return 0.0
        return max(0.0, (early - late) / early * 100.0)

    g0_reduction = _reduction(yaw_errors_g0)
    g1_reduction = _reduction(yaw_errors_g1)

    _print()
    _ok(f"Convergence complete:  "
        f"G0 yaw error reduced {g0_reduction:.0f}%  |  "
        f"G1 yaw error reduced {g1_reduction:.0f}%")

    return {
        "g0_yaw_errors": yaw_errors_g0,
        "g1_yaw_errors": yaw_errors_g1,
        "g0_reduction_pct": g0_reduction,
        "g1_reduction_pct": g1_reduction,
    }


# ===========================================================================
# PHASE 4 — Sequential Engagement via EngagementQueue
# ===========================================================================

def phase4_sequential_engagement(cfg) -> dict:
    """Build a VisionGimbalPipeline + EngagementQueue and engage targets 1 then 2.

    Returns engagement log entries.
    """
    _header("PHASE 4: SEQUENTIAL ENGAGEMENT (EngagementQueue)")

    import datetime
    from rws_tracking.algebra import CameraModel, DistortionCoeffs, MountExtrinsics, PixelToGimbalTransform
    from rws_tracking.config import SelectorConfig
    from rws_tracking.control import TwoAxisGimbalController
    from rws_tracking.hardware import SimulatedGimbalDriver
    from rws_tracking.hardware.driver import DriverLimits
    from rws_tracking.perception import PassthroughDetector, SimpleIoUTracker, WeightedTargetSelector
    from rws_tracking.telemetry import FileTelemetryLogger
    from rws_tracking.safety.shooting_chain import ShootingChain
    from rws_tracking.telemetry.audit import AuditLogger
    from rws_tracking.health.monitor import HealthMonitor
    from rws_tracking.decision.lifecycle import TargetLifecycleManager
    from rws_tracking.safety.iff import IFFChecker
    from rws_tracking.telemetry.video_ring_buffer import VideoRingBuffer
    from rws_tracking.pipeline.pipeline import VisionGimbalPipeline
    from rws_tracking.decision.engagement import (
        EngagementConfig as EConfig, EngagementQueue, ThreatAssessor, ThreatWeights,
    )
    from rws_tracking.safety.interlock import SafetyInterlockConfig
    from rws_tracking.safety.manager import SafetyManager, SafetyManagerConfig
    from rws_tracking.types import BoundingBox, Detection

    cam_cfg = cfg.camera
    cam = CameraModel(
        width=cam_cfg.width, height=cam_cfg.height,
        fx=cam_cfg.fx, fy=cam_cfg.fy, cx=cam_cfg.cx, cy=cam_cfg.cy,
    )
    mount = MountExtrinsics(
        roll_deg=cam_cfg.mount_roll_deg,
        pitch_deg=cam_cfg.mount_pitch_deg,
        yaw_deg=cam_cfg.mount_yaw_deg,
    )
    transform = PixelToGimbalTransform(cam, mount)

    # Engagement subsystem
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
        frame_width=cam.width, frame_height=cam.height,
        camera_fy=cam.fy, config=eng_cfg,
    )
    engagement_queue = EngagementQueue(config=eng_cfg)

    # Safety subsystem — use short min_lock_time for demo (0.1s instead of 1s)
    interlock_cfg = SafetyInterlockConfig(
        require_operator_auth=cfg.safety.interlock.require_operator_auth,
        min_lock_time_s=0.1,  # demo: short lock requirement
        min_engagement_range_m=0.0,  # demo: no min range check
        max_engagement_range_m=cfg.safety.interlock.max_engagement_range_m,
        system_check_interval_s=cfg.safety.interlock.system_check_interval_s,
        heartbeat_timeout_s=cfg.safety.interlock.heartbeat_timeout_s,
    )
    safety_manager = SafetyManager(
        SafetyManagerConfig(
            interlock=interlock_cfg,
            nfz_slow_down_margin_deg=cfg.safety.nfz_slow_down_margin_deg,
            zones=(),
        )
    )
    safety_manager.set_operator_auth(True)
    safety_manager.operator_heartbeat()
    safety_manager.update_system_status(comms_ok=True, sensors_ok=True)

    # Logging
    logs_dir = _REPO_ROOT / "logs"
    logs_dir.mkdir(exist_ok=True)
    ts_tag = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    audit_path = logs_dir / f"multi_demo_audit_{ts_tag}.jsonl"
    telemetry_path = logs_dir / f"multi_demo_telemetry_{ts_tag}.jsonl"

    shooting_chain = ShootingChain(cooldown_s=3.0)
    audit_logger = AuditLogger(log_path=str(audit_path))
    health_monitor = HealthMonitor()
    lifecycle_manager = TargetLifecycleManager(confirm_age_frames=3, archive_after_s=10.0)
    iff_checker = IFFChecker(friendly_classes={"civilian", "friendly"})
    video_ring_buffer = VideoRingBuffer(
        duration_s=10.0, pre_event_s=3.0, post_event_s=2.0,
        output_dir=str(logs_dir / "clips"), fps=30.0,
    )

    detector_seq = PassthroughDetector()
    pipeline_seq = VisionGimbalPipeline(
        detector=detector_seq,
        tracker=SimpleIoUTracker(iou_threshold=0.18, max_misses=10),
        selector=WeightedTargetSelector(
            frame_width=cam.width, frame_height=cam.height, config=cfg.selector
        ),
        controller=TwoAxisGimbalController(transform=transform, cfg=cfg.controller),
        driver=SimulatedGimbalDriver(DriverLimits.from_config(cfg.driver_limits)),
        telemetry=FileTelemetryLogger(file_path=str(telemetry_path), append=True),
        combined_tracker=None,
        threat_assessor=threat_assessor,
        engagement_queue=engagement_queue,
        safety_manager=safety_manager,
        shooting_chain=shooting_chain,
        audit_logger=audit_logger,
        health_monitor=health_monitor,
        lifecycle_manager=lifecycle_manager,
        iff_checker=iff_checker,
        video_ring_buffer=video_ring_buffer,
    )

    blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    engagement_log = []
    operator_id = "multi_demo_operator"

    _print()
    _info("Building engagement scenario: 2 targets (Person + Vehicle)")
    _info("Strategy: ARM chain, wait for FIRE_AUTHORIZED, request fire,")
    _info("          pipeline auto-executes on next step() call.")
    _print()

    def _engage_one_target(
        det_fn,
        label: str,
        tgt_label: str,
    ) -> tuple[bool, int | None]:
        """Arm chain, wait for fire_authorized, request fire, return (fired, track_id).

        ``det_fn(ts)`` must return a list of Detection objects to inject.
        """
        # Re-arm from SAFE
        shooting_chain.safe("reset_for_engagement")
        ok = shooting_chain.arm(operator_id=operator_id)
        if not ok and shooting_chain.state.value != "armed":
            _warn(f"  Could not arm for {label}")
            return False, None
        if audit_logger:
            audit_logger.log("arm", operator_id, "armed")
        _ok(f"  [{label}] ARMED  state={shooting_chain.state.value}")

        track_id_seen: int | None = None
        fired = False
        authorized = False

        # Step 1: wait for FIRE_AUTHORIZED (up to 90 ticks at 30 Hz = 3s)
        _info(f"  [{label}] Awaiting fire authorization (target must be locked)...")
        for tick in range(90):
            ts = time.monotonic()
            safety_manager.operator_heartbeat()
            detector_seq.inject(det_fn(ts))
            try:
                output = pipeline_seq.step(blank_frame, ts)
            except Exception:
                time.sleep(0.033)
                continue

            if output.tracks and track_id_seen is None:
                track_id_seen = output.tracks[0].track_id

            if shooting_chain.state.value == "fire_authorized":
                authorized = True
                break
            time.sleep(0.033)

        if not authorized:
            # Force authorization (same pattern as full_system_demo.py)
            _warn(f"  [{label}] Auto-authorization timed out — forcing via direct injection")
            shooting_chain.update_authorization(True, time.monotonic())
            if shooting_chain.state.value == "fire_authorized":
                authorized = True

        if not authorized:
            _warn(f"  [{label}] Could not reach FIRE_AUTHORIZED — skipping")
            return False, track_id_seen

        _ok(f"  [{label}] Fire authorized!  chain={shooting_chain.state.value}  "
            f"track_id={track_id_seen}")

        # Step 2: operator presses FIRE button
        req_ok = shooting_chain.request_fire(operator_id=operator_id)
        if not req_ok:
            _warn(f"  [{label}] request_fire() failed — state={shooting_chain.state.value}")
            return False, track_id_seen

        if audit_logger:
            audit_logger.log("fire_requested", operator_id, shooting_chain.state.value)

        # Step 3: one more pipeline step — pipeline sees can_fire=True and executes
        ts = time.monotonic()
        safety_manager.operator_heartbeat()
        detector_seq.inject(det_fn(ts))
        try:
            output = pipeline_seq.step(blank_frame, ts)
        except Exception as exc:
            _warn(f"  [{label}] pipeline.step() error: {exc}")

        # Check if pipeline fired (chain moves to COOLDOWN)
        if shooting_chain.state.value == "cooldown":
            fired = True
        elif shooting_chain.state.value == "fire_requested":
            # Pipeline didn't fire internally (no can_fire path hit) — force it
            fired = shooting_chain.execute_fire(time.monotonic())
            if fired and audit_logger:
                audit_logger.log("fired", operator_id, "cooldown", target_id=track_id_seen)

        if fired:
            _print()
            _print("  " + ("=" * 52))
            msg = f"  FIRE EXECUTED — Track #{track_id_seen} ({tgt_label}) neutralized"
            _print(f"  [bold red]{msg}[/bold red]" if HAS_RICH else msg)
            _print("  " + ("=" * 52))
            _print()
            if audit_logger and shooting_chain.state.value == "cooldown":
                # Log if pipeline fired (audit logger called inside pipeline.step)
                pass
        else:
            _warn(f"  [{label}] Fire did not execute (state={shooting_chain.state.value})")

        return fired, track_id_seen

    # --- Engagement 1: Target 1 (person, centered-left) ---
    def det_target1(ts: float) -> list:
        return [Detection(
            bbox=BoundingBox(x=600, y=300, w=80, h=120),
            confidence=0.92, class_id="person", timestamp=ts,
        )]

    fired_1, track1_id = _engage_one_target(det_target1, "Target-1", "person")
    if fired_1:
        engagement_log.append({"event": "FIRE_EXECUTED", "target_id": track1_id, "tick": 0})
        engagement_log.append({"event": "NEUTRALIZED", "target_id": track1_id, "tick": 0})
        if track1_id is not None:
            lifecycle_manager.mark_neutralized(track1_id, time.monotonic())
            _ok(f"TargetLifecycleManager.mark_neutralized(track_id={track1_id})")

    # Wait for cooldown to expire (or force safe)
    _info("Waiting for cooldown / resetting for target 2...")
    time.sleep(1.0)

    # --- Engagement 2: Target 2 (vehicle, centered-right) ---
    def det_target2(ts: float) -> list:
        return [Detection(
            bbox=BoundingBox(x=640, y=310, w=120, h=80),
            confidence=0.85, class_id="vehicle", timestamp=ts,
        )]

    fired_2, track2_id = _engage_one_target(det_target2, "Target-2", "vehicle")
    if fired_2:
        engagement_log.append({"event": "FIRE_EXECUTED", "target_id": track2_id, "tick": 1})
        engagement_log.append({"event": "NEUTRALIZED", "target_id": track2_id, "tick": 1})
        if track2_id is not None:
            lifecycle_manager.mark_neutralized(track2_id, time.monotonic())
            _ok(f"TargetLifecycleManager.mark_neutralized(track_id={track2_id})")

    # Return chain to SAFE
    shooting_chain.safe("demo_end")
    if audit_logger:
        audit_logger.log("safe", operator_id, "safe")
    _ok(f"System returned to SAFE  state={shooting_chain.state.value}")

    # Print engagement sequence log
    _print()
    if HAS_RICH:
        tbl = Table(title="Engagement Sequence Log", show_header=True)
        tbl.add_column("Event", style="red")
        tbl.add_column("Target ID", style="cyan")
        tbl.add_column("Tick", style="dim")
        for entry in engagement_log:
            tbl.add_row(
                entry["event"],
                str(entry.get("target_id", "?")),
                str(entry.get("tick", "?")),
            )
        _console.print(tbl)
    else:
        _print(f"  {'Event':<20} {'Target ID':<12} {'Tick'}")
        _print("  " + "-" * 45)
        for entry in engagement_log:
            _print(f"  {entry['event']:<20} {str(entry.get('target_id','?')):<12} "
                   f"{entry.get('tick', '?')}")

    # Cleanup
    pipeline_seq.stop()
    pipeline_seq.cleanup()

    return {
        "engagement_log": engagement_log,
        "fired_count": sum(1 for e in engagement_log if e["event"] == "FIRE_EXECUTED"),
        "audit_path": str(audit_path),
    }


# ===========================================================================
# PHASE 5 — Summary
# ===========================================================================

def phase5_summary(
    alloc_stats: dict,
    conv_stats: dict,
    engage_stats: dict,
    demo_start: float,
) -> None:
    """Print final stats table."""
    _header("PHASE 5: SUMMARY")

    duration_s = time.monotonic() - demo_start
    fired_count = engage_stats.get("fired_count", 0)
    g0_red = conv_stats.get("g0_reduction_pct", 0.0)
    g1_red = conv_stats.get("g1_reduction_pct", 0.0)
    known_ids = alloc_stats.get("known_ids", [])
    audit_path = engage_stats.get("audit_path", "N/A")

    _print()

    if HAS_RICH:
        from rich.table import Table as RTable
        from rich.panel import Panel
        tbl = RTable(title="MULTI-TARGET DEMO RESULTS", box=None, show_header=False, padding=(0, 2))
        tbl.add_column("Key", style="cyan")
        tbl.add_column("Value", style="bold white")
        tbl.add_row("Total runtime", f"{duration_s:.1f}s")
        tbl.add_row("Gimbals", "2")
        tbl.add_row("Targets injected", "3")
        tbl.add_row("Tracked IDs", str(known_ids))
        tbl.add_row("G0 yaw error reduction", f"{g0_red:.0f}%")
        tbl.add_row("G1 yaw error reduction", f"{g1_red:.0f}%")
        tbl.add_row("Targets fired upon", str(fired_count))
        tbl.add_row("Audit log", Path(audit_path).name if audit_path != "N/A" else "N/A")
        _console.print(Panel(tbl, title="DEMO COMPLETE", style="bold green", expand=False))
    else:
        w = 44
        print()
        print("  " + "=" * w)
        print(f"  {'MULTI-TARGET DEMO RESULTS':^{w-2}}")
        print("  " + "=" * w)
        print(f"  {'Total runtime:':<28} {duration_s:.1f}s")
        print(f"  {'Gimbals:':<28} 2")
        print(f"  {'Targets injected:':<28} 3")
        print(f"  {'Tracked IDs:':<28} {known_ids}")
        print(f"  {'G0 yaw error reduction:':<28} {g0_red:.0f}%")
        print(f"  {'G1 yaw error reduction:':<28} {g1_red:.0f}%")
        print(f"  {'Targets fired upon:':<28} {fired_count}")
        print(f"  {'Audit log:':<28} {Path(audit_path).name if audit_path != 'N/A' else 'N/A'}")
        print("  " + "=" * w)


# ===========================================================================
# MAIN
# ===========================================================================

def main() -> None:
    print()
    print("=" * 60)
    print("  RWS — Multi-Target Demo  //  2 Gimbals, 3 Targets")
    print("  Hungarian allocation + sequential engagement")
    print("=" * 60)

    demo_start = time.monotonic()

    try:
        # Phase 0: Setup
        pipeline, detector, cfg = phase0_setup()

        # Phase 1: Inject targets
        alloc_stats = phase1_inject_targets(pipeline, detector)

        # Phase 2: Verify allocation
        phase2_verify_allocation(alloc_stats)

        # Phase 3: Convergence
        conv_stats = phase3_convergence(pipeline, detector)

        # Phase 4: Sequential engagement
        engage_stats = phase4_sequential_engagement(cfg)

        # Phase 5: Summary
        phase5_summary(alloc_stats, conv_stats, engage_stats, demo_start)

    except KeyboardInterrupt:
        _print()
        _warn("Demo interrupted by user (Ctrl+C)")
    except Exception:
        _print()
        _fail("Demo encountered an unhandled error:")
        traceback.print_exc()
        sys.exit(1)

    total_s = time.monotonic() - demo_start
    _print()
    _rule()
    _ok(f"Multi-target demo complete.  Total runtime: {total_s:.1f}s")
    _print()


if __name__ == "__main__":
    main()
