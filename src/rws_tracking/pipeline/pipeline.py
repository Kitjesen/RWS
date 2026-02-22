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
import signal
from dataclasses import dataclass, field
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
from ..telemetry.interfaces import TelemetryLogger
from .protocols import FrameAnnotatorProtocol, FrameBufferProtocol
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

        self._last_target_id: int | None = None
        self._stop_flag = False
        self._signal_handlers_installed = False
        self._lock_start_ts: float | None = None
        self._last_track_state: str = TrackState.SEARCH.value

        # Distance cache: track_id -> last fused distance_m.
        # Populated from distance_fusion results and passed to ThreatAssessor
        # so all downstream modules share the same distance measurement.
        self._distance_cache: dict[int, float] = {}

        # Engagement dwell tracking: how long the current target has been
        # continuously LOCK + fire_authorized.
        self._engagement_dwell_time_s = engagement_dwell_time_s
        self._engagement_dwell_id: int | None = None
        self._engagement_dwell_start: float | None = None

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

        threat_assessments: list[ThreatAssessment] = []
        if self._threat_assessor is not None and tracks:
            # Pass cached fused distances so ThreatAssessor uses laser measurements
            # instead of its own bbox-only estimate.
            threat_assessments = self._threat_assessor.assess(
                tracks, distance_map=self._distance_cache or None
            )
            if self._engagement_queue is not None:
                self._engagement_queue.update(threat_assessments)

        # =====================================================================
        # 3. 目标选择
        # =====================================================================
        selected = self.selector.select(tracks, timestamp)

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
        # 7b. 交战队列自动推进 (可选)
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
        # 8. 控制指令计算 (PID + 弹道 + 提前量)
        # =====================================================================
        body_state = (
            self._body_provider.get_body_state(timestamp)
            if self._body_provider is not None
            else None
        )

        command = self.controller.compute_command(
            selected, feedback, timestamp, body_state=body_state,
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

        # 叠加提前量到控制指令 (在 PID 输出之后附加)
        if lead_angle is not None and lead_angle.confidence > 0:
            command = ControlCommand(
                timestamp=command.timestamp,
                yaw_rate_cmd_dps=command.yaw_rate_cmd_dps + lead_angle.yaw_lead_deg * 2.0,
                pitch_rate_cmd_dps=command.pitch_rate_cmd_dps + lead_angle.pitch_lead_deg * 2.0,
                metadata={
                    **command.metadata,
                    "lead_yaw_deg": lead_angle.yaw_lead_deg,
                    "lead_pitch_deg": lead_angle.pitch_lead_deg,
                    "lead_confidence": lead_angle.confidence,
                },
            )

        # 叠加风偏补偿 (弹道解算的 yaw 方向补偿)
        if ballistic_solution is not None and ballistic_solution.windage_deg != 0:
            command = ControlCommand(
                timestamp=command.timestamp,
                yaw_rate_cmd_dps=command.yaw_rate_cmd_dps + ballistic_solution.windage_deg * 2.0,
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
        self.telemetry.log(
            "control",
            timestamp,
            {
                "yaw_cmd_dps": command.yaw_rate_cmd_dps,
                "pitch_cmd_dps": command.pitch_rate_cmd_dps,
                "yaw_error_deg": command.metadata.get("yaw_error_deg", 0.0),
                "pitch_error_deg": command.metadata.get("pitch_error_deg", 0.0),
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
        if self._frame_buffer is not None and frame is not None:
            import numpy as np

            if isinstance(frame, np.ndarray):
                annotated = frame
                if self._frame_annotator is not None:
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
                self._frame_buffer.push(annotated, timestamp)

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
