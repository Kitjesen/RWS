"""End-to-end orchestration pipeline.

完整射击链路:
    detect/track → 威胁评估 → 目标选择 → 距离融合
    → 弹道解算 → 提前量 → 安全检查 → PID 控制
    → 轨迹规划 → 驱动 → 视频推帧

所有扩展模块（弹道/提前量/安全/测距/视频流等）均为可选注入,
默认 None = 不启用, 行为与旧版完全一致 (零回归)。
"""

from __future__ import annotations

import logging
import math
import signal
from dataclasses import dataclass, field, replace
from typing import Protocol

from ..control.interfaces import (
    BallisticSolverProtocol,
    DistanceFusionProtocol,
    GimbalController,
    LeadCalculatorProtocol,
    TrajectoryPlannerProtocol,
)
from ..decision.interfaces import EngagementQueueProtocol, ThreatAssessorProtocol
from ..hardware.imu_interface import BodyMotionProvider
from ..hardware.interfaces import GimbalDriver
from ..hardware.rangefinder import RangefinderProvider
from ..perception.interfaces import Detector, TargetSelector, Tracker
from ..safety.interfaces import SafetyEvaluatorProtocol
from ..safety.iff import IFFChecker
from ..decision.lifecycle import TargetLifecycleManager
from ..health.monitor import HealthMonitor
from ..safety.shooting_chain import ShootingChain
from ..telemetry.audit import AuditLogger
from ..telemetry.interfaces import TelemetryLogger
from ..telemetry.video_ring_buffer import VideoRingBuffer
from .protocols import FrameAnnotatorProtocol, FrameBufferProtocol

# Optional SSE event bus — imported lazily to avoid circular imports at module
# load time.  If the events module is not available, we silently skip emission.
try:
    from ..api.events import event_bus as _event_bus
except Exception:  # pragma: no cover
    _event_bus = None  # type: ignore[assignment]
from ..types import (
    BallisticSolution,
    ControlCommand,
    LeadAngle,
    SafetyStatus,
    TargetObservation,
    ThreatAssessment,
    Track,
    TrackState,
)

logger = logging.getLogger(__name__)


class CombinedTracker(Protocol):
    """Protocol for combined detector+tracker (e.g. YoloSegTracker)."""

    def detect_and_track(self, frame: object, timestamp: float) -> list[Track]: ...


@dataclass
class PipelineOutputs:
    """单帧 pipeline 输出，包含完整射击链路状态。"""

    selected_target: TargetObservation | None
    command: ControlCommand
    tracks: list[Track] = field(default_factory=list)
    detections: list = field(default_factory=list)
    threat_assessments: list[ThreatAssessment] = field(default_factory=list)
    ballistic_solution: BallisticSolution | None = None
    lead_angle: LeadAngle | None = None
    safety_status: SafetyStatus | None = None
    distance_m: float = 0.0


class VisionGimbalPipeline:
    """完整射击链路 pipeline。

    支持两种检测模式:
    1. **Two-step** (legacy): 分离的 ``detector`` + ``tracker``。
    2. **Combined** (new): 单一 ``combined_tracker`` 直接输出 tracks。

    可选注入的扩展组件（全部默认 None = 不启用，零回归）:
    - ``body_provider`` : 运动基座补偿
    - ``threat_assessor`` : 威胁评估
    - ``engagement_queue`` : 交战排序
    - ``distance_fusion`` : 距离融合（激光 + bbox）
    - ``rangefinder`` : 激光测距仪
    - ``ballistic_solver`` : 物理弹道解算
    - ``lead_calculator`` : 射击提前量
    - ``safety_manager`` : 安全系统
    - ``trajectory_planner`` : 轨迹规划
    - ``frame_buffer`` : 视频帧缓冲
    - ``frame_annotator`` : 帧标注
    - ``video_ring_buffer`` : 环形缓冲区（火控事件录像）
    """

    def __init__(
        self,
        detector: Detector,
        tracker: Tracker,
        selector: TargetSelector,
        controller: GimbalController,
        driver: GimbalDriver,
        telemetry: TelemetryLogger,
        combined_tracker: CombinedTracker | None = None,
        body_provider: BodyMotionProvider | None = None,
        # ---- v1.1 扩展组件（全部 Protocol 约束，默认 None = 不启用）----
        threat_assessor: ThreatAssessorProtocol | None = None,
        engagement_queue: EngagementQueueProtocol | None = None,
        distance_fusion: DistanceFusionProtocol | None = None,
        rangefinder: RangefinderProvider | None = None,
        ballistic_solver: BallisticSolverProtocol | None = None,
        lead_calculator: LeadCalculatorProtocol | None = None,
        safety_manager: SafetyEvaluatorProtocol | None = None,
        trajectory_planner: TrajectoryPlannerProtocol | None = None,
        frame_buffer: FrameBufferProtocol | None = None,
        frame_annotator: FrameAnnotatorProtocol | None = None,
        shooting_chain: ShootingChain | None = None,
        audit_logger: AuditLogger | None = None,
        health_monitor: HealthMonitor | None = None,
        lifecycle_manager: TargetLifecycleManager | None = None,
        iff_checker: IFFChecker | None = None,
        video_ring_buffer: VideoRingBuffer | None = None,
        # Minimum time (s) a target must be continuously LOCK+fire_authorized
        # before the engagement queue auto-advances to the next target.
        # Set to 0.0 to disable auto-advance.
        engagement_dwell_time_s: float = 2.0,
    ) -> None:
        self.detector = detector
        self.tracker = tracker
        self.selector = selector
        self.controller = controller
        self.driver = driver
        self.telemetry = telemetry
        self._combined_tracker = combined_tracker
        self._body_provider = body_provider

        # 扩展组件
        self._threat_assessor = threat_assessor
        self._engagement_queue = engagement_queue
        self._distance_fusion = distance_fusion
        self._rangefinder = rangefinder
        self._ballistic_solver = ballistic_solver
        self._lead_calculator = lead_calculator
        self._safety_manager = safety_manager
        self._trajectory_planner = trajectory_planner
        self._frame_buffer = frame_buffer
        self._frame_annotator = frame_annotator
        self._shooting_chain = shooting_chain
        self._audit_logger = audit_logger
        self._health_monitor = health_monitor
        self._lifecycle_manager = lifecycle_manager
        self._iff_checker = iff_checker
        self._video_ring_buffer = video_ring_buffer
        # ROE manager — injected by build_pipeline_from_config(); may also be
        # set directly on the pipeline instance after construction.
        self._roe_manager = None  # type: ignore[assignment]

        self._last_target_id: int | None = None
        self._last_chain_state: str = ""
        self._stop_flag = False
        # Operator-designated target — overrides auto-selection when set.
        self._designated_track_id: int | None = None
        self._designated_by: str = ""  # operator_id who made the designation
        self._signal_handlers_installed = False
        self._lock_start_ts: float | None = None
        self._last_track_state: str = TrackState.SEARCH.value
        # Most-recent gimbal error (updated each step; read by API status endpoint)
        self._last_yaw_error_deg: float = 0.0
        self._last_pitch_error_deg: float = 0.0

        # Distance cache: track_id -> last fused distance_m.
        # Populated from distance_fusion results and passed to ThreatAssessor
        # so all downstream modules share the same distance measurement.
        self._distance_cache: dict[int, float] = {}

        # Engagement dwell tracking: how long the current target has been
        # continuously LOCK + fire_authorized.
        self._engagement_dwell_time_s = engagement_dwell_time_s
        self._engagement_dwell_id: int | None = None
        self._engagement_dwell_start: float | None = None

        # SSE state-change tracking — used to detect transitions and emit events.
        self._last_threat_track_ids: set[int] = set()
        self._last_fire_authorized: bool | None = None
        self._last_health_statuses: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Target designation (operator C2 override)
    # ------------------------------------------------------------------

    def designate_target(self, track_id: int, operator_id: str = "") -> None:
        """Operator-designate a specific track as the engagement target.

        Overrides auto-selection until the track disappears or is cleared.
        """
        self._designated_track_id = track_id
        self._designated_by = operator_id
        logger.info("designation: track %d designated by '%s'", track_id, operator_id)

    def clear_designation(self) -> None:
        """Remove operator designation, returning to auto-selection."""
        old = self._designated_track_id
        self._designated_track_id = None
        self._designated_by = ""
        if old is not None:
            logger.info("designation: cleared (was track %d)", old)

    @property
    def designated_track_id(self) -> int | None:
        return self._designated_track_id

    @property
    def dwell_status(self) -> dict:
        """Return current engagement dwell timer state (for API consumption).

        Uses time.monotonic() to compute elapsed seconds since dwell began.
        Returns a dict with keys: active, track_id, elapsed_s, total_s, fraction.
        """
        import time as _time

        total = self._engagement_dwell_time_s
        if self._engagement_dwell_start is None or self._engagement_dwell_id is None:
            return {
                "active": False,
                "track_id": None,
                "elapsed_s": 0.0,
                "total_s": total,
                "fraction": 0.0,
            }
        elapsed = _time.monotonic() - self._engagement_dwell_start
        fraction = min(elapsed / total, 1.0) if total > 0 else 0.0
        return {
            "active": True,
            "track_id": self._engagement_dwell_id,
            "elapsed_s": round(elapsed, 2),
            "total_s": total,
            "fraction": round(fraction, 3),
        }

    def install_signal_handlers(self) -> None:
        """安装 SIGINT/SIGTERM 信号处理器，支持优雅退出"""
        if self._signal_handlers_installed:
            return

        def handler(signum, frame):
            print(f"\n[RWS] Received signal {signum}, stopping gracefully...")
            self._stop_flag = True

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)
        self._signal_handlers_installed = True

    def should_stop(self) -> bool:
        return self._stop_flag

    def stop(self) -> None:
        self._stop_flag = True

    def cleanup(self) -> None:
        if hasattr(self.telemetry, "close"):
            self.telemetry.close()

    def step(self, frame: object, timestamp: float) -> PipelineOutputs:
        """执行完整射击链路的单帧处理。

        数据流:
            detect/track → 威胁评估 → 选择 → 距离融合
            → 弹道解算 → 提前量 → 安全检查 → PID → 驱动 → 推帧
        """
        # =====================================================================
        # 1. 感知: 检测 + 跟踪
        # =====================================================================
        if self._combined_tracker is not None:
            tracks = self._combined_tracker.detect_and_track(frame, timestamp)
        else:
            detections = self.detector.detect(frame, timestamp)
            tracks = self.tracker.update(detections, timestamp)

        # =====================================================================
        # 2. 威胁评估 (可选)
        # =====================================================================
        # Evict stale cache entries for tracks that disappeared this frame.
        live_ids = {t.track_id for t in tracks}
        self._distance_cache = {k: v for k, v in self._distance_cache.items()
                                if k in live_ids}

        # Filter out already-neutralized/archived targets before assessment.
        assessable_tracks = (
            self._lifecycle_manager.filter_active(tracks)
            if self._lifecycle_manager is not None
            else tracks
        )

        threat_assessments: list[ThreatAssessment] = []
        if self._threat_assessor is not None and assessable_tracks:
            # Pass cached fused distances so ThreatAssessor uses laser measurements
            # instead of its own bbox-only estimate.
            threat_assessments = self._threat_assessor.assess(
                assessable_tracks, distance_map=self._distance_cache or None
            )
            if self._engagement_queue is not None:
                self._engagement_queue.update(threat_assessments)

        # Update lifecycle state for all current tracks.
        if self._lifecycle_manager is not None:
            self._lifecycle_manager.update(tracks, threat_assessments, timestamp)

        # SSE: emit threat_detected for tracks newly entering the high-priority list.
        if _event_bus is not None:
            current_high_ids = {ta.track_id for ta in threat_assessments
                                if ta.threat_score >= 0.3}
            new_threat_ids = current_high_ids - self._last_threat_track_ids
            for ta in threat_assessments:
                if ta.track_id in new_threat_ids:
                    _event_bus.emit("threat_detected", {
                        "track_id": ta.track_id,
                        "threat_score": round(ta.threat_score, 4),
                        "priority_rank": ta.priority_rank,
                        "ts": round(timestamp, 3),
                    })
            self._last_threat_track_ids = current_high_ids

        # =====================================================================
        # 3. 目标选择
        # =====================================================================
        selected = self.selector.select(tracks, timestamp)

        # 3b. Operator designation override — if an operator has manually
        #     designated a specific track, use it instead of auto-selection,
        #     provided that track is currently visible and not neutralised.
        if self._designated_track_id is not None:
            designated = next(
                (t for t in assessable_tracks if t.track_id == self._designated_track_id),
                None,
            )
            if designated is not None:
                selected = TargetObservation(
                    track_id=designated.track_id,
                    bbox=designated.bbox,
                    class_id=designated.class_id,
                    confidence=designated.confidence,
                    timestamp=timestamp,
                )
            else:
                # Designated track no longer visible — clear designation.
                logger.info(
                    "designation: track %d no longer visible, clearing designation",
                    self._designated_track_id,
                )
                self._designated_track_id = None
                self._designated_by = ""

        # =====================================================================
        # 4. 距离融合 (可选): 激光优先, bbox 兜底
        # =====================================================================
        distance_m = 0.0
        laser_reading = None

        if self._rangefinder is not None and selected is not None:
            self._rangefinder.set_target_bbox(selected.bbox)
            laser_reading = self._rangefinder.measure(timestamp)

        if self._distance_fusion is not None and selected is not None:
            distance_m = self._distance_fusion.fuse(
                laser_reading, selected.bbox, timestamp
            )
            # Update cache so ThreatAssessor can use it next frame.
            if distance_m > 0:
                self._distance_cache[selected.track_id] = distance_m

        # =====================================================================
        # 5. 弹道解算 (可选): 飞行时间 + 下坠 + 风偏
        # =====================================================================
        ballistic_solution: BallisticSolution | None = None
        if self._ballistic_solver is not None and distance_m > 0:
            ballistic_solution = self._ballistic_solver.solve(distance_m)

        # =====================================================================
        # 6. 射击提前量 (可选): 融合目标运动 + 飞行时间
        # =====================================================================
        lead_angle: LeadAngle | None = None
        if self._lead_calculator is not None and selected is not None:
            lead_angle = self._lead_calculator.compute(selected)

        # =====================================================================
        # 7. 安全检查 (可选): NFZ + 联锁
        # =====================================================================
        safety_status: SafetyStatus | None = None
        feedback = self.driver.get_feedback(timestamp)

        if self._safety_manager is not None:
            is_locked = self._last_track_state == TrackState.LOCK.value
            lock_duration = 0.0
            if is_locked:
                if self._lock_start_ts is None:
                    self._lock_start_ts = timestamp
                lock_duration = timestamp - self._lock_start_ts
            else:
                self._lock_start_ts = None

            safety_status = self._safety_manager.evaluate(
                yaw_deg=feedback.yaw_deg,
                pitch_deg=feedback.pitch_deg,
                target_locked=is_locked,
                lock_duration_s=lock_duration,
                target_distance_m=distance_m,
            )

        # =====================================================================
        # 7b. IFF check (optional): block fire if selected target is friendly
        # =====================================================================
        if (
            self._iff_checker is not None
            and safety_status is not None
            and selected is not None
        ):
            iff_results = self._iff_checker.check(tracks)
            iff_result = iff_results.get(selected.track_id)
            if iff_result is not None and iff_result.is_friend:
                logger.warning(
                    "IFF: target %d identified as FRIEND (%s) — fire blocked",
                    selected.track_id,
                    iff_result.reason,
                )
                safety_status = SafetyStatus(
                    fire_authorized=False,
                    blocked_reason=f"IFF:{iff_result.reason}",
                    active_zone=safety_status.active_zone,
                    operator_override=safety_status.operator_override,
                    emergency_stop=safety_status.emergency_stop,
                )

        # SSE: emit safety_triggered on the first frame fire transitions to blocked.
        if _event_bus is not None and safety_status is not None:
            if not safety_status.fire_authorized and self._last_fire_authorized is not False:
                _event_bus.emit("safety_triggered", {
                    "reason": safety_status.blocked_reason or "interlock",
                    "yaw_deg": round(feedback.yaw_deg, 2),
                    "pitch_deg": round(feedback.pitch_deg, 2),
                    "ts": round(timestamp, 3),
                })
            self._last_fire_authorized = safety_status.fire_authorized

        # =====================================================================
        # 7c. 交战队列自动推进 (可选)
        #
        # 触发条件: 当前目标持续 LOCK + fire_authorized >= engagement_dwell_time_s
        # 意义: 系统确认已对该目标充分瞄准，自动切换到下一优先目标。
        # =====================================================================
        if (
            self._engagement_queue is not None
            and self._engagement_dwell_time_s > 0.0
            and selected is not None
            and self._last_track_state == TrackState.LOCK.value
            and safety_status is not None
            and safety_status.fire_authorized
        ):
            cur_id = selected.track_id
            if cur_id != self._engagement_dwell_id:
                # New target entered fire-authorized lock — start dwell timer.
                self._engagement_dwell_id = cur_id
                self._engagement_dwell_start = timestamp
            elif (
                self._engagement_dwell_start is not None
                and timestamp - self._engagement_dwell_start >= self._engagement_dwell_time_s
            ):
                next_id = self._engagement_queue.advance()
                logger.info(
                    "engagement auto-advance: target %d dwelled %.1fs -> next %s",
                    cur_id,
                    timestamp - self._engagement_dwell_start,
                    next_id,
                )
                self.telemetry.log(
                    "engagement_advance",
                    timestamp,
                    {
                        "completed_id": float(cur_id),
                        "next_id": float(next_id) if next_id is not None else -1.0,
                        "dwell_s": timestamp - self._engagement_dwell_start,
                    },
                )
                self._engagement_dwell_id = None
                self._engagement_dwell_start = None
        else:
            # Reset dwell timer whenever conditions break (target lost, unlock, NFZ block).
            if self._engagement_dwell_id is not None:
                self._engagement_dwell_id = None
                self._engagement_dwell_start = None

        # =====================================================================
        # 7c. ShootingChain update (optional)
        # =====================================================================
        if self._shooting_chain is not None:
            fire_auth = safety_status.fire_authorized if safety_status else False
            self._shooting_chain.update_authorization(fire_auth, timestamp)
            self._shooting_chain.tick(timestamp)

            new_state = self._shooting_chain.state.value
            if new_state != self._last_chain_state:
                if self._audit_logger is not None:
                    self._audit_logger.log(
                        event_type=f"state_{new_state}",
                        operator_id=self._shooting_chain.operator_id or "system",
                        chain_state=new_state,
                        target_id=selected.track_id if selected else None,
                        threat_score=(threat_assessments[0].threat_score
                                      if threat_assessments else 0.0),
                        distance_m=distance_m,
                        fire_authorized=fire_auth,
                        blocked_reason=(safety_status.blocked_reason
                                        if safety_status and not fire_auth else ""),
                    )
                # Push SSE event for real-time operator notification.
                if _event_bus is not None:
                    _event_bus.emit("fire_chain_state", {
                        "state": new_state,
                        "prev_state": self._last_chain_state,
                        "target_id": selected.track_id if selected else None,
                        "fire_authorized": fire_auth,
                        "ts": round(timestamp, 3),
                    })
                self._last_chain_state = new_state

            # ROE gate: if the active profile has fire_enabled=False (e.g.
            # training mode), suppress the actual fire command even when the
            # shooting chain reports can_fire=True.
            _roe_permits_fire = (
                self._roe_manager is None
                or self._roe_manager.is_fire_enabled()
            )
            if not _roe_permits_fire and self._shooting_chain.can_fire:
                logger.info(
                    "fire suppressed: ROE profile=%s (fire_enabled=False)",
                    self._roe_manager.active.name if self._roe_manager else "unknown",
                )

            if self._shooting_chain.can_fire and _roe_permits_fire:
                fired = self._shooting_chain.execute_fire(timestamp)
                if fired:
                    logger.warning(
                        "FIRE EXECUTED: target=%s ts=%.3f",
                        selected.track_id if selected else None,
                        timestamp,
                    )
                    if self._audit_logger is not None:
                        self._audit_logger.log(
                            event_type="fired",
                            operator_id=self._shooting_chain.operator_id or "system",
                            chain_state="fired",
                            target_id=selected.track_id if selected else None,
                            threat_score=(threat_assessments[0].threat_score
                                          if threat_assessments else 0.0),
                            distance_m=distance_m,
                            fire_authorized=True,
                        )
                    # SSE: notify operator of fire execution.
                    if _event_bus is not None:
                        _event_bus.emit("fire_executed", {
                            "target_id": selected.track_id if selected else None,
                            "threat_score": round(
                                threat_assessments[0].threat_score
                                if threat_assessments else 0.0, 4),
                            "distance_m": round(distance_m, 1),
                            "ts": round(timestamp, 3),
                        })
                    if (self._lifecycle_manager is not None
                            and selected is not None):
                        self._lifecycle_manager.mark_neutralized(
                            selected.track_id, timestamp
                        )
                        if _event_bus is not None:
                            _event_bus.emit("target_neutralized", {
                                "track_id": selected.track_id,
                                "threat_score": round(
                                    threat_assessments[0].threat_score
                                    if threat_assessments else 0.0, 4),
                                "ts": round(timestamp, 3),
                            })
                    if self._video_ring_buffer is not None:
                        track_id_for_clip = (
                            selected.track_id if selected is not None else None
                        )
                        self._video_ring_buffer.save_clip(
                            timestamp, "fire", track_id_for_clip
                        )

        # HealthMonitor: report pipeline heartbeat each frame.
        if self._health_monitor is not None:
            self._health_monitor.heartbeat("pipeline", timestamp)
            # SSE: emit health_degraded when a subsystem transitions to degraded/failed.
            if _event_bus is not None:
                try:
                    for name, info in self._health_monitor.get_status().items():
                        status_str = (
                            info.get("status", "unknown")
                            if isinstance(info, dict)
                            else info.compute_status()
                        )
                        prev = self._last_health_statuses.get(name, "ok")
                        if status_str in ("degraded", "failed") and status_str != prev:
                            _event_bus.emit("health_degraded", {
                                "subsystem": name,
                                "status": status_str,
                                "ts": round(timestamp, 3),
                            })
                        self._last_health_statuses[name] = status_str
                except Exception:
                    pass

        # =====================================================================
        # 8. 控制指令计算 (PID + 弹道 + 提前量)
        # =====================================================================
        body_state = (
            self._body_provider.get_body_state(timestamp)
            if self._body_provider is not None
            else None
        )

        # --- 提前量位置补偿 (在 PID 之前修正目标坐标) ---
        #
        # 正确做法: 将 lead_angle (°) 转换为像素偏移量，调整 TargetObservation
        # 的 mask_center，使 PID 控制器将云台瞄准弹丸将抵达时的目标预测位置。
        #
        # 旧方案（×2.0 乘以速率）维度有误（°/s ≠ °），已废弃。
        #
        # 转换公式: Δpx = Δangle_deg · fx / (180/π)
        #   其中 fx 来自已配置的相机内参。
        control_target = selected
        if lead_angle is not None and lead_angle.confidence > 0 and selected is not None:
            cam = self.controller._transform.camera
            lead_px_yaw = lead_angle.yaw_lead_deg * cam.fx / math.degrees(1.0)
            lead_px_pitch = lead_angle.pitch_lead_deg * cam.fy / math.degrees(1.0)
            # Pixel convention: right = +x, down = +y; gimbal yaw right = +°, pitch up = -°
            if selected.mask_center is not None:
                mcx, mcy = selected.mask_center
                control_target = replace(
                    selected,
                    mask_center=(mcx + lead_px_yaw, mcy - lead_px_pitch),
                )
            else:
                cx, cy = selected.bbox.center
                control_target = replace(
                    selected,
                    mask_center=(cx + lead_px_yaw, cy - lead_px_pitch),
                )

        fire_auth_for_pid = safety_status.fire_authorized if safety_status is not None else True
        command = self.controller.compute_command(
            control_target, feedback, timestamp,
            body_state=body_state,
            fire_authorized=fire_auth_for_pid,
        )

        state_val = command.metadata.get("state", 0.0)
        if state_val == 2.0:
            self._last_track_state = TrackState.LOCK.value
        elif state_val == 1.0:
            self._last_track_state = TrackState.TRACK.value
        elif state_val == 3.0:
            self._last_track_state = TrackState.LOST.value
        else:
            self._last_track_state = TrackState.SEARCH.value

        # =====================================================================
        # 8b. 轨迹规划器覆盖 (可选)
        #
        # 当检测到目标切换时 (selected.track_id != _last_target_id)，
        # 将新目标的像素中心转换为云台角度目标，并触发梯形轨迹规划。
        # 在轨迹激活期间，以轨迹速率指令覆盖 PID 输出，实现平滑切换。
        #
        # 转换公式: angle_deg = feedback_deg + (px - cx) * degrees(1) / f
        #   其中 f 为相机焦距 (px), cx/cy 为主点坐标。
        # =====================================================================
        if self._trajectory_planner is not None and selected is not None:
            # Detect target switch: _last_target_id still holds the PREVIOUS
            # target ID at this point (updated later in section 11).
            target_switched = (
                selected.track_id != self._last_target_id
                and self._last_target_id is not None
            )
            if target_switched:
                cam = self.controller._transform.camera
                cx, cy = (
                    control_target.mask_center
                    if control_target is not None and control_target.mask_center is not None
                    else control_target.bbox.center
                    if control_target is not None
                    else selected.bbox.center
                )
                # Angular resolution: degrees per pixel
                # math.degrees(1.0) converts 1 radian to degrees;
                # dividing by focal length gives deg/px.
                target_yaw_deg = feedback.yaw_deg + (cx - cam.cx) * math.degrees(1.0) / cam.fx
                target_pitch_deg = feedback.pitch_deg - (cy - cam.cy) * math.degrees(1.0) / cam.fy
                self._trajectory_planner.set_target(
                    target_yaw_deg,
                    target_pitch_deg,
                    feedback.yaw_deg,
                    feedback.pitch_deg,
                    timestamp,
                )

            if self._trajectory_planner.is_active:
                traj_yaw, traj_pitch = self._trajectory_planner.get_rate_command(timestamp)
                command = ControlCommand(
                    timestamp=command.timestamp,
                    yaw_rate_cmd_dps=traj_yaw,
                    pitch_rate_cmd_dps=traj_pitch,
                    metadata={**command.metadata, "trajectory_active": True},
                )

        # 在 metadata 中记录提前量（供遥测使用），不再直接叠加速率
        if lead_angle is not None and lead_angle.confidence > 0:
            command = ControlCommand(
                timestamp=command.timestamp,
                yaw_rate_cmd_dps=command.yaw_rate_cmd_dps,
                pitch_rate_cmd_dps=command.pitch_rate_cmd_dps,
                metadata={
                    **command.metadata,
                    "lead_yaw_deg": lead_angle.yaw_lead_deg,
                    "lead_pitch_deg": lead_angle.pitch_lead_deg,
                    "lead_confidence": lead_angle.confidence,
                },
            )

        # 叠加风偏补偿 (弹道解算的 yaw 方向补偿)
        # 风偏是外部环境因素，仍以速率形式叠加（短时平滑等效于位置偏移）
        if ballistic_solution is not None and ballistic_solution.windage_deg != 0:
            # 用 Kp 增益将角度补偿转化为等效速率 (°/s)
            kp_yaw = self.controller._cfg.yaw_pid.kp
            windage_rate = ballistic_solution.windage_deg * kp_yaw
            command = ControlCommand(
                timestamp=command.timestamp,
                yaw_rate_cmd_dps=command.yaw_rate_cmd_dps + windage_rate,
                pitch_rate_cmd_dps=command.pitch_rate_cmd_dps,
                metadata={
                    **command.metadata,
                    "windage_deg": ballistic_solution.windage_deg,
                    "flight_time_s": ballistic_solution.flight_time_s,
                },
            )

        # =====================================================================
        # 9. 安全限速 (可选): 靠近禁射区时降速
        # =====================================================================
        if self._safety_manager is not None:
            speed_factor = self._safety_manager.get_speed_factor(
                feedback.yaw_deg, feedback.pitch_deg
            )
            if speed_factor < 1.0:
                command = ControlCommand(
                    timestamp=command.timestamp,
                    yaw_rate_cmd_dps=command.yaw_rate_cmd_dps * speed_factor,
                    pitch_rate_cmd_dps=command.pitch_rate_cmd_dps * speed_factor,
                    metadata={**command.metadata, "safety_speed_factor": speed_factor},
                )

        # =====================================================================
        # 10. 驱动执行
        # =====================================================================
        self.driver.set_yaw_pitch_rate(
            command.yaw_rate_cmd_dps, command.pitch_rate_cmd_dps, timestamp,
        )

        # =====================================================================
        # 11. 遥测记录
        # =====================================================================
        self._last_yaw_error_deg = command.metadata.get("yaw_error_deg", 0.0)
        self._last_pitch_error_deg = command.metadata.get("pitch_error_deg", 0.0)
        self.telemetry.log(
            "control",
            timestamp,
            {
                "yaw_cmd_dps": command.yaw_rate_cmd_dps,
                "pitch_cmd_dps": command.pitch_rate_cmd_dps,
                "yaw_error_deg": self._last_yaw_error_deg,
                "pitch_error_deg": self._last_pitch_error_deg,
                "state": command.metadata.get("state", 0.0),
                "ff_yaw_dps": command.metadata.get("ff_yaw_dps", 0.0),
                "ff_pitch_dps": command.metadata.get("ff_pitch_dps", 0.0),
                "distance_m": distance_m,
                "lead_yaw_deg": command.metadata.get("lead_yaw_deg", 0.0),
                "lead_pitch_deg": command.metadata.get("lead_pitch_deg", 0.0),
                "flight_time_s": command.metadata.get("flight_time_s", 0.0),
                "windage_deg": command.metadata.get("windage_deg", 0.0),
                "safety_speed_factor": command.metadata.get("safety_speed_factor", 1.0),
            },
        )

        # 目标切换日志
        if selected is not None and selected.track_id != self._last_target_id:
            self.telemetry.log("switch", timestamp, {"track_id": float(selected.track_id)})
            self._last_target_id = selected.track_id
        if selected is None:
            self._last_target_id = None

        # 威胁评估日志
        if threat_assessments:
            top = threat_assessments[0]
            self.telemetry.log(
                "threat",
                timestamp,
                {
                    "top_threat_id": float(top.track_id),
                    "top_threat_score": top.threat_score,
                    "threat_count": float(len(threat_assessments)),
                },
            )

        # =====================================================================
        # 12. 视频帧推送 (可选)
        # =====================================================================
        if frame is not None:
            import numpy as np

            if isinstance(frame, np.ndarray):
                annotated = frame
                if self._frame_annotator is not None and self._frame_buffer is not None:
                    state_str = str(command.metadata.get("state", ""))
                    status_text = f"D:{distance_m:.0f}m" if distance_m > 0 else ""
                    if safety_status is not None and not safety_status.fire_authorized:
                        status_text += f" BLOCKED:{safety_status.blocked_reason[:30]}"
                    annotated = self._frame_annotator.annotate(
                        frame,
                        tracks=tracks,
                        selected_id=selected.track_id if selected else None,
                        status_text=status_text,
                    )
                if self._frame_buffer is not None:
                    self._frame_buffer.push(annotated, timestamp)
                if self._video_ring_buffer is not None:
                    self._video_ring_buffer.push(frame, timestamp)

        return PipelineOutputs(
            selected_target=selected,
            command=command,
            tracks=tracks,
            threat_assessments=threat_assessments,
            ballistic_solution=ballistic_solution,
            lead_angle=lead_angle,
            safety_status=safety_status,
            distance_m=distance_m,
        )
