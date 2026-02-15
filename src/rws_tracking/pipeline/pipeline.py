"""End-to-end orchestration pipeline."""

from __future__ import annotations

import signal
from dataclasses import dataclass
from typing import Protocol

from ..control.interfaces import GimbalController
from ..hardware.imu_interface import BodyMotionProvider
from ..hardware.interfaces import GimbalDriver
from ..perception.interfaces import Detector, TargetSelector, Tracker
from ..telemetry.interfaces import TelemetryLogger
from ..types import ControlCommand, TargetObservation, Track


class CombinedTracker(Protocol):
    """Protocol for combined detector+tracker (e.g. YoloSegTracker)."""

    def detect_and_track(self, frame: object, timestamp: float) -> list[Track]: ...


@dataclass
class PipelineOutputs:
    selected_target: TargetObservation | None
    command: ControlCommand


class VisionGimbalPipeline:
    """
    Supports two modes:

    1. **Two-step** (legacy): separate ``detector`` + ``tracker``.
    2. **Combined** (new): single ``combined_tracker`` that outputs tracks directly.

    When ``combined_tracker`` is provided, ``detector`` and ``tracker`` are unused.

    Optionally accepts a ``body_provider`` (:class:`BodyMotionProvider`) to
    enable feedforward compensation for a moving base (e.g. robot dog).
    When ``body_provider`` is ``None`` the pipeline behaves identically to the
    legacy stationary-base mode (zero regression).
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
    ) -> None:
        self.detector = detector
        self.tracker = tracker
        self.selector = selector
        self.controller = controller
        self.driver = driver
        self.telemetry = telemetry
        self._combined_tracker = combined_tracker
        self._body_provider = body_provider
        self._last_target_id: int | None = None
        self._stop_flag = False
        self._signal_handlers_installed = False

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
        """检查是否应该停止（用户按 Ctrl+C 或调用 stop()）"""
        return self._stop_flag

    def stop(self) -> None:
        """请求停止 pipeline（设置 stop flag）"""
        self._stop_flag = True

    def cleanup(self) -> None:
        """清理资源（关闭文件日志等）"""
        # 如果 telemetry 是 FileTelemetryLogger，调用 close()
        if hasattr(self.telemetry, "close"):
            self.telemetry.close()

    def step(self, frame: object, timestamp: float) -> PipelineOutputs:
        if self._combined_tracker is not None:
            tracks = self._combined_tracker.detect_and_track(frame, timestamp)
        else:
            detections = self.detector.detect(frame, timestamp)
            tracks = self.tracker.update(detections, timestamp)
        selected = self.selector.select(tracks, timestamp)
        feedback = self.driver.get_feedback(timestamp)

        # Fetch body state for feedforward compensation (None if no provider)
        body_state = (
            self._body_provider.get_body_state(timestamp)
            if self._body_provider is not None
            else None
        )

        command = self.controller.compute_command(
            selected,
            feedback,
            timestamp,
            body_state=body_state,
        )
        self.driver.set_yaw_pitch_rate(
            command.yaw_rate_cmd_dps, command.pitch_rate_cmd_dps, timestamp
        )

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
            },
        )
        if selected is not None and selected.track_id != self._last_target_id:
            self.telemetry.log("switch", timestamp, {"track_id": float(selected.track_id)})
            self._last_target_id = selected.track_id
        if selected is None:
            self._last_target_id = None
        return PipelineOutputs(selected_target=selected, command=command)
