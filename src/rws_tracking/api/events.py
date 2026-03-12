"""Server-Sent Events (SSE) event bus for real-time operator alerts.

Architecture
-----------
Singleton ``EventBus`` accepts ``emit()`` calls from anywhere (pipeline,
fire routes, health monitor, mission controller) and fans each event out to
all currently-connected SSE subscribers.

Event types
-----------
fire_chain_state    Fire chain FSM changed state (SAFE→ARMED, etc.)
fire_executed       Round fired (track_id, timestamp)
threat_detected     New track with high threat score entered
target_neutralized  Target marked neutralised by lifecycle manager
health_degraded     Subsystem health dropped to degraded or failed
safety_triggered    Safety interlock blocked a fire command
operator_timeout    Operator watchdog fired (deadman timeout)
mission_started     Mission started
mission_ended       Mission ended (includes report_path)
heartbeat           Keep-alive every HEARTBEAT_INTERVAL_S seconds

SSE wire format (RFC 8895)::

    event: fire_executed
    data: {"track_id": 3, "timestamp": 1234567890.12}
    id: 42

    (blank line)

Usage
-----
Backend code that wants to emit::

    from .events import event_bus
    event_bus.emit("fire_executed", {"track_id": track_id, "timestamp": ts})

Flask route (GET /api/events)::

    from .events import events_bp

    # Already registered in create_flask_app() via server.py
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections.abc import Generator, Iterator

from flask import Blueprint, Response, stream_with_context

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HEARTBEAT_INTERVAL_S: float = 15.0
"""Seconds between keep-alive heartbeat events."""

_MAX_QUEUE_SIZE: int = 256
"""Per-subscriber backlog.  If a slow client fills its queue, events drop."""


# ---------------------------------------------------------------------------
# Event bus
# ---------------------------------------------------------------------------


class EventBus:
    """Thread-safe, fan-out SSE event bus.

    Subscribers call ``subscribe()`` to get a generator that yields SSE
    text chunks.  Publishers call ``emit()`` to broadcast to all subscribers.
    A background heartbeat thread keeps idle connections alive.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: list[queue.Queue[str | None]] = []
        self._event_id: int = 0
        self._heartbeat_thread: threading.Thread | None = None
        self._stopped = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background heartbeat thread.

        Called once during Flask app startup.
        """
        if self._heartbeat_thread is None or not self._heartbeat_thread.is_alive():
            self._stopped = False
            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop,
                name="sse-heartbeat",
                daemon=True,
            )
            self._heartbeat_thread.start()
            logger.info("SSE event bus started (heartbeat=%.0fs)", HEARTBEAT_INTERVAL_S)

    def stop(self) -> None:
        """Signal all subscribers to close and stop the heartbeat."""
        self._stopped = True
        with self._lock:
            for q in self._subscribers:
                try:
                    q.put_nowait(None)  # sentinel → subscriber generator exits
                except queue.Full:
                    pass

    def emit(self, event_type: str, data: dict) -> None:
        """Broadcast an event to every connected subscriber.

        Parameters
        ----------
        event_type:
            One of the event types documented in the module docstring.
        data:
            JSON-serialisable payload dict.
        """
        with self._lock:
            self._event_id += 1
            chunk = _format_sse(event_type, data, self._event_id)
            dead: list[queue.Queue[str | None]] = []
            for q in self._subscribers:
                try:
                    q.put_nowait(chunk)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._subscribers.remove(q)
                logger.debug("SSE: dropped slow subscriber")

    def subscribe(self) -> Generator[str, None, None]:
        """Return an SSE generator for one HTTP connection.

        Yields SSE-formatted text chunks until the client disconnects or the
        bus is stopped.
        """
        q: queue.Queue[str | None] = queue.Queue(maxsize=_MAX_QUEUE_SIZE)
        with self._lock:
            self._subscribers.append(q)
        logger.debug("SSE subscriber connected (total=%d)", len(self._subscribers))

        # Send a welcome event so the client knows the connection is live.
        yield _format_sse("connected", {"message": "SSE stream open"}, 0)

        try:
            while True:
                try:
                    chunk = q.get(timeout=HEARTBEAT_INTERVAL_S + 5)
                except queue.Empty:
                    # Safety valve: shouldn't happen if heartbeat is running.
                    yield ": timeout-keepalive\n\n"
                    continue

                if chunk is None:
                    # Sentinel → bus is shutting down.
                    break
                yield chunk
        finally:
            with self._lock:
                try:
                    self._subscribers.remove(q)
                except ValueError:
                    pass
            logger.debug("SSE subscriber disconnected (total=%d)", len(self._subscribers))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _heartbeat_loop(self) -> None:
        while not self._stopped:
            time.sleep(HEARTBEAT_INTERVAL_S)
            if self._stopped:
                break
            self.emit("heartbeat", {"ts": round(time.time(), 3)})


def _format_sse(event: str, data: dict, event_id: int) -> str:
    """Serialise one SSE event frame."""
    payload = json.dumps(data, default=str)
    return f"event: {event}\ndata: {payload}\nid: {event_id}\n\n"


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

event_bus = EventBus()
"""Module-level singleton.  Import and call ``event_bus.emit()`` anywhere."""


# ---------------------------------------------------------------------------
# Flask Blueprint
# ---------------------------------------------------------------------------

events_bp = Blueprint("events", __name__)


@events_bp.route("/api/events")
def sse_stream():
    """GET /api/events — Server-Sent Events stream.

    Connect with::

        const es = new EventSource('/api/events');
        es.addEventListener('fire_executed', e => console.log(JSON.parse(e.data)));

    Or with Flutter's http package (chunked streaming).
    """

    def _gen() -> Iterator[str]:
        yield from event_bus.subscribe()

    return Response(
        stream_with_context(_gen()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
            "Connection": "keep-alive",
        },
    )
