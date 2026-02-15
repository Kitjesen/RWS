"""Control layer interfaces -- implement these to swap control algorithms."""

from __future__ import annotations

from typing import Protocol

from ..types import BodyState, ControlCommand, GimbalFeedback, TargetObservation


class GimbalController(Protocol):
    """
    Takes a target observation and gimbal feedback, returns a control command.

    To implement your own controller:
        1. Create a class with a ``compute_command`` method matching this signature.
        2. Inject it into ``VisionGimbalPipeline`` via the ``controller`` parameter.
    """

    def compute_command(
        self,
        target: TargetObservation | None,
        feedback: GimbalFeedback,
        timestamp: float,
        body_state: BodyState | None = None,
    ) -> ControlCommand: ...
