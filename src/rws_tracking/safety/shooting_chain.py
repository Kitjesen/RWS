"""Shooting chain state machine for fire control.

States: SAFE -> ARMED -> FIRE_AUTHORIZED -> FIRE_REQUESTED -> FIRED -> COOLDOWN -> ARMED
        ^_________________________SAFE()________________________________________|

Only a single operator can arm the system at a time.  Every frame,
``update_authorization`` should be called with the latest safety status;
``tick`` handles cooldown timeout.
"""

from __future__ import annotations

import logging
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

    def __init__(self, cooldown_s: float = 3.0) -> None:
        self._state: FireChainState = FireChainState.SAFE
        self._cooldown_s = cooldown_s
        self._operator_id: str | None = None
        self._fire_ts: float | None = None

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

    def safe(self, reason: str = "") -> None:
        """Any state -> SAFE."""
        prev = self._state
        self._state = FireChainState.SAFE
        self._operator_id = None
        self._fire_ts = None
        logger.info("chain SAFE from %s reason=%s", prev.value, reason)

    def update_authorization(
        self, fire_authorized: bool, timestamp: float
    ) -> None:
        """Called every pipeline frame.

        ARMED -> FIRE_AUTHORIZED when *fire_authorized* is True.
        FIRE_AUTHORIZED -> ARMED when *fire_authorized* becomes False
        (lost lock, NFZ, etc.).
        """
        if self._state is FireChainState.ARMED and fire_authorized:
            self._state = FireChainState.FIRE_AUTHORIZED
            logger.info("chain -> FIRE_AUTHORIZED ts=%.3f", timestamp)
        elif (
            self._state is FireChainState.FIRE_AUTHORIZED
            and not fire_authorized
        ):
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
