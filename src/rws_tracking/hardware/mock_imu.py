"""
Mock body-motion providers for testing and SIL simulation.
===========================================================

Three implementations:

``StaticBodyMotion``
    Always returns zero orientation & angular rates.
    Equivalent to a stationary base — current system behaviour.

``SinusoidalBodyMotion``
    Simulates periodic walking gait oscillation:
    configurable amplitude and frequency for each axis.
    Useful for SIL closed-loop tests of feedforward compensation.

``ReplayBodyMotion``
    Replays a pre-recorded sequence of ``BodyState`` entries,
    interpolating between the two nearest timestamps.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..types import BodyState

# ---------------------------------------------------------------------------
# Static (zero motion) — drop-in for legacy "base is fixed" assumption
# ---------------------------------------------------------------------------


class StaticBodyMotion:
    """Always returns constant body state.  Implements ``BodyMotionProvider``."""

    def __init__(
        self,
        yaw_rate_dps: float = 0.0,
        pitch_rate_dps: float = 0.0,
        roll_rate_dps: float = 0.0,
    ) -> None:
        self._yaw_rate = yaw_rate_dps
        self._pitch_rate = pitch_rate_dps
        self._roll_rate = roll_rate_dps

    def get_body_state(self, timestamp: float) -> BodyState:
        return BodyState(
            timestamp=timestamp,
            yaw_rate_dps=self._yaw_rate,
            pitch_rate_dps=self._pitch_rate,
            roll_rate_dps=self._roll_rate,
        )


# ---------------------------------------------------------------------------
# Sinusoidal oscillation — models walking gait
# ---------------------------------------------------------------------------


@dataclass
class SinusoidalConfig:
    """Amplitude (deg) and frequency (Hz) for each axis."""

    roll_amplitude_deg: float = 3.0
    roll_freq_hz: float = 2.0
    pitch_amplitude_deg: float = 5.0
    pitch_freq_hz: float = 2.0
    yaw_amplitude_deg: float = 2.0
    yaw_freq_hz: float = 1.0


class SinusoidalBodyMotion:
    """Sinusoidal body motion.  Implements ``BodyMotionProvider``.

    Parameters
    ----------
    config : SinusoidalConfig
        Oscillation parameters.
    t0 : float
        Timestamp that corresponds to phase = 0.
    """

    def __init__(
        self,
        config: SinusoidalConfig = SinusoidalConfig(),
        t0: float = 0.0,
    ) -> None:
        self._cfg = config
        self._t0 = t0

    def get_body_state(self, timestamp: float) -> BodyState:
        t = timestamp - self._t0
        cfg = self._cfg

        roll = cfg.roll_amplitude_deg * math.sin(2.0 * math.pi * cfg.roll_freq_hz * t)
        pitch = cfg.pitch_amplitude_deg * math.sin(2.0 * math.pi * cfg.pitch_freq_hz * t)
        yaw = cfg.yaw_amplitude_deg * math.sin(2.0 * math.pi * cfg.yaw_freq_hz * t)

        # Analytical derivatives (deg/s)
        roll_rate = (
            cfg.roll_amplitude_deg
            * 2.0
            * math.pi
            * cfg.roll_freq_hz
            * math.cos(2.0 * math.pi * cfg.roll_freq_hz * t)
        )
        pitch_rate = (
            cfg.pitch_amplitude_deg
            * 2.0
            * math.pi
            * cfg.pitch_freq_hz
            * math.cos(2.0 * math.pi * cfg.pitch_freq_hz * t)
        )
        yaw_rate = (
            cfg.yaw_amplitude_deg
            * 2.0
            * math.pi
            * cfg.yaw_freq_hz
            * math.cos(2.0 * math.pi * cfg.yaw_freq_hz * t)
        )

        return BodyState(
            timestamp=timestamp,
            roll_deg=roll,
            pitch_deg=pitch,
            yaw_deg=yaw,
            roll_rate_dps=roll_rate,
            pitch_rate_dps=pitch_rate,
            yaw_rate_dps=yaw_rate,
        )


# ---------------------------------------------------------------------------
# Replay from recorded data
# ---------------------------------------------------------------------------


@dataclass
class ReplayBodyMotion:
    """Replay a recorded sequence of ``BodyState``.

    Linearly interpolates between the two nearest timestamps.
    Before the first sample, returns the first sample;
    after the last sample, returns the last sample.

    Implements ``BodyMotionProvider``.

    Parameters
    ----------
    data : list[BodyState]
        Must be sorted by timestamp in ascending order.
    """

    data: list[BodyState] = field(default_factory=list)

    def get_body_state(self, timestamp: float) -> BodyState:
        if not self.data:
            return BodyState(timestamp=timestamp)

        # Clamp to data range
        if timestamp <= self.data[0].timestamp:
            s = self.data[0]
            return BodyState(
                timestamp=timestamp,
                roll_deg=s.roll_deg,
                pitch_deg=s.pitch_deg,
                yaw_deg=s.yaw_deg,
                roll_rate_dps=s.roll_rate_dps,
                pitch_rate_dps=s.pitch_rate_dps,
                yaw_rate_dps=s.yaw_rate_dps,
            )
        if timestamp >= self.data[-1].timestamp:
            s = self.data[-1]
            return BodyState(
                timestamp=timestamp,
                roll_deg=s.roll_deg,
                pitch_deg=s.pitch_deg,
                yaw_deg=s.yaw_deg,
                roll_rate_dps=s.roll_rate_dps,
                pitch_rate_dps=s.pitch_rate_dps,
                yaw_rate_dps=s.yaw_rate_dps,
            )

        # Binary search for the interval
        lo, hi = 0, len(self.data) - 1
        while lo < hi - 1:
            mid = (lo + hi) // 2
            if self.data[mid].timestamp <= timestamp:
                lo = mid
            else:
                hi = mid

        a, b = self.data[lo], self.data[hi]
        span = b.timestamp - a.timestamp
        alpha = (timestamp - a.timestamp) / span if span > 1e-12 else 0.0

        def _lerp(va: float, vb: float) -> float:
            return va + alpha * (vb - va)

        return BodyState(
            timestamp=timestamp,
            roll_deg=_lerp(a.roll_deg, b.roll_deg),
            pitch_deg=_lerp(a.pitch_deg, b.pitch_deg),
            yaw_deg=_lerp(a.yaw_deg, b.yaw_deg),
            roll_rate_dps=_lerp(a.roll_rate_dps, b.roll_rate_dps),
            pitch_rate_dps=_lerp(a.pitch_rate_dps, b.pitch_rate_dps),
            yaw_rate_dps=_lerp(a.yaw_rate_dps, b.yaw_rate_dps),
        )
