"""Event bus abstraction — framework-agnostic.

Defines the ``EventBusProtocol`` used by pipeline and safety layers.
The concrete Flask/SSE implementation lives in ``api/events.py``.

Usage
-----
Inject via constructor::

    pipeline = VisionGimbalPipeline(..., event_bus=my_bus)
    watchdog  = OperatorWatchdog(...,   event_bus=my_bus)

In production (``pipeline/app.py``)::

    from .api.events import event_bus          # Flask SSE singleton
    pipeline = VisionGimbalPipeline(..., event_bus=event_bus)

In tests (no Flask needed)::

    from rws_tracking.events import NoopEventBus
    pipeline = VisionGimbalPipeline(..., event_bus=NoopEventBus())
    # or simply omit event_bus — None means no events emitted
"""

from __future__ import annotations

from typing import Protocol


class EventBusProtocol(Protocol):
    """Minimal interface required by pipeline and safety layers.

    Any object with an ``emit(event_type, data)`` method satisfies this
    Protocol — no base class or registration required.
    """

    def emit(self, event_type: str, data: dict) -> None:
        """Broadcast *event_type* with JSON-serialisable *data* payload."""
        ...


class NoopEventBus:
    """Silent drop-all implementation — useful in tests and standalone runs."""

    def emit(self, event_type: str, data: dict) -> None:  # noqa: ARG002
        pass
