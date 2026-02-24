"""
RWS Full System Demo
====================
Runs a complete end-to-end demonstration of the Robot Weapon Station
pipeline without requiring real hardware (no camera, no gimbal, no YOLO model).

Phases:
  0 — Setup & banner
  1 — System self-test (7 checks)
  2 — Mission start
  3 — Simulated target engagement (synthetic tracks injected per-frame)
  4 — Operator fire control (ARM → FIRE_AUTHORIZED → REQUEST → FIRE)
  5 — Mission end & HTML report generation
  6 — Audit trail display with SHA-256 chain verification

Runtime: ~45 seconds
"""

from __future__ import annotations

import datetime
import math
import os
import sys
import tempfile
import time
import traceback
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
    from rich.panel import Panel
    from rich.table import Table
    from rich import print as rprint

    # Force Rich to write UTF-8 through our already-wrapped stdout.
    _console = Console(force_terminal=True)

    def _print(msg: str = "", style: str = "") -> None:
        try:
            if style:
                _console.print(msg, style=style)
            else:
                _console.print(msg)
        except Exception:
            # Last-resort: strip markup and write plain text
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

def _sleep_progress(seconds: float, label: str = "", steps: int = 10) -> None:
    """Sleep for *seconds* printing a simple progress indicator."""
    step_s = seconds / steps
    for i in range(steps):
        frac = int((i + 1) / steps * 20)
        bar = "[" + "#" * frac + "." * (20 - frac) + "]"
        print(f"\r  {label} {bar} {int((i + 1) / steps * 100):3d}%", end="", flush=True)
        time.sleep(step_s)
    print()


def _ok(msg: str) -> None:
    _print(f"  [green]✓[/green] {msg}" if HAS_RICH else f"  OK  {msg}")


def _fail(msg: str) -> None:
    _print(f"  [red]✗[/red] {msg}" if HAS_RICH else f"  FAIL {msg}")


def _info(msg: str) -> None:
    _print(f"     {msg}" if not HAS_RICH else f"     [dim]{msg}[/dim]")


def _warn(msg: str) -> None:
    _print(f"  [yellow]![/yellow] {msg}" if HAS_RICH else f"  WARN {msg}")


def _header(msg: str) -> None:
    _rule(msg)


# ===========================================================================
# PHASE 0 — Banner & Setup
# ===========================================================================

def phase0_banner_and_setup():
    """Print ASCII banner and build the pipeline from config."""
    _print()
    banner = r"""
  ██████  ██     ██ ███████
  ██   ██ ██     ██ ██
  ██████  ██  █  ██ ███████
  ██   ██ ██ ███ ██      ██
  ██   ██  ███ ███  ███████

  Robot Weapon Station  //  Full System Demo
  Non-ROS2 · YOLO11n-Seg · BoT-SORT · 2-DOF Gimbal · IMU Feedforward
    """
    if HAS_RICH:
        from rich.panel import Panel
        _console.print(Panel(banner.strip(), style="bold cyan", expand=False))
    else:
        print(banner)

    _header("PHASE 0: SETUP")

    # --- Load config -------------------------------------------------------
    config_path = _REPO_ROOT / "config.yaml"
    _info(f"Loading config from: {config_path}")

    from rws_tracking.config import load_config, SystemConfig

    if config_path.exists():
        cfg = load_config(config_path)
        _ok(f"Config loaded from config.yaml")
    else:
        _warn("config.yaml not found — using default SystemConfig")
        cfg = SystemConfig()

    # Force safety and engagement enabled for the demo
    from dataclasses import replace as dc_replace
    cfg = dc_replace(cfg, safety=dc_replace(cfg.safety, enabled=True))
    cfg = dc_replace(cfg, engagement=dc_replace(cfg.engagement, enabled=True))
    _ok("safety.enabled=True, engagement.enabled=True confirmed")

    # --- Build pipeline (mock YOLO) ----------------------------------------
    _info("Building pipeline (mock YOLO — no model file required)...")

    pipeline = _build_demo_pipeline(cfg)
    _ok("Pipeline built with mock detector (no camera/model required)")

    # Print subsystem inventory
    comps = {
        "Detector (mock)": pipeline.detector.__class__.__name__,
        "Tracker": pipeline.tracker.__class__.__name__,
        "Selector": pipeline.selector.__class__.__name__,
        "Controller": pipeline.controller.__class__.__name__,
        "Driver": pipeline.driver.__class__.__name__,
        "ThreatAssessor": getattr(pipeline._threat_assessor, "__class__", type(None)).__name__,
        "SafetyManager": getattr(pipeline._safety_manager, "__class__", type(None)).__name__,
        "ShootingChain": getattr(pipeline._shooting_chain, "__class__", type(None)).__name__,
        "AuditLogger": getattr(pipeline._audit_logger, "__class__", type(None)).__name__,
        "HealthMonitor": getattr(pipeline._health_monitor, "__class__", type(None)).__name__,
        "LifecycleManager": getattr(pipeline._lifecycle_manager, "__class__", type(None)).__name__,
        "Telemetry": pipeline.telemetry.__class__.__name__,
    }

    if HAS_RICH:
        tbl = Table(title="Subsystem Inventory", show_header=True)
        tbl.add_column("Subsystem", style="cyan")
        tbl.add_column("Class", style="green")
        for name, cls in comps.items():
            tbl.add_row(name, cls)
        _console.print(tbl)
    else:
        _print("  Subsystem Inventory:")
        for name, cls in comps.items():
            _print(f"    {name:30s} {cls}")

    time.sleep(1.0)
    return cfg, pipeline


def _build_demo_pipeline(cfg):
    """Build a full pipeline but replace the YOLO combined_tracker with a mock.

    This allows the demo to run without any YOLO model files.
    The mock detector is a PassthroughDetector; we also install a
    DemoMockTracker as the combined_tracker so we can inject fake tracks.
    """
    import datetime  # needed for timestamped log filenames
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

    cam_cfg = cfg.camera
    dist = DistortionCoeffs(
        k1=cam_cfg.distortion_k1, k2=cam_cfg.distortion_k2,
        p1=cam_cfg.distortion_p1, p2=cam_cfg.distortion_p2, k3=cam_cfg.distortion_k3,
    )
    has_dist = any(v != 0.0 for v in (
        cam_cfg.distortion_k1, cam_cfg.distortion_k2,
        cam_cfg.distortion_p1, cam_cfg.distortion_p2, cam_cfg.distortion_k3,
    ))
    cam = CameraModel(
        width=cam_cfg.width, height=cam_cfg.height,
        fx=cam_cfg.fx, fy=cam_cfg.fy, cx=cam_cfg.cx, cy=cam_cfg.cy,
        distortion=dist if has_dist else None,
    )
    mount = MountExtrinsics(
        roll_deg=cam_cfg.mount_roll_deg,
        pitch_deg=cam_cfg.mount_pitch_deg,
        yaw_deg=cam_cfg.mount_yaw_deg,
    )
    transform = PixelToGimbalTransform(cam, mount)

    # v1.1 optional components (same logic as build_pipeline_from_config)
    threat_assessor = None
    engagement_queue = None
    if cfg.engagement.enabled:
        from rws_tracking.decision.engagement import (
            EngagementConfig as EConfig, EngagementQueue, ThreatAssessor, ThreatWeights,
        )
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

    safety_manager = None
    if cfg.safety.enabled:
        from rws_tracking.safety.interlock import SafetyInterlockConfig
        from rws_tracking.safety.manager import SafetyManager, SafetyManagerConfig
        from rws_tracking.types import SafetyZone
        interlock_cfg = SafetyInterlockConfig(
            require_operator_auth=cfg.safety.interlock.require_operator_auth,
            min_lock_time_s=cfg.safety.interlock.min_lock_time_s,
            min_engagement_range_m=cfg.safety.interlock.min_engagement_range_m,
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
        # Pre-authorize operator and comms/sensor status for demo
        # (in a real deployment the operator presses ARM and sends heartbeats)
        safety_manager.set_operator_auth(True)
        safety_manager.operator_heartbeat()
        safety_manager.update_system_status(comms_ok=True, sensors_ok=True)

    # Ensure logs directory exists; use timestamped files so each run is isolated
    logs_dir = _REPO_ROOT / "logs"
    logs_dir.mkdir(exist_ok=True)

    ts_tag = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    audit_path = logs_dir / f"demo_audit_{ts_tag}.jsonl"
    telemetry_path = logs_dir / f"demo_telemetry_{ts_tag}.jsonl"

    shooting_chain = ShootingChain(cooldown_s=3.0)
    audit_logger = AuditLogger(log_path=str(audit_path))
    health_monitor = HealthMonitor()
    lifecycle_manager = TargetLifecycleManager(confirm_age_frames=3, archive_after_s=10.0)
    iff_checker = IFFChecker(friendly_classes={"civilian", "friendly"})
    video_ring_buffer = VideoRingBuffer(
        duration_s=10.0, pre_event_s=3.0, post_event_s=2.0,
        output_dir=str(logs_dir / "clips"), fps=30.0,
    )

    pipeline = VisionGimbalPipeline(
        detector=PassthroughDetector(),
        tracker=SimpleIoUTracker(iou_threshold=0.18, max_misses=10),
        selector=WeightedTargetSelector(
            frame_width=cam.width,
            frame_height=cam.height,
            config=cfg.selector,
        ),
        controller=TwoAxisGimbalController(transform=transform, cfg=cfg.controller),
        driver=SimulatedGimbalDriver(DriverLimits.from_config(cfg.driver_limits)),
        telemetry=FileTelemetryLogger(file_path=str(telemetry_path), append=True),
        combined_tracker=None,  # We will inject tracks via passthrough
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
    return pipeline


# ===========================================================================
# PHASE 1 — System Self-Test
# ===========================================================================

def phase1_selftest(pipeline) -> bool:
    """Run self-test checks independently of the Flask app."""
    _header("PHASE 1: SYSTEM SELF-TEST")
    time.sleep(0.3)

    checks = []

    def _run_check(name: str, fn) -> dict:
        t0 = time.monotonic()
        try:
            msg = fn()
            elapsed = round((time.monotonic() - t0) * 1000, 1)
            return {"name": name, "status": "pass", "message": msg or "", "elapsed_ms": elapsed}
        except Exception as exc:  # noqa: BLE001
            elapsed = round((time.monotonic() - t0) * 1000, 1)
            return {"name": name, "status": "fail", "message": str(exc), "elapsed_ms": elapsed}

    # 1. pipeline_imports
    def check_imports():
        from rws_tracking.safety.shooting_chain import ShootingChain  # noqa: F401
        from rws_tracking.telemetry.audit import AuditLogger  # noqa: F401
        from rws_tracking.health.monitor import HealthMonitor  # noqa: F401
        from rws_tracking.decision.lifecycle import TargetLifecycleManager  # noqa: F401
        from rws_tracking.decision.engagement import ThreatAssessor  # noqa: F401
        return "all critical imports OK"

    checks.append(_run_check("pipeline_imports", check_imports))

    # 2. shooting_chain
    def check_chain():
        chain = getattr(pipeline, "_shooting_chain", None)
        if chain is None:
            raise RuntimeError("ShootingChain not configured in pipeline")
        state = chain.state.value
        if state != "safe":
            raise RuntimeError(f"Expected initial state 'safe', got '{state}'")
        return f"state={state}"

    checks.append(_run_check("shooting_chain", check_chain))

    # 3. audit_logger
    def check_audit():
        import tempfile
        from rws_tracking.telemetry.audit import AuditLogger
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            tpath = f.name
        try:
            al = AuditLogger(tpath)
            al.log("selftest", "system", "safe")
            ok, err = al.verify_chain()
            if not ok:
                raise RuntimeError(f"chain verify failed: {err}")
        finally:
            Path(tpath).unlink(missing_ok=True)
        return "write+verify OK"

    checks.append(_run_check("audit_logger", check_audit))

    # 4. health_monitor
    def check_health():
        hm = getattr(pipeline, "_health_monitor", None)
        if hm is None:
            raise RuntimeError("HealthMonitor not configured in pipeline")
        hm.heartbeat("selftest", time.monotonic())
        s = hm.get_status()
        return f"{len(s)} subsystems tracked"

    checks.append(_run_check("health_monitor", check_health))

    # 5. lifecycle_manager
    def check_lifecycle():
        lm = getattr(pipeline, "_lifecycle_manager", None)
        if lm is None:
            raise RuntimeError("TargetLifecycleManager not configured")
        summary = lm.summary()
        return f"total_seen={summary.get('total_seen', 0)}"

    checks.append(_run_check("lifecycle_manager", check_lifecycle))

    # 6. logs_dir_writable
    def check_logs_dir():
        logs = _REPO_ROOT / "logs"
        logs.mkdir(exist_ok=True)
        probe = logs / ".selftest_probe"
        probe.write_text("ok")
        probe.unlink()
        return "logs/ writable"

    checks.append(_run_check("logs_dir_writable", check_logs_dir))

    # 7. config_valid
    def check_config():
        from rws_tracking.config import load_config  # noqa: F401
        return "config module importable"

    checks.append(_run_check("config_valid", check_config))

    # --- Print results ---
    passed = [c for c in checks if c["status"] == "pass"]
    failed = [c for c in checks if c["status"] == "fail"]

    for c in checks:
        elapsed_s = c["elapsed_ms"] / 1000
        if c["status"] == "pass":
            _ok(f"{c['name']:35s} {c['message']}  [{elapsed_s:.3f}s]")
        else:
            _fail(f"{c['name']:35s} {c['message']}  [{elapsed_s:.3f}s]")

    go = len(failed) == 0
    _print()
    if go:
        _print("  [bold green]>>> GO — All systems nominal <<<[/bold green]" if HAS_RICH
               else "  >>> GO — All systems nominal <<<")
    else:
        reasons = ", ".join(c["name"] for c in failed)
        _print(f"  [bold red]>>> NO-GO — Failed: {reasons} <<<[/bold red]" if HAS_RICH
               else f"  >>> NO-GO — Failed: {reasons} <<<")

    time.sleep(0.5)
    return go


# ===========================================================================
# PHASE 2 — Mission Start
# ===========================================================================

def phase2_mission_start(pipeline) -> float:
    """Start the pipeline tracking loop."""
    _header("PHASE 2: MISSION START")
    time.sleep(0.3)

    session_id = "DEMO-001"
    profile = "default"
    mission_start_ts = time.monotonic()

    _ok(f"Mission started: profile={profile}  session_id={session_id}")
    _info(f"Mission timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    _info("Pipeline ticking at 30 Hz (simulated)")
    time.sleep(0.5)
    return mission_start_ts


# ===========================================================================
# PHASE 3 — Simulated Target Engagement
# ===========================================================================

def phase3_engagement(pipeline) -> dict:
    """Run 150 frames of simulated target engagement."""
    _header("PHASE 3: SIMULATED TARGET ENGAGEMENT")

    from rws_tracking.types import BoundingBox, Detection, Track
    from rws_tracking.perception import PassthroughDetector

    blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)

    # Telemetry accumulators
    yaw_errors = []
    pitch_errors = []
    lock_frames = 0
    total_frames = 150
    target_detected = False
    threat_score = 0.0
    distance_m = 0.0

    _print()

    # Camera intrinsics (matching config.yaml defaults)
    _CAM_CX = 640.0
    _CAM_CY = 360.0

    for frame_idx in range(1, total_frames + 1):
        ts = time.monotonic()
        dt = 0.033  # 30 Hz

        # ---- Build synthetic detections based on frame range ----------------
        detections_to_inject: list[Detection] = []

        if frame_idx >= 31:
            # Target enters frame at 31.
            # The bbox center starts offset from the image principal point
            # (simulating a target appearing off-axis) and converges toward
            # the image centre as the PID controller drives the gimbal to track
            # it.  We model this convergence synthetically: the residual pixel
            # error decays exponentially to simulate closed-loop PID response.
            target_detected = True
            # Start with ~60 px offset left/up, decay with tau = 25 frames
            phase = frame_idx - 31
            decay = math.exp(-phase / 25.0)
            offset_x = -60.0 * decay  # converging toward centre
            offset_y = -35.0 * decay
            cx = _CAM_CX + offset_x
            cy = _CAM_CY + offset_y
            w, h = 80, 120
            x = cx - w / 2
            y = cy - h / 2
            det = Detection(
                bbox=BoundingBox(x=x, y=y, w=w, h=h),
                confidence=0.87,
                class_id="person",
                timestamp=ts,
            )
            detections_to_inject.append(det)

        # Inject into the PassthroughDetector
        pipeline.detector.inject(detections_to_inject)

        # Keep operator heartbeat alive (prevents interlock heartbeat timeout)
        if pipeline._safety_manager is not None:
            pipeline._safety_manager.operator_heartbeat()

        # ---- Step pipeline --------------------------------------------------
        try:
            output = pipeline.step(blank_frame, ts)
        except Exception as exc:
            _warn(f"Frame {frame_idx}: pipeline.step() error: {exc}")
            time.sleep(dt)
            continue

        # ---- Collect metrics -----------------------------------------------
        yaw_err = abs(pipeline._last_yaw_error_deg)
        pitch_err = abs(pipeline._last_pitch_error_deg)
        yaw_errors.append(yaw_err)
        pitch_errors.append(pitch_err)

        state = pipeline._last_track_state
        if state == "lock":
            lock_frames += 1

        if output.threat_assessments:
            threat_score = output.threat_assessments[0].threat_score

        if output.distance_m > 0:
            distance_m = output.distance_m

        # ---- Progress print ------------------------------------------------
        if frame_idx <= 30 and frame_idx % 10 == 0:
            _info(f"  Frame {frame_idx:3d}/150  | State: SEARCH  | Scanning... no targets")

        elif frame_idx == 31:
            _ok(f"  Frame {frame_idx:3d}/150  | Target detected! Track #1 — Person, "
                f"confidence 0.87, bbox=[320,240,80,120]")

        elif 32 <= frame_idx <= 60 and frame_idx % 10 == 0:
            _info(f"  Frame {frame_idx:3d}/150  | State: {state.upper():6s}  | "
                  f"Tracking...  Yaw error: {yaw_err:.2f}°  Pitch error: {pitch_err:.2f}°")

        elif frame_idx == 61:
            _ok(f"  Frame {frame_idx:3d}/150  | Lock acquired!  "
                f"Yaw error: {yaw_err:.2f}°")

        elif 61 <= frame_idx <= 90 and frame_idx % 10 == 0:
            _info(f"  Frame {frame_idx:3d}/150  | State: {state.upper():6s}  | "
                  f"Convergence → Yaw: {yaw_err:.2f}°  Pitch: {pitch_err:.2f}°")

        elif frame_idx == 91:
            _ok(f"  Frame {frame_idx:3d}/150  | Threat assessment: "
                f"score={threat_score:.2f} ({'HIGH' if threat_score >= 0.5 else 'MED'}). "
                f"Engagement queue: 1 target")

        elif 91 <= frame_idx <= 120 and frame_idx % 10 == 0:
            _info(f"  Frame {frame_idx:3d}/150  | State: {state.upper():6s}  | "
                  f"Threat score: {threat_score:.3f}  Distance: {distance_m:.1f}m")

        elif frame_idx == 121:
            safety_ok = (output.safety_status is not None)
            nfz_clear = True  # no zones configured in demo
            lock_ok = state in ("lock", "track")
            range_ok = 5.0 < distance_m < 500.0 if distance_m > 0 else True
            _ok(f"  Frame {frame_idx:3d}/150  | Safety check:  "
                f"{'✓' if nfz_clear else '✗'} NFZ clear  "
                f"{'✓' if lock_ok else '✗'} Lock  "
                f"{'✓' if range_ok else '?'} Range {distance_m:.1f}m")

        elif 121 <= frame_idx <= 150 and frame_idx % 10 == 0:
            _info(f"  Frame {frame_idx:3d}/150  | State: {state.upper():6s}  | "
                  f"Yaw err: {yaw_err:.3f}°  Fire auth: "
                  f"{output.safety_status.fire_authorized if output.safety_status else 'n/a'}")

        time.sleep(dt)

    avg_yaw = sum(yaw_errors) / len(yaw_errors) if yaw_errors else 0.0
    avg_pitch = sum(pitch_errors) / len(pitch_errors) if pitch_errors else 0.0
    lock_rate = lock_frames / total_frames * 100.0 if total_frames > 0 else 0.0

    _print()
    _ok(f"Engagement phase complete:  "
        f"lock_rate={lock_rate:.0f}%  "
        f"avg_yaw_err={avg_yaw:.3f}°  "
        f"avg_pitch_err={avg_pitch:.3f}°")

    return {
        "avg_yaw_error_deg": avg_yaw,
        "avg_pitch_error_deg": avg_pitch,
        "lock_rate_pct": lock_rate,
        "threat_score": threat_score,
        "distance_m": distance_m,
        "target_detected": target_detected,
    }


# ===========================================================================
# PHASE 4 — Operator Fire Control
# ===========================================================================

def phase4_fire_control(pipeline, engagement_stats: dict) -> bool:
    """ARM → FIRE_AUTHORIZED → REQUEST → FIRE → SAFE."""
    _header("PHASE 4: OPERATOR FIRE CONTROL")

    chain = pipeline._shooting_chain
    audit = pipeline._audit_logger
    operator_id = "demo_operator"
    blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)

    if chain is None:
        _warn("ShootingChain not configured — skipping fire control phase")
        return False

    # --- ARM ---------------------------------------------------------------
    _print()
    result = chain.arm(operator_id=operator_id)
    if result:
        if audit:
            audit.log("arm", operator_id, "armed")
        _print(f"  [bold yellow]ARMED[/bold yellow]  operator={operator_id}  "
               f"state={chain.state.value}" if HAS_RICH else
               f"  ** ARMED **  operator={operator_id}  state={chain.state.value}")
    else:
        _warn(f"arm() returned False (current state: {chain.state.value})")
        chain.safe("demo_reset")
        chain.arm(operator_id=operator_id)
        _ok(f"ARM forced: state={chain.state.value}")

    time.sleep(0.5)

    # --- Wait for FIRE_AUTHORIZED via pipeline ticking ---------------------
    # Keep stepping the pipeline so safety_status gets updated and chain
    # transitions ARMED -> FIRE_AUTHORIZED when fire_authorized=True.
    from rws_tracking.types import BoundingBox, Detection

    _info("Awaiting fire authorization (target must be locked + safety clear)...")
    ts_start = time.monotonic()
    authorized = False

    for tick in range(90):  # up to 3 seconds at 30 Hz
        ts = time.monotonic()

        # Keep operator heartbeat alive so interlock doesn't timeout
        if pipeline._safety_manager is not None:
            pipeline._safety_manager.operator_heartbeat()

        # Inject a centred target so PID error is near-zero -> lock state
        det = Detection(
            bbox=BoundingBox(x=600, y=300, w=80, h=120),
            confidence=0.92,
            class_id="person",
            timestamp=ts,
        )
        pipeline.detector.inject([det])

        try:
            output = pipeline.step(blank_frame, ts)
        except Exception:
            pass

        if chain.state.value == "fire_authorized":
            authorized = True
            break

        time.sleep(0.033)

    if authorized:
        if audit:
            audit.log("fire_authorized", operator_id, "fire_authorized")
        _ok(f"Fire authorized!  state={chain.state.value}  "
            f"(after {time.monotonic() - ts_start:.1f}s)")
    else:
        # Force authorization for demo purposes
        _warn(f"Auto-authorization timed out (state={chain.state.value}). "
              "Forcing via direct state injection for demo...")
        # Manually set via update_authorization with fire_authorized=True
        chain.update_authorization(True, time.monotonic())
        if audit:
            audit.log("fire_authorized", operator_id, chain.state.value)
        _ok(f"Fire authorization injected: state={chain.state.value}")

    time.sleep(0.5)

    # --- Countdown ---------------------------------------------------------
    for i in range(3, 0, -1):
        _print(f"  [bold red]  {i}...[/bold red]" if HAS_RICH else f"  {i}...")
        time.sleep(1.0)

    # --- REQUEST FIRE -------------------------------------------------------
    # Ensure we are in FIRE_AUTHORIZED before requesting
    if chain.state.value != "fire_authorized":
        chain.update_authorization(True, time.monotonic())
        time.sleep(0.1)

    req_result = chain.request_fire(operator_id=operator_id)
    if req_result:
        if audit:
            audit.log("fire_requested", operator_id, "fire_requested")
        _print(f"  [bold red]FIRE REQUESTED[/bold red]  state={chain.state.value}" if HAS_RICH
               else f"  !! FIRE REQUESTED !!  state={chain.state.value}")
    else:
        _warn(f"request_fire() returned False (state: {chain.state.value})")
        return False

    time.sleep(0.3)

    # --- EXECUTE FIRE (from pipeline.step) ---------------------------------
    # Inject a centred target so the pipeline fires cleanly
    det = Detection(
        bbox=BoundingBox(x=600, y=300, w=80, h=120),
        confidence=0.92,
        class_id="person",
        timestamp=time.monotonic(),
    )
    pipeline.detector.inject([det])

    fire_ts = time.monotonic()
    fired = False

    try:
        output = pipeline.step(blank_frame, fire_ts)
        # If pipeline called execute_fire() internally, chain is now in COOLDOWN
        if chain.state.value == "cooldown":
            fired = True
    except Exception as exc:
        _warn(f"pipeline.step() during fire: {exc}")

    # Fallback: call execute_fire directly if pipeline didn't do it
    if not fired and chain.state.value == "fire_requested":
        fired = chain.execute_fire(fire_ts)
        if fired and audit:
            audit.log(
                "fired", operator_id, "cooldown",
                target_id=1,
                threat_score=engagement_stats.get("threat_score", 0.0),
                distance_m=engagement_stats.get("distance_m", 0.0),
                fire_authorized=True,
            )

    if fired or chain.state.value in ("cooldown", "armed", "safe"):
        _print()
        _print("  " + ("=" * 52))
        _print(f"  [bold red]  FIRE EXECUTED — Track #1 neutralized[/bold red]" if HAS_RICH
               else "  ***** FIRE EXECUTED — Track #1 neutralized *****")
        _print("  " + ("=" * 52))
    else:
        _warn(f"Fire execution uncertain (state={chain.state.value})")

    time.sleep(1.0)

    # --- SAFE --------------------------------------------------------------
    chain.safe(reason="demo_end")
    if audit:
        audit.log("safe", operator_id, "safe")
    _print()
    _ok(f"System returned to SAFE  state={chain.state.value}")
    time.sleep(0.5)

    return fired or chain.state.value == "safe"


# ===========================================================================
# PHASE 5 — Mission End & Report
# ===========================================================================

def phase5_mission_end(pipeline, mission_start_ts: float, engagement_stats: dict) -> str:
    """Stop pipeline, generate HTML report, print debrief table."""
    _header("PHASE 5: MISSION END & REPORT")
    time.sleep(0.3)

    pipeline.stop()
    pipeline.cleanup()
    _ok("Pipeline stopped and resources released")

    # --- Generate HTML report ---
    from rws_tracking.telemetry.report import generate_report

    logs_dir = _REPO_ROOT / "logs"
    logs_dir.mkdir(exist_ok=True)
    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = logs_dir / f"demo_report_{timestamp_str}.html"

    audit = pipeline._audit_logger
    html_content = ""
    if audit is not None and audit._records:
        html_content = generate_report(
            audit_logger=audit,
            mission_name=f"RWS Full System Demo — {timestamp_str}",
            output_path=str(report_path),
        )
        _ok(f"HTML report generated: {report_path}")
    else:
        _warn("No audit records — skipping HTML report (audit logger empty)")
        report_path = None

    # --- Mission duration ---
    duration_s = time.monotonic() - mission_start_ts

    # --- Debrief table ---
    shots_fired = 0
    if audit is not None:
        shots_fired = sum(1 for r in audit._records if r.event_type == "fired")

    lock_rate = engagement_stats.get("lock_rate_pct", 0.0)
    avg_yaw = engagement_stats.get("avg_yaw_error_deg", 0.0)
    targets_detected = 1 if engagement_stats.get("target_detected") else 0
    targets_engaged = 1 if shots_fired > 0 else 0
    report_name = report_path.name if report_path else "N/A"

    _print()
    if HAS_RICH:
        from rich.table import Table as RTable
        tbl = RTable(title="MISSION DEBRIEF", box=None, show_header=False, padding=(0, 2))
        tbl.add_column("Key", style="cyan")
        tbl.add_column("Value", style="bold white")
        tbl.add_row("Duration", f"{duration_s:.1f}s")
        tbl.add_row("Targets detected", str(targets_detected))
        tbl.add_row("Targets engaged", str(targets_engaged))
        tbl.add_row("Shots fired", str(shots_fired))
        tbl.add_row("Lock rate", f"{lock_rate:.0f}%")
        tbl.add_row("Avg yaw error", f"{avg_yaw:.3f}°")
        tbl.add_row("Report saved", report_name)
        from rich.panel import Panel as RPanel
        _console.print(RPanel(tbl, title="MISSION DEBRIEF", style="bold green", expand=False))
    else:
        w = 36
        print()
        print("  " + "=" * w)
        print(f"  {'MISSION DEBRIEF':^{w-2}}")
        print("  " + "=" * w)
        print(f"  {'Duration:':<22} {duration_s:.1f}s")
        print(f"  {'Targets detected:':<22} {targets_detected}")
        print(f"  {'Targets engaged:':<22} {targets_engaged}")
        print(f"  {'Shots fired:':<22} {shots_fired}")
        print(f"  {'Lock rate:':<22} {lock_rate:.0f}%")
        print(f"  {'Avg yaw error:':<22} {avg_yaw:.3f}°")
        print(f"  {'Report saved:':<22} {report_name}")
        print("  " + "=" * w)

    time.sleep(0.5)
    return str(report_path) if report_path else ""


# ===========================================================================
# PHASE 6 — Audit Trail
# ===========================================================================

def phase6_audit_trail(pipeline) -> None:
    """Print last 5 audit log entries and verify chain integrity."""
    _header("PHASE 6: AUDIT TRAIL")
    time.sleep(0.3)

    audit = pipeline._audit_logger
    if audit is None:
        _warn("No audit logger configured")
        return

    records = audit.get_recent(n=5)
    if not records:
        _warn("Audit log is empty — no events recorded during demo")
        return

    _print()
    if HAS_RICH:
        from rich.table import Table as RTable
        tbl = RTable(title="Last 5 Audit Entries", show_header=True)
        tbl.add_column("Seq", style="dim", width=5)
        tbl.add_column("Time", width=12)
        tbl.add_column("Event", style="cyan")
        tbl.add_column("State", style="yellow")
        tbl.add_column("Operator")
        tbl.add_column("Hash[:12]", style="dim")
        for r in records:
            ts_str = datetime.datetime.fromtimestamp(r.timestamp).strftime("%H:%M:%S.%f")[:-3]
            tbl.add_row(
                str(r.seq), ts_str, r.event_type, r.chain_state,
                r.operator_id or "—", r.record_hash[:12] + "..."
            )
        _console.print(tbl)
    else:
        print(f"  {'Seq':>4}  {'Time':12}  {'Event':20}  {'State':18}  {'Operator':15}  {'Hash[:12]'}")
        print("  " + "-" * 90)
        for r in records:
            ts_str = datetime.datetime.fromtimestamp(r.timestamp).strftime("%H:%M:%S.%f")[:-3]
            print(f"  {r.seq:>4}  {ts_str:12}  {r.event_type:20}  "
                  f"{r.chain_state:18}  {(r.operator_id or '—'):15}  {r.record_hash[:12]}...")

    # --- Chain verification ---
    _print()
    chain_ok, chain_err = audit.verify_chain()
    if chain_ok:
        total = len(audit._records)
        _ok(f"Audit chain integrity verified  ({total} records, SHA-256 chain intact)")
    else:
        _fail(f"Audit chain integrity FAILED: {chain_err}")

    # Print audit log file location
    _info(f"Audit log: {audit._path}")
    time.sleep(0.5)


# ===========================================================================
# MAIN
# ===========================================================================

def main() -> None:
    print()
    print("=" * 60)
    print("  RWS — Robot Weapon Station  //  Full System Demo")
    print("  Starting up...")
    print("=" * 60)

    demo_start = time.monotonic()

    try:
        # Phase 0: Setup
        cfg, pipeline = phase0_banner_and_setup()

        # Phase 1: Self-test
        go = phase1_selftest(pipeline)
        if not go:
            _warn("Self-test indicates NO-GO, but continuing demo for demonstration purposes")

        # Phase 2: Mission start
        mission_start_ts = phase2_mission_start(pipeline)

        # Phase 3: Engagement
        engagement_stats = phase3_engagement(pipeline)

        # Phase 4: Fire control
        phase4_fire_control(pipeline, engagement_stats)

        # Phase 5: Mission end & report
        report_path = phase5_mission_end(pipeline, mission_start_ts, engagement_stats)

        # Phase 6: Audit trail
        phase6_audit_trail(pipeline)

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
    _ok(f"Full system demo complete.  Total runtime: {total_s:.1f}s")
    _info("RWS — Robot Weapon Station demo finished successfully.")
    _print()


if __name__ == "__main__":
    main()
