"""Operator deadman-switch watchdog.

If the operator stops sending heartbeats for longer than *timeout_s*,
the watchdog automatically forces the ShootingChain to SAFE state.

This works independently of SafetyInterlock — it provides belt-and-suspenders
safety even when no SafetyManager is configured (e.g., dev/simulation mode).

Usage::

    watchdog = OperatorWatchdog(chain, timeout_s=5.0)
    watchdog.start()

    # Operator sends heartbeat via /api/fire/heartbeat:
    watchdog.heartbeat()

    # Shutdown gracefully:
    watchdog.stop()
"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)


class OperatorWatchdog:
    """Thread-based operator deadman switch.

    Parameters
    ----------
    shooting_chain :
        The :class:`~rws_tracking.safety.shooting_chain.ShootingChain` instance
        to force-safe when the operator times out.
    timeout_s : float
        Seconds without a heartbeat before auto-safe is triggered.
    check_interval_s : float
        How often the watchdog thread checks the heartbeat timestamp.
    """

    def __init__(
        self,
        shooting_chain,
        timeout_s: float = 5.0,
        check_interval_s: float = 1.0,
    ) -> None:
        self._chain = shooting_chain
        self._timeout_s = timeout_s
        self._check_interval_s = check_interval_s

        self._last_heartbeat_ts: float = time.monotonic()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = False
        self._timed_out = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def heartbeat(self, operator_id: str = "") -> None:
        """Refresh the operator heartbeat.

        Call this whenever a heartbeat HTTP request arrives (e.g., from
        ``/api/fire/heartbeat``).  Resets the timeout counter and, if the
        chain had previously timed out, clears the timed-out flag.
        """
        with self._lock:
            self._last_heartbeat_ts = time.monotonic()
            if self._timed_out:
                self._timed_out = False
                logger.info("watchdog: operator reconnected (id=%s)", operator_id)

    @property
    def seconds_since_heartbeat(self) -> float:
        with self._lock:
            return time.monotonic() - self._last_heartbeat_ts

    @property
    def timed_out(self) -> bool:
        return self._timed_out

    def start(self) -> None:
        """Start the background watchdog thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="operator-watchdog")
        self._thread.start()
        logger.info("watchdog: started (timeout=%.1fs)", self._timeout_s)

    def stop(self) -> None:
        """Stop the watchdog thread gracefully."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=self._check_interval_s * 2)
        logger.info("watchdog: stopped")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self) -> None:
        while self._running:
            elapsed = self.seconds_since_heartbeat
            if elapsed > self._timeout_s and not self._timed_out:
                self._timed_out = True
                logger.warning(
                    "watchdog: operator heartbeat timeout (%.1fs > %.1fs) — forcing SAFE",
                    elapsed,
                    self._timeout_s,
                )
                try:
                    self._chain.safe(f"heartbeat_timeout_{elapsed:.0f}s")
                except Exception as exc:  # noqa: BLE001
                    logger.error("watchdog: failed to safe chain: %s", exc)
                # Notify connected SSE subscribers of the operator timeout.
                try:
                    from ..api.events import event_bus

                    event_bus.emit(
                        "operator_timeout",
                        {
                            "elapsed_s": round(elapsed, 1),
                            "timeout_s": self._timeout_s,
                            "ts": round(time.time(), 3),
                        },
                    )
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(self._check_interval_s)
