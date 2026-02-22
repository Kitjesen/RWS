"""
Track state machine (decision layer).

Decides which phase the system is in: Search / Track / Lock / Lost.
This is a *decision*, not a *control* concern -- the controller only
receives the resulting state and acts on it.
"""

from __future__ import annotations

import logging

from ..config import GimbalControllerConfig
from ..types import TargetError, TrackState

logger = logging.getLogger(__name__)


class TrackStateMachine:
    def __init__(self, cfg: GimbalControllerConfig) -> None:
        self._cfg = cfg
        self._state = TrackState.SEARCH
        self._last_seen_ts: float | None = None
        self._lock_start_ts: float | None = None
        self._high_error_start_ts: float | None = None
        self._last_error: TargetError | None = None

    @property
    def state(self) -> TrackState:
        return self._state

    def _transition(self, new_state: TrackState) -> None:
        """Set state and log transitions."""
        if new_state != self._state:
            logger.info(
                "state transition: %s -> %s",
                self._state.value,
                new_state.value,
            )
            self._state = new_state

    def update(self, error: TargetError | None, timestamp: float) -> TrackState:
        if error is not None:
            self._last_seen_ts = timestamp
            self._last_error = error
            err_mag = max(abs(error.yaw_error_deg), abs(error.pitch_error_deg))
            if err_mag <= self._cfg.lock_error_threshold_deg:
                self._high_error_start_ts = None
                if self._lock_start_ts is None:
                    self._lock_start_ts = timestamp
                if timestamp - self._lock_start_ts >= self._cfg.lock_hold_time_s:
                    self._transition(TrackState.LOCK)
                else:
                    self._transition(TrackState.TRACK)
            else:
                self._lock_start_ts = None
                # TRACK -> SEARCH on sustained high error
                high_err_thresh = (
                    self._cfg.lock_error_threshold_deg * self._cfg.high_error_multiplier
                )
                if err_mag > high_err_thresh:
                    # If already in SEARCH, don't start tracking a target that
                    # is immediately outside the high-error envelope.  This
                    # prevents the SEARCH→TRACK→SEARCH cycling where the
                    # timeout resets on every re-acquisition attempt.
                    if self._state == TrackState.SEARCH:
                        self._high_error_start_ts = None
                        return self._state
                    if self._high_error_start_ts is None:
                        self._high_error_start_ts = timestamp
                    if timestamp - self._high_error_start_ts >= self._cfg.max_track_error_timeout_s:
                        self._transition(TrackState.SEARCH)
                        self._high_error_start_ts = None
                    else:
                        self._transition(TrackState.TRACK)
                else:
                    self._high_error_start_ts = None
                    self._transition(TrackState.TRACK)
            return self._state

        self._lock_start_ts = None
        self._high_error_start_ts = None
        if self._last_seen_ts is None:
            since_seen = float("inf")
        else:
            since_seen = timestamp - self._last_seen_ts
        if since_seen <= self._cfg.lost_timeout_s:
            self._transition(TrackState.LOST)
        else:
            self._transition(TrackState.SEARCH)
        return self._state
