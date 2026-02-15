"""Multi-gimbal pipeline for coordinated multi-target tracking."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..control.interfaces import GimbalController
from ..hardware.interfaces import GimbalDriver
from ..perception.interfaces import Detector, Tracker
from ..perception.multi_target import TargetAllocator, TargetAssignment
from ..perception.multi_target_selector import WeightedMultiTargetSelector
from ..telemetry.interfaces import TelemetryLogger
from ..types import ControlCommand, TargetObservation

logger = logging.getLogger(__name__)


@dataclass
class GimbalUnit:
    """A single gimbal unit with its controller and driver."""

    unit_id: int
    controller: GimbalController
    driver: GimbalDriver
    telemetry: TelemetryLogger


@dataclass
class MultiGimbalOutputs:
    """Outputs from multi-gimbal pipeline step."""

    assignments: list[TargetAssignment]
    commands: list[ControlCommand]
    all_targets: list[TargetObservation]


class MultiGimbalPipeline:
    """Coordinates multiple gimbals to track multiple targets.

    Architecture:
    1. Single detector + tracker (shared)
    2. Multi-target selector (returns top N targets)
    3. Target allocator (assigns targets to gimbals using Hungarian algorithm)
    4. Multiple controllers + drivers (one per gimbal)
    """

    def __init__(
        self,
        detector: Detector,
        tracker: Tracker,
        selector: WeightedMultiTargetSelector,
        allocator: TargetAllocator,
        gimbal_units: list[GimbalUnit],
    ):
        """Initialize multi-gimbal pipeline.

        Parameters
        ----------
        detector : Detector
            Shared object detector
        tracker : Tracker
            Shared multi-object tracker
        selector : WeightedMultiTargetSelector
            Multi-target selector
        allocator : TargetAllocator
            Target-to-gimbal allocator
        gimbal_units : List[GimbalUnit]
            List of gimbal units (controllers + drivers)
        """
        self.detector = detector
        self.tracker = tracker
        self.selector = selector
        self.allocator = allocator
        self.gimbal_units = gimbal_units

        logger.info("MultiGimbalPipeline initialized with %d gimbal units", len(gimbal_units))

    def step(self, frame: object, timestamp: float) -> MultiGimbalOutputs:
        """Process one frame and update all gimbals.

        Parameters
        ----------
        frame : object
            Input frame (image or detection list)
        timestamp : float
            Current timestamp

        Returns
        -------
        MultiGimbalOutputs
            Assignments, commands, and all detected targets
        """
        # 1. Detect and track
        detections = self.detector.detect(frame, timestamp)
        tracks = self.tracker.update(detections, timestamp)

        # 2. Select top N targets
        max_targets = len(self.gimbal_units)
        targets = self.selector.select_multiple(tracks, timestamp, max_targets)

        if not targets:
            # No targets: all gimbals enter SEARCH mode
            logger.debug("No targets detected, all gimbals searching")
            commands = []
            for unit in self.gimbal_units:
                feedback = unit.driver.get_feedback(timestamp)
                cmd = unit.controller.compute_command(None, feedback, timestamp)
                unit.driver.set_yaw_pitch_rate(
                    cmd.yaw_rate_cmd_dps, cmd.pitch_rate_cmd_dps, timestamp
                )
                commands.append(cmd)
                self._log_telemetry(unit, cmd, None, timestamp)

            return MultiGimbalOutputs(assignments=[], commands=commands, all_targets=[])

        # 3. Get current gimbal positions
        executor_positions = []
        for unit in self.gimbal_units:
            feedback = unit.driver.get_feedback(timestamp)
            executor_positions.append((feedback.yaw_deg, feedback.pitch_deg))

        # 4. Allocate targets to gimbals
        assignments = self.allocator.allocate(targets, executor_positions)

        # Build assignment map
        assignment_map = {a.executor_id: a for a in assignments}

        # 5. Compute commands for each gimbal
        commands = []
        for unit in self.gimbal_units:
            feedback = unit.driver.get_feedback(timestamp)

            # Get assigned target (if any)
            assignment = assignment_map.get(unit.unit_id)
            target = assignment.target if assignment else None

            # Compute command
            cmd = unit.controller.compute_command(target, feedback, timestamp)

            # Send to driver
            unit.driver.set_yaw_pitch_rate(cmd.yaw_rate_cmd_dps, cmd.pitch_rate_cmd_dps, timestamp)

            commands.append(cmd)

            # Log telemetry
            self._log_telemetry(unit, cmd, target, timestamp)

            if assignment:
                logger.debug(
                    "Gimbal %d assigned target %d (cost=%.2f)",
                    unit.unit_id,
                    assignment.target.track_id,
                    assignment.cost,
                )

        return MultiGimbalOutputs(assignments=assignments, commands=commands, all_targets=targets)

    def _log_telemetry(
        self,
        unit: GimbalUnit,
        command: ControlCommand,
        target: TargetObservation | None,
        timestamp: float,
    ):
        """Log telemetry for a gimbal unit."""
        unit.telemetry.log(
            "control",
            timestamp,
            {
                "unit_id": float(unit.unit_id),
                "yaw_cmd_dps": command.yaw_rate_cmd_dps,
                "pitch_cmd_dps": command.pitch_rate_cmd_dps,
                "yaw_error_deg": command.metadata.get("yaw_error_deg", 0.0),
                "pitch_error_deg": command.metadata.get("pitch_error_deg", 0.0),
                "state": command.metadata.get("state", 0.0),
                "target_id": float(target.track_id) if target else -1.0,
            },
        )
