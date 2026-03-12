"""Shooting chain state machine for fire control.

States: SAFE -> ARMED -> FIRE_AUTHORIZED -> FIRE_REQUESTED -> FIRED -> COOLDOWN -> ARMED
        ^_________________________SAFE()________________________________________|

Only a single operator can arm the system at a time.  Every frame,
``update_authorization`` should be called with the latest safety status;
``tick`` handles cooldown timeout.

Two-Man Rule
------------
When enabled (``enable_two_man_rule(True)``), arming requires two *different*
operators to independently confirm within a configurable window.

    Operator A  →  ``initiate_arm("op_a")``
                   returns {"status": "pending_confirmation", ...}

    Operator B  →  ``initiate_arm("op_b")``
                   returns {"status": "armed", "confirmed_by": "op_b"}

If the second confirmation does not arrive within
``_arm_confirmation_timeout_s`` seconds the pending request expires and the
first operator must start over.  An operator may not confirm their own
request (returns an error dict and leaves state unchanged).
"""

from __future__ import annotations

import logging
import time
from enum import Enum

logger = logging.getLogger(__name__)


class FireChainState(str, Enum):
    SAFE = "safe"
    ARMED = "armed"
    FIRE_AUTHORIZED = "fire_authorized"
    FIRE_REQUESTED = "fire_requested"
    FIRED = "fired"
    COOLDOWN = "cooldown"


class ShootingChain:
    """Fire-control state machine.

    Parameters
    ----------
    cooldown_s : float
        Seconds to remain in COOLDOWN after a shot before returning
        to ARMED.
    """

    def __init__(
        self,
        cooldown_s: float = 3.0,
        arm_confirmation_timeout_s: float = 30.0,
    ) -> None:
        self._state: FireChainState = FireChainState.SAFE
        self._cooldown_s = cooldown_s
        self._operator_id: str | None = None
        self._fire_ts: float | None = None

        # Two-man rule state
        self._two_man_rule_enabled: bool = False
        self._arm_initiator: str | None = None
        self._arm_initiated_at: float | None = None
        self._arm_confirmation_timeout_s: float = arm_confirmation_timeout_s

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def arm(self, operator_id: str) -> bool:
        """SAFE -> ARMED.  Returns True if transition succeeded."""
        if self._state is not FireChainState.SAFE:
            return False
        self._state = FireChainState.ARMED
        self._operator_id = operator_id
        logger.info("chain ARM by %s", operator_id)
        return True

    # ------------------------------------------------------------------
    # Two-man rule
    # ------------------------------------------------------------------

    def enable_two_man_rule(self, enabled: bool = True) -> None:
        """Enable or disable the two-man arming rule.

        When *enabled*, ``initiate_arm()`` must be called by two different
        operators before the chain transitions to ARMED.
        """
        self._two_man_rule_enabled = enabled
        logger.info("two_man_rule=%s", enabled)

    def initiate_arm(self, operator_id: str) -> dict:
        """Initiate or confirm a two-man arm request.

        If two-man rule is **disabled**, falls through to the normal ``arm()``
        transition immediately.

        If two-man rule is **enabled**:

        * First call (no pending request): records the initiating operator and
          returns ``{"status": "pending_confirmation", ...}``.
        * Second call (different operator, within timeout): arms the chain and
          returns ``{"status": "armed", "confirmed_by": <op>}``.
        * Same operator as initiator: returns an error dict without changing
          state.
        * Expired request: clears the pending request and returns
          ``{"status": "expired", ...}``.

        Parameters
        ----------
        operator_id:
            Unique identifier for the requesting operator.

        Returns
        -------
        dict
            Status dict with at least a ``"status"`` key.
        """
        if not self._two_man_rule_enabled:
            ok = self.arm(operator_id=operator_id)
            if ok:
                return {"status": "armed", "two_man_required": False}
            return {
                "status": "error",
                "message": f"cannot arm from state {self._state.value}",
                "two_man_required": False,
            }

        # --- Two-man path ---

        # Guard: same operator cannot confirm their own request.
        if self._arm_initiator == operator_id:
            return {
                "status": "error",
                "message": "same operator cannot confirm own arm request",
            }

        if self._arm_initiator is None:
            # First operator: record and wait for second confirmation.
            self._arm_initiator = operator_id
            self._arm_initiated_at = time.monotonic()
            logger.info(
                "two_man_rule: arm initiated by %s (timeout=%.0fs)",
                operator_id,
                self._arm_confirmation_timeout_s,
            )
            return {
                "status": "pending_confirmation",
                "initiated_by": operator_id,
                "expires_in_s": self._arm_confirmation_timeout_s,
            }

        # Second operator: check expiry first.
        assert self._arm_initiated_at is not None  # set alongside _arm_initiator
        elapsed = time.monotonic() - self._arm_initiated_at
        if elapsed > self._arm_confirmation_timeout_s:
            self._arm_initiator = None
            self._arm_initiated_at = None
            logger.warning(
                "two_man_rule: arm request expired (%.1fs > %.0fs)",
                elapsed,
                self._arm_confirmation_timeout_s,
            )
            return {
                "status": "expired",
                "message": "arm request expired, reinitiate",
            }

        # Valid second confirmation — arm.
        combined_id = f"{self._arm_initiator}+{operator_id}"
        self.arm(operator_id=combined_id)
        confirmer = operator_id
        self._arm_initiator = None
        self._arm_initiated_at = None
        logger.info("two_man_rule: ARMED (initiator+confirmer=%s)", combined_id)
        return {"status": "armed", "confirmed_by": confirmer}

    def get_arm_pending_status(self) -> dict | None:
        """Return info about any pending two-man arm request, or ``None``.

        Returns ``None`` when no request is pending or the pending request has
        expired (the expired entry is cleaned up as a side-effect).
        """
        if self._arm_initiator is None:
            return None
        assert self._arm_initiated_at is not None
        elapsed = time.monotonic() - self._arm_initiated_at
        remaining = self._arm_confirmation_timeout_s - elapsed
        if remaining <= 0:
            self._arm_initiator = None
            self._arm_initiated_at = None
            return None
        return {
            "initiated_by": self._arm_initiator,
            "expires_in_s": round(remaining, 1),
        }

    def safe(self, reason: str = "") -> None:
        """Any state -> SAFE."""
        prev = self._state
        self._state = FireChainState.SAFE
        self._operator_id = None
        self._fire_ts = None
        logger.info("chain SAFE from %s reason=%s", prev.value, reason)

    def update_authorization(self, fire_authorized: bool, timestamp: float) -> None:
        """Called every pipeline frame.

        ARMED -> FIRE_AUTHORIZED when *fire_authorized* is True.
        FIRE_AUTHORIZED -> ARMED when *fire_authorized* becomes False
        (lost lock, NFZ, etc.).
        """
        if self._state is FireChainState.ARMED and fire_authorized:
            self._state = FireChainState.FIRE_AUTHORIZED
            logger.info("chain -> FIRE_AUTHORIZED ts=%.3f", timestamp)
        elif self._state is FireChainState.FIRE_AUTHORIZED and not fire_authorized:
            self._state = FireChainState.ARMED
            logger.info(
                "chain FIRE_AUTHORIZED -> ARMED (auth lost) ts=%.3f",
                timestamp,
            )

    def request_fire(self, operator_id: str) -> bool:
        """FIRE_AUTHORIZED -> FIRE_REQUESTED (human presses button).

        Returns True if transition succeeded.
        """
        if self._state is not FireChainState.FIRE_AUTHORIZED:
            return False
        self._state = FireChainState.FIRE_REQUESTED
        logger.info("chain FIRE_REQUESTED by %s", operator_id)
        return True

    def execute_fire(self, timestamp: float) -> bool:
        """FIRE_REQUESTED -> FIRED -> start cooldown timer.

        Returns True if fire command was issued.
        """
        if self._state is not FireChainState.FIRE_REQUESTED:
            return False
        self._state = FireChainState.FIRED
        self._fire_ts = timestamp
        logger.warning(
            "chain FIRED at ts=%.3f operator=%s",
            timestamp,
            self._operator_id,
        )
        # Immediately transition to COOLDOWN
        self._state = FireChainState.COOLDOWN
        return True

    def tick(self, timestamp: float) -> None:
        """Call every frame: handles COOLDOWN -> ARMED timeout."""
        if (
            self._state is FireChainState.COOLDOWN
            and self._fire_ts is not None
            and timestamp - self._fire_ts >= self._cooldown_s
        ):
            self._state = FireChainState.ARMED
            self._fire_ts = None
            logger.info("chain COOLDOWN -> ARMED (cooldown expired)")

    # ------------------------------------------------------------------
    # Read-only properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> FireChainState:
        return self._state

    @property
    def can_fire(self) -> bool:
        """True only when state == FIRE_REQUESTED."""
        return self._state is FireChainState.FIRE_REQUESTED

    @property
    def operator_id(self) -> str | None:
        return self._operator_id
