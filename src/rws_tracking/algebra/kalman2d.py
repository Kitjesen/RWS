"""
Lightweight 2D Kalman Filters for centroid tracking.
=====================================================

Two models provided:

1. **CentroidKalman2D** — Constant-Velocity (CV), 4 states ``[cx, cy, vx, vy]``.
   Good for steady-speed targets.

2. **CentroidKalmanCA** — Constant-Acceleration (CA), 6 states
   ``[cx, cy, vx, vy, ax, ay]``.  Better for targets that speed up, slow down,
   or turn — acceleration is estimated and used for parabolic prediction.

Common API
----------
Both classes share the same public interface:

- ``predict(dt)``  — extrapolate state forward (call every frame, even without
  a measurement).
- ``update(cx, cy)`` — fuse a new centroid measurement.
- ``position``  — ``(cx, cy)`` best estimate.
- ``velocity``  — ``(vx, vy)`` best estimate in px/s.
- ``predict_position(dt_ahead)`` — read-only future extrapolation.

``CentroidKalmanCA`` additionally exposes:

- ``acceleration`` — ``(ax, ay)`` best estimate in px/s².

Pure numpy, no external dependencies, O(1) per step.

Units: position in pixels, velocity in px/s, acceleration in px/s², dt in seconds.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np


@dataclass
class KalmanConfig:
    """Tuning knobs for the 2D centroid Kalman filter.

    Attributes
    ----------
    process_noise_pos : float
        Standard deviation of position process noise (pixels).
        Models random jitter in the centroid measurement.
    process_noise_vel : float
        Standard deviation of velocity process noise (pixels/s).
        Models how quickly the target can change speed.
    measurement_noise : float
        Standard deviation of measurement noise (pixels).
        Reflects the expected noise in the raw mask centroid.
    initial_velocity_var : float
        Initial variance for velocity states (px/s)^2.
        Large value → filter learns velocity quickly from first observations.
    """
    process_noise_pos: float = 3.0
    process_noise_vel: float = 15.0
    measurement_noise: float = 8.0
    initial_velocity_var: float = 200.0


class CentroidKalman2D:
    """
    4-state linear Kalman filter for pixel centroid + velocity.

    Typical usage::

        kf = CentroidKalman2D(cx0, cy0)
        # each frame:
        kf.predict(dt)          # always call first
        if measurement_available:
            kf.update(meas_cx, meas_cy)
        pos = kf.position       # smoothed (cx, cy)
        vel = kf.velocity       # estimated (vx, vy) px/s
    """

    def __init__(
        self,
        cx0: float,
        cy0: float,
        vx0: float = 0.0,
        vy0: float = 0.0,
        config: KalmanConfig = KalmanConfig(),
    ) -> None:
        # State: [cx, cy, vx, vy]
        self._x = np.array([cx0, cy0, vx0, vy0], dtype=np.float64)

        # Covariance
        iv = config.initial_velocity_var
        self._P = np.diag([
            config.measurement_noise ** 2,
            config.measurement_noise ** 2,
            iv,
            iv,
        ]).astype(np.float64)

        # Measurement matrix: observe [cx, cy]
        self._H = np.array([
            [1, 0, 0, 0],
            [0, 1, 0, 0],
        ], dtype=np.float64)

        # Measurement noise
        r = config.measurement_noise ** 2
        self._R = np.diag([r, r]).astype(np.float64)

        # Process noise config (used to build Q each predict step)
        self._q_pos = config.process_noise_pos
        self._q_vel = config.process_noise_vel

        # Identity for convenience
        self._I4 = np.eye(4, dtype=np.float64)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def predict(self, dt: float) -> None:
        """Propagate state forward by *dt* seconds (constant-velocity model)."""
        if dt <= 0.0:
            return

        F = self._transition(dt)
        Q = self._process_noise(dt)

        self._x = F @ self._x
        self._P = F @ self._P @ F.T + Q

    def update(self, cx: float, cy: float) -> None:
        """Fuse a new centroid measurement."""
        z = np.array([cx, cy], dtype=np.float64)
        y = z - self._H @ self._x                     # innovation
        S = self._H @ self._P @ self._H.T + self._R   # innovation covariance
        K = self._P @ self._H.T @ np.linalg.inv(S)    # Kalman gain

        self._x = self._x + K @ y
        self._P = (self._I4 - K @ self._H) @ self._P

    @property
    def position(self) -> Tuple[float, float]:
        """Current estimated position (cx, cy) in pixels."""
        return (float(self._x[0]), float(self._x[1]))

    @property
    def velocity(self) -> Tuple[float, float]:
        """Current estimated velocity (vx, vy) in px/s."""
        return (float(self._x[2]), float(self._x[3]))

    @property
    def state(self) -> np.ndarray:
        """Full state vector [cx, cy, vx, vy] (read-only copy)."""
        return self._x.copy()

    def predict_position(self, dt_ahead: float) -> Tuple[float, float]:
        """Extrapolate position *dt_ahead* seconds into the future (read-only)."""
        cx = self._x[0] + self._x[2] * dt_ahead
        cy = self._x[1] + self._x[3] * dt_ahead
        return (float(cx), float(cy))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _transition(dt: float) -> np.ndarray:
        """State transition matrix F(dt)."""
        return np.array([
            [1, 0, dt, 0],
            [0, 1, 0, dt],
            [0, 0, 1,  0],
            [0, 0, 0,  1],
        ], dtype=np.float64)

    def _process_noise(self, dt: float) -> np.ndarray:
        """
        Discrete-time process noise Q(dt).

        Uses the piecewise-white-noise model where acceleration is the noise
        source:  q_vel drives velocity noise, and position noise is coupled
        through dt.
        """
        dt2 = dt * dt
        dt3 = dt2 * dt
        qp = self._q_pos ** 2
        qv = self._q_vel ** 2
        return np.array([
            [qp + qv * dt3 / 3, 0,                 qv * dt2 / 2, 0],
            [0,                  qp + qv * dt3 / 3, 0,            qv * dt2 / 2],
            [qv * dt2 / 2,      0,                  qv * dt,      0],
            [0,                  qv * dt2 / 2,       0,            qv * dt],
        ], dtype=np.float64)


# ======================================================================
# Constant-Acceleration (CA) model — 6 states
# ======================================================================

@dataclass
class KalmanCAConfig:
    """Tuning knobs for the Constant-Acceleration Kalman filter.

    Attributes
    ----------
    process_noise_pos : float
        Position process noise σ (pixels).
    process_noise_vel : float
        Velocity process noise σ (pixels/s).
    process_noise_acc : float
        Acceleration process noise σ (pixels/s²).
        Controls how rapidly the filter adapts to acceleration changes.
    measurement_noise : float
        Measurement noise σ (pixels).
    initial_velocity_var : float
        Initial velocity variance (px/s)².
    initial_accel_var : float
        Initial acceleration variance (px/s²)².
    """
    process_noise_pos: float = 2.0
    process_noise_vel: float = 10.0
    process_noise_acc: float = 30.0
    measurement_noise: float = 6.0
    initial_velocity_var: float = 200.0
    initial_accel_var: float = 500.0


class CentroidKalmanCA:
    """
    6-state Kalman filter: Constant-Acceleration model.

    State vector  x = [cx, cy, vx, vy, ax, ay]^T

    Compared to CentroidKalman2D (CV):
      - Tracks acceleration explicitly → better during speed changes & turns.
      - predict_position uses parabolic extrapolation (not linear).
      - predict_trajectory returns a list of future points for smooth arc display.

    Typical usage::

        kf = CentroidKalmanCA(cx0, cy0)
        kf.predict(dt)
        kf.update(meas_cx, meas_cy)
        pos = kf.position        # (cx, cy)
        vel = kf.velocity        # (vx, vy)
        acc = kf.acceleration    # (ax, ay)
        trail = kf.predict_trajectory(horizon_s=0.5, steps=8)
    """

    def __init__(
        self,
        cx0: float,
        cy0: float,
        vx0: float = 0.0,
        vy0: float = 0.0,
        config: KalmanCAConfig = KalmanCAConfig(),
    ) -> None:
        # State: [cx, cy, vx, vy, ax, ay]
        self._x = np.array([cx0, cy0, vx0, vy0, 0.0, 0.0], dtype=np.float64)

        # Covariance
        r2 = config.measurement_noise ** 2
        iv = config.initial_velocity_var
        ia = config.initial_accel_var
        self._P = np.diag([r2, r2, iv, iv, ia, ia]).astype(np.float64)

        # Measurement matrix: observe [cx, cy]
        self._H = np.zeros((2, 6), dtype=np.float64)
        self._H[0, 0] = 1.0
        self._H[1, 1] = 1.0

        # Measurement noise
        self._R = np.diag([r2, r2]).astype(np.float64)

        # Process noise parameters
        self._q_pos = config.process_noise_pos
        self._q_vel = config.process_noise_vel
        self._q_acc = config.process_noise_acc

        self._I6 = np.eye(6, dtype=np.float64)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def predict(self, dt: float) -> None:
        """Propagate state forward by *dt* seconds (constant-acceleration model)."""
        if dt <= 0.0:
            return
        F = self._transition(dt)
        Q = self._process_noise(dt)
        self._x = F @ self._x
        self._P = F @ self._P @ F.T + Q

    def update(self, cx: float, cy: float) -> None:
        """Fuse a new centroid measurement."""
        z = np.array([cx, cy], dtype=np.float64)
        y = z - self._H @ self._x
        S = self._H @ self._P @ self._H.T + self._R
        K = self._P @ self._H.T @ np.linalg.inv(S)
        self._x = self._x + K @ y
        self._P = (self._I6 - K @ self._H) @ self._P

    @property
    def position(self) -> Tuple[float, float]:
        return (float(self._x[0]), float(self._x[1]))

    @property
    def velocity(self) -> Tuple[float, float]:
        return (float(self._x[2]), float(self._x[3]))

    @property
    def acceleration(self) -> Tuple[float, float]:
        return (float(self._x[4]), float(self._x[5]))

    @property
    def state(self) -> np.ndarray:
        return self._x.copy()

    def predict_position(self, dt_ahead: float) -> Tuple[float, float]:
        """Parabolic extrapolation: p + v*t + 0.5*a*t²."""
        t = dt_ahead
        t2 = t * t
        cx = self._x[0] + self._x[2] * t + 0.5 * self._x[4] * t2
        cy = self._x[1] + self._x[3] * t + 0.5 * self._x[5] * t2
        return (float(cx), float(cy))

    def predict_trajectory(
        self, horizon_s: float = 0.5, steps: int = 8
    ) -> List[Tuple[float, float]]:
        """Return a list of predicted future positions (parabolic arc)."""
        dt_step = horizon_s / steps
        return [self.predict_position(dt_step * i) for i in range(1, steps + 1)]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _transition(dt: float) -> np.ndarray:
        """State transition F(dt) for constant-acceleration model."""
        dt2 = 0.5 * dt * dt
        return np.array([
            [1, 0, dt, 0,  dt2, 0],
            [0, 1, 0,  dt, 0,   dt2],
            [0, 0, 1,  0,  dt,  0],
            [0, 0, 0,  1,  0,   dt],
            [0, 0, 0,  0,  1,   0],
            [0, 0, 0,  0,  0,   1],
        ], dtype=np.float64)

    def _process_noise(self, dt: float) -> np.ndarray:
        """
        Discrete-time process noise Q(dt) for CA model.

        Jerk (da/dt) is the noise source.  The covariance couples
        through the kinematic integrals:
          pos  += 0.5 * dt² * jerk
          vel  += dt * jerk
          acc  += jerk
        Each axis is independent, so Q is block-diagonal 2x(3x3).
        """
        dt2 = dt * dt
        dt3 = dt2 * dt
        dt4 = dt3 * dt
        dt5 = dt4 * dt

        qp = self._q_pos ** 2
        qv = self._q_vel ** 2
        qa = self._q_acc ** 2

        # Per-axis 3x3 block (pos, vel, acc coupling from jerk noise)
        q_block = qa * np.array([
            [dt5 / 20, dt4 / 8, dt3 / 6],
            [dt4 / 8,  dt3 / 3, dt2 / 2],
            [dt3 / 6,  dt2 / 2, dt],
        ], dtype=np.float64)

        # Add direct pos/vel noise
        q_block[0, 0] += qp * dt + qv * dt3 / 3
        q_block[0, 1] += qv * dt2 / 2
        q_block[1, 0] += qv * dt2 / 2
        q_block[1, 1] += qv * dt

        Q = np.zeros((6, 6), dtype=np.float64)
        # x-axis: indices 0, 2, 4
        # y-axis: indices 1, 3, 5
        idx_x = [0, 2, 4]
        idx_y = [1, 3, 5]
        for i in range(3):
            for j in range(3):
                Q[idx_x[i], idx_x[j]] = q_block[i, j]
                Q[idx_y[i], idx_y[j]] = q_block[i, j]

        return Q
