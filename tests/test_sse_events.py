"""Tests for the SSE event bus (src/rws_tracking/api/events.py)."""

from __future__ import annotations

import queue
import threading
import time

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _import_bus():
    """Import a fresh EventBus (bypasses module-level singleton)."""
    from src.rws_tracking.api.events import EventBus

    return EventBus()


# ---------------------------------------------------------------------------
# EventBus unit tests
# ---------------------------------------------------------------------------


class TestEventBusBroadcast:
    def test_emit_reaches_single_subscriber(self):
        bus = _import_bus()
        received = []

        def _consume():
            for chunk in bus.subscribe():
                received.append(chunk)
                if len(received) >= 2:
                    break  # collected welcome + test_event

        t = threading.Thread(target=_consume, daemon=True)
        t.start()
        time.sleep(0.05)  # let subscriber register

        bus.emit("test_event", {"value": 42})
        t.join(timeout=2.0)

        assert len(received) == 2  # 'connected' welcome + 'test_event'
        assert "test_event" in received[-1]
        assert "42" in received[-1]

    def test_emit_fans_out_to_multiple_subscribers(self):
        bus = _import_bus()
        results: list[list[str]] = [[], []]

        def _consume(idx):
            for chunk in bus.subscribe():
                results[idx].append(chunk)
                if len(results[idx]) >= 2:
                    break

        threads = [threading.Thread(target=_consume, args=(i,), daemon=True) for i in range(2)]
        for t in threads:
            t.start()
        time.sleep(0.05)

        bus.emit("ping", {"x": 1})

        for t in threads:
            t.join(timeout=2.0)

        # Both subscribers should have received the ping event.
        for r in results:
            combined = " ".join(r)
            assert "ping" in combined

    def test_stop_sends_sentinel_to_all_subscribers(self):
        bus = _import_bus()
        done = threading.Event()

        def _consume():
            for _ in bus.subscribe():
                pass  # drain until sentinel
            done.set()

        t = threading.Thread(target=_consume, daemon=True)
        t.start()
        time.sleep(0.05)

        bus.stop()
        assert done.wait(timeout=2.0), "subscriber did not exit after stop()"
        t.join(timeout=1.0)

    def test_emit_increments_event_id(self):
        bus = _import_bus()
        received = []

        def _consume():
            for chunk in bus.subscribe():
                received.append(chunk)
                if len(received) >= 3:
                    break

        t = threading.Thread(target=_consume, daemon=True)
        t.start()
        time.sleep(0.05)

        bus.emit("e1", {})
        bus.emit("e2", {})
        t.join(timeout=2.0)

        # IDs should increase.
        id_lines = [
            id_line
            for chunk in received
            for id_line in chunk.split("\n")
            if id_line.startswith("id:")
        ]
        ids = [int(id_line.split(":")[1]) for id_line in id_lines]
        assert ids == sorted(ids), "event IDs must be monotonically increasing"

    def test_slow_subscriber_queue_full_does_not_block_others(self):
        """Dropping events for a slow subscriber must not affect a fast one."""
        from src.rws_tracking.api.events import _MAX_QUEUE_SIZE

        bus = _import_bus()

        fast_received = []
        fast_ready = threading.Event()

        def _fast():
            fast_ready.set()
            for chunk in bus.subscribe():
                fast_received.append(chunk)
                if len(fast_received) >= 2:
                    break

        # Slow subscriber: never reads.
        slow_q = queue.Queue(maxsize=1)

        with bus._lock:
            bus._subscribers.append(slow_q)  # inject directly

        t = threading.Thread(target=_fast, daemon=True)
        t.start()
        fast_ready.wait(timeout=1.0)
        time.sleep(0.05)

        # Emit more events than slow_q can hold.
        for i in range(_MAX_QUEUE_SIZE + 5):
            bus.emit("flood", {"i": i})

        t.join(timeout=3.0)
        # Fast subscriber received events; no deadlock.
        assert len(fast_received) >= 2


# ---------------------------------------------------------------------------
# Format helper
# ---------------------------------------------------------------------------


class TestFormatSSE:
    def test_format_includes_event_data_id(self):
        from src.rws_tracking.api.events import _format_sse

        out = _format_sse("fire_executed", {"track_id": 7}, 3)
        assert "event: fire_executed" in out
        assert '"track_id": 7' in out
        assert "id: 3" in out
        assert out.endswith("\n\n")

    def test_format_handles_non_serialisable_via_str(self):
        import datetime

        from src.rws_tracking.api.events import _format_sse

        out = _format_sse("ts_event", {"ts": datetime.datetime(2025, 1, 1)}, 1)
        assert "2025" in out  # datetime serialised via str()


# ---------------------------------------------------------------------------
# Flask SSE endpoint smoke test
# ---------------------------------------------------------------------------


class TestSseBlueprintRoute:
    def test_sse_endpoint_returns_event_stream(self):
        """GET /api/events returns text/event-stream and opens cleanly."""
        from flask import Flask

        from src.rws_tracking.api.events import EventBus, events_bp

        # Use a fresh isolated bus so the heartbeat thread doesn't interfere.
        fresh_bus = EventBus()

        app = Flask(__name__)
        app.register_blueprint(events_bp)

        # Patch the module-level event_bus used inside the route.
        import src.rws_tracking.api.events as events_mod

        original_bus = events_mod.event_bus
        events_mod.event_bus = fresh_bus

        try:
            with app.test_client() as client:
                # Open SSE stream (streaming=True to avoid buffering).
                with client.get("/api/events") as resp:
                    assert resp.status_code == 200
                    assert "text/event-stream" in resp.content_type
                    # Read just the first chunk (welcome event).
                    first = next(resp.response)
                    assert b"connected" in first
        finally:
            events_mod.event_bus = original_bus
            fresh_bus.stop()
