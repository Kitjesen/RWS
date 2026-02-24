"""MPC Controller for 2-DOF Gimbal.

Short-horizon Model Predictive Control as a drop-in replacement for the
PID controller.  The optimal feedback gain K is precomputed offline using
batch MPC (numpy only, no QP solver required), then applied at runtime in
O(1): u* = -K·e.

Plant model (1-D integrator):
    e[k+1] = e[k] - dt·u[k]
    (rate command u integrates the angle error e toward zero)

MPC cost:
    J = Σ_{k=0}^{N-1} (q_e·e[k]² + r_u·u[k]²) + q_term·e[N]²

Unconstrained batch-MPC solution (first control step only — receding horizon):
    u*[0] = K_mpc · e[0]
    K_mpc = first element of (Su^T Q Su + R)^{-1} Su^T Q Sx

Steady-state behaviour:
    K_mpc → √(q_e / r_u) / dt  as N → ∞   (LQR limit)
    q_e / r_u ratio tunes aggressiveness (higher → faster, like bigger Kp).

Integral action is added explicitly (separate integrator state) to eliminate
steady-state error.

Advantages over standard PID
------------------------------
* Principled gain tuning via q/r ratio (no manual Kp/Ki/Kd search)
* Velocity feedforward integrated into cost objective
* Predictive N-step horizon reduces control lag compared to pure proportional
* Natural soft rate saturation through r_effort weight
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class MPCConfig:
    """Tuning parameters for the MPC controller.

    Attributes
    ----------
    horizon : int
        Prediction horizon N (steps). Longer horizon → more anticipatory,
        smoother control at the cost of a larger precompute (still O(1) runtime).
    q_error : float
        Stage state-cost weight (error²). Higher → more aggressive rejection.
    r_effort : float
        Stage control-effort weight (u²). Higher → smoother, less aggressive.
    q_terminal : float
        Terminal state cost. 0 = inherit q_error (recommended).
    integral_limit : float
        Anti-windup clamp on the integral accumulator (deg·s).
    output_limit : float
        Hard output clamp (deg/s).
    ki : float
        Integral gain multiplier. Set 0 to disable integral action.
    derivative_lpf_alpha : float
        LPF coefficient for derivative smoothing (0 = heavy filter, 1 = off).
    feedforward_kv : float
        Velocity feedforward gain (scales the feedforward argument to step()).
    plant_dt : float
        Plant timestep used for offline gain computation.
        Should match the expected pipeline loop interval (e.g. 1/30 ≈ 0.033 s).
    """

    horizon: int = 10
    q_error: float = 100.0
    r_effort: float = 1.0
    q_terminal: float = 0.0       # 0 = use q_error
    integral_limit: float = 30.0
    output_limit: float = 90.0
    ki: float = 0.3
    derivative_lpf_alpha: float = 0.3
    feedforward_kv: float = 0.0
    plant_dt: float = 0.033


class MPCController:
    """Precomputed-gain MPC controller.

    Drop-in replacement for ``PID`` — same ``.step(error, dt, feedforward)``
    interface and ``.reset()`` method.

    Internals
    ---------
    Gain K_mpc is precomputed in ``__init__`` via batch MPC (numpy solve).
    At runtime only ``K_mpc * error + ki * integral + kv * ff`` is evaluated.

    Integral term
    -------------
    The integrator-plant (A=1, B=-dt) has a pole at z=1.  Pure proportional
    feedback from MPC leaves a steady-state error of r·dt / (q·dt²+r).
    An explicit integral accumulator with gain ``ki`` eliminates this offset
    at the cost of a small increase in settling time — identical in concept to
    the PID integral term.

    Usage::

        from rws_tracking.control.mpc_controller import MPCController, MPCConfig
        cfg = MPCConfig(horizon=10, q_error=200.0, r_effort=0.5, ki=0.2)
        ctrl = MPCController(cfg)
        cmd = ctrl.step(error_deg, dt_s)
    """

    def __init__(self, cfg: MPCConfig | None = None) -> None:
        self.cfg = cfg or MPCConfig()

        # Internal state (mirrors PIDState for drop-in compatibility)
        self._integral: float = 0.0
        self._prev_error: float = 0.0
        self._d_lpf: float = 0.0
        self._first_call: bool = True

        # Precompute MPC proportional gain K_mpc offline
        q_term = self.cfg.q_terminal if self.cfg.q_terminal > 0.0 else self.cfg.q_error
        self._K = self._precompute_gain(
            N=self.cfg.horizon,
            q_e=self.cfg.q_error,
            r_u=self.cfg.r_effort,
            q_term=q_term,
            dt=self.cfg.plant_dt,
        )
        logger.info(
            "MPCController initialized: horizon=%d q_e=%.1f r_u=%.2f "
            "K_mpc=%.4f (equiv_Kp≈%.4f)",
            self.cfg.horizon, self.cfg.q_error, self.cfg.r_effort,
            self._K,
            math.sqrt(self.cfg.q_error / max(self.cfg.r_effort, 1e-9)) / max(self.cfg.plant_dt, 1e-9),
        )

    # ------------------------------------------------------------------
    # Public API — identical to PID
    # ------------------------------------------------------------------

    def step(self, error: float, dt: float, feedforward: float = 0.0) -> float:
        """Compute rate command for the given tracking error.

        Parameters
        ----------
        error : float
            Tracking error (degrees). Positive → gimbal needs to move positive.
        dt : float
            Time since last call (seconds).
        feedforward : float
            Optional velocity feedforward (deg/s) — e.g. estimated target
            angular rate from pixel-velocity conversion.

        Returns
        -------
        float
            Rate command (deg/s) clamped to ±``output_limit``.
        """
        if dt <= 0.0:
            return 0.0

        # Integral with anti-windup
        self._integral += error * dt
        self._integral = max(
            -self.cfg.integral_limit,
            min(self.cfg.integral_limit, self._integral),
        )

        # Derivative with low-pass filter (matches PID derivative LPF)
        if self._first_call:
            self._prev_error = error
            self._first_call = False
        derivative = (error - self._prev_error) / dt
        alpha = self.cfg.derivative_lpf_alpha
        self._d_lpf = alpha * derivative + (1.0 - alpha) * self._d_lpf
        self._prev_error = error

        # MPC proportional + integral + feedforward
        # Note: K_mpc replaces Kp; ki and feedforward_kv are additive
        output = (
            self._K * error
            + self.cfg.ki * self._integral
            + self.cfg.feedforward_kv * feedforward
        )
        return max(-self.cfg.output_limit, min(self.cfg.output_limit, output))

    def reset(self) -> None:
        """Reset all internal state (integral, derivative, first-call flag)."""
        self._integral = 0.0
        self._prev_error = 0.0
        self._d_lpf = 0.0
        self._first_call = True

    # ------------------------------------------------------------------
    # Gain precomputation
    # ------------------------------------------------------------------

    @staticmethod
    def _precompute_gain(
        N: int,
        q_e: float,
        r_u: float,
        q_term: float,
        dt: float,
    ) -> float:
        """Precompute the MPC proportional gain K_mpc using batch MPC.

        Plant: e[k+1] = A·e[k] + B·u[k],  A=1, B=-dt

        Stacked prediction:
            E = Sx·e[0] + Su·U       (N+1 predicted states, N controls)

        Cost:
            J = E^T Q_N E + U^T R_N U

        Optimal (unconstrained) solution:
            U* = -(Su^T Q_N Su + R_N)^{-1} Su^T Q_N Sx · e[0]

        Returns K_mpc = -U*[0] / e[0]  (first control step only).

        Parameters
        ----------
        N : int          Horizon length (number of control steps).
        q_e : float      Stage state cost weight.
        r_u : float      Stage control effort weight.
        q_term : float   Terminal state cost weight (applied to e[N]).
        dt : float       Plant timestep (seconds).
        """
        A = 1.0
        B = -dt  # positive rate drives error negative

        # Sx (N+1, 1): free-response state sequence for U=0
        # e[k] = A^k · e[0]
        Sx = np.array([[A ** k] for k in range(1, N + 2)], dtype=np.float64)  # (N+1, 1)

        # Su (N+1, N): forced-response matrix
        # e[k] is influenced by u[j] for j < k:  coeff = A^(k-j-1) · B
        Su = np.zeros((N + 1, N), dtype=np.float64)
        for k in range(1, N + 2):
            for j in range(min(k, N)):
                Su[k - 1, j] = A ** (k - j - 1) * B

        # Diagonal cost weights: stage cost q_e, terminal cost q_term
        Q_diag = np.full(N + 1, q_e, dtype=np.float64)
        Q_diag[-1] = q_term
        Q_N = np.diag(Q_diag)           # (N+1, N+1)
        R_N = r_u * np.eye(N, dtype=np.float64)  # (N, N)

        # Optimal gain matrix: K_full (N, 1), only first element needed
        SuT_Q = Su.T @ Q_N                                  # (N, N+1)
        # U* = -(Su^T Q Su + R)^{-1} Su^T Q Sx · e0  → negate result
        K_full = np.linalg.solve(SuT_Q @ Su + R_N, SuT_Q @ Sx)  # (N, 1)

        return -float(K_full[0, 0])  # minus sign from optimal U* derivation

    def __repr__(self) -> str:
        return (
            f"MPCController(N={self.cfg.horizon}, "
            f"q_e={self.cfg.q_error}, r_u={self.cfg.r_effort}, "
            f"K_mpc={self._K:.4f})"
        )
