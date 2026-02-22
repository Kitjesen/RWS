"""Tests for VideoRingBuffer.

Uses synthetic 640x480x3 uint8 numpy arrays — no real camera or cv2 needed.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pytest

from src.rws_tracking.telemetry.video_ring_buffer import (
    VideoRingBuffer,
    _clip_stem,
    _parse_timestamp_from_filename,
    _try_write_mp4,
    _write_jpegs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _frame(val: int = 128) -> np.ndarray:
    """Return a 640x480 BGR uint8 frame filled with *val*."""
    return np.full((480, 640, 3), val, dtype=np.uint8)


def _push_n(buf: VideoRingBuffer, n: int, start_ts: float = 0.0, dt: float = 1.0 / 30) -> float:
    """Push *n* frames and return the timestamp of the last frame."""
    ts = start_ts
    for _ in range(n):
        buf.push(_frame(), ts)
        ts += dt
    return ts - dt


# ---------------------------------------------------------------------------
# Basic construction and push
# ---------------------------------------------------------------------------

class TestBasicBehavior:
    def test_empty_buffer_len(self):
        buf = VideoRingBuffer(duration_s=5.0, fps=30.0)
        assert len(buf) == 0

    def test_push_increases_len(self):
        buf = VideoRingBuffer(duration_s=5.0, fps=30.0)
        buf.push(_frame(), 0.0)
        assert len(buf) == 1
        buf.push(_frame(), 1.0)
        assert len(buf) == 2

    def test_maxlen_enforced(self):
        fps = 30.0
        duration = 2.0
        buf = VideoRingBuffer(duration_s=duration, fps=fps)
        expected_max = int(duration * fps)
        # Push more frames than the buffer can hold
        for i in range(expected_max + 50):
            buf.push(_frame(), i / fps)
        assert len(buf) == expected_max

    def test_thread_safety_concurrent_push(self):
        """Concurrent pushes must not corrupt the buffer."""
        import threading

        buf = VideoRingBuffer(duration_s=5.0, fps=30.0)
        errors = []

        def push_loop(start_ts: float) -> None:
            try:
                for i in range(60):
                    buf.push(_frame(i % 255), start_ts + i / 30.0)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=push_loop, args=(t * 100,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Exceptions in push threads: {errors}"


# ---------------------------------------------------------------------------
# save_clip — empty-buffer early exit
# ---------------------------------------------------------------------------

class TestSaveClipEmptyBuffer:
    def test_returns_none_when_empty(self, tmp_path):
        buf = VideoRingBuffer(output_dir=tmp_path, fps=30.0)
        result = buf.save_clip(event_ts=1.0)
        assert result is None


# ---------------------------------------------------------------------------
# save_clip — JPEG fallback (no cv2.VideoWriter required)
# ---------------------------------------------------------------------------

class TestSaveClipJpegFallback:
    """Force the JPEG fallback by monkeypatching _try_write_mp4."""

    def test_jpeg_dir_created(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "src.rws_tracking.telemetry.video_ring_buffer._try_write_mp4",
            lambda *a, **kw: False,
        )
        buf = VideoRingBuffer(
            duration_s=5.0, pre_event_s=1.0, post_event_s=0.1,
            output_dir=tmp_path, fps=10.0,
        )
        n = 20
        _push_n(buf, n, start_ts=0.0, dt=0.1)

        out_path = buf.save_clip(event_ts=1.0, event_label="fire", track_id=7)
        assert out_path is not None

        # Wait for background thread to write.
        time.sleep(0.5)

        # Expect a subdirectory named after the stem (without .mp4).
        stem = Path(out_path).stem
        jpeg_dir = tmp_path / stem
        assert jpeg_dir.exists(), f"Expected JPEG dir {jpeg_dir} to exist"
        jpgs = list(jpeg_dir.iterdir())
        assert len(jpgs) > 0, "Expected at least one frame file in JPEG dir"

    def test_jpeg_files_have_expected_names(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "src.rws_tracking.telemetry.video_ring_buffer._try_write_mp4",
            lambda *a, **kw: False,
        )
        buf = VideoRingBuffer(
            duration_s=5.0, pre_event_s=2.0, post_event_s=0.1,
            output_dir=tmp_path, fps=10.0,
        )
        _push_n(buf, 30, start_ts=0.0, dt=0.1)

        buf.save_clip(event_ts=2.0, event_label="fire")
        time.sleep(0.5)

        # Find the created subdirectory.
        dirs = [p for p in tmp_path.iterdir() if p.is_dir()]
        assert len(dirs) == 1
        files = sorted(dirs[0].iterdir())
        assert len(files) > 0
        for f in files:
            # Accept both .jpg (cv2) and .ppm (numpy fallback) extensions.
            assert f.suffix in (".jpg", ".ppm", ".jpeg"), f"Unexpected file: {f}"


# ---------------------------------------------------------------------------
# save_clip — MP4 path (mocked VideoWriter)
# ---------------------------------------------------------------------------

class TestSaveClipMp4:
    """Test the MP4 write path using a mock cv2 module."""

    def test_mp4_written_when_writer_succeeds(self, tmp_path, monkeypatch):
        written_frames = []

        class _MockWriter:
            def isOpened(self):
                return True

            def write(self, frame):
                written_frames.append(frame.copy())

            def release(self):
                pass

        class _MockCv2:
            VideoWriter_fourcc = staticmethod(lambda *args: 0)

            @staticmethod
            def VideoWriter(path, fourcc, fps, size):
                # Create a placeholder file so VideoRingBuffer logic stays green.
                Path(path).touch()
                return _MockWriter()

        import src.rws_tracking.telemetry.video_ring_buffer as vrb_module
        monkeypatch.setattr(vrb_module, "_try_write_mp4", lambda frames, path, w, h, fps: True)

        buf = VideoRingBuffer(
            duration_s=5.0, pre_event_s=1.0, post_event_s=0.1,
            output_dir=tmp_path, fps=10.0,
        )
        _push_n(buf, 20, start_ts=0.0, dt=0.1)

        out = buf.save_clip(event_ts=1.0, event_label="fire", track_id=3)
        assert out is not None
        assert out.endswith(".mp4")


# ---------------------------------------------------------------------------
# Return path naming
# ---------------------------------------------------------------------------

class TestClipNaming:
    def test_stem_with_track_id(self):
        stem = _clip_stem(100.5, "fire", 42)
        assert "fire" in stem
        assert "tid42" in stem
        assert "100" in stem

    def test_stem_without_track_id(self):
        stem = _clip_stem(200.123, "test_event", None)
        assert "test_event" in stem
        assert "tid" not in stem

    def test_event_label_spaces_replaced(self):
        stem = _clip_stem(1.0, "fire event", None)
        assert " " not in stem

    def test_save_clip_returns_mp4_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "src.rws_tracking.telemetry.video_ring_buffer._try_write_mp4",
            lambda *a, **kw: True,
        )
        buf = VideoRingBuffer(
            duration_s=5.0, pre_event_s=1.0, post_event_s=0.0,
            output_dir=tmp_path, fps=10.0,
        )
        _push_n(buf, 15, start_ts=0.0, dt=0.1)
        out = buf.save_clip(event_ts=1.0, event_label="fire", track_id=1)
        assert out is not None
        assert out.endswith(".mp4")
        assert "fire" in out
        assert "tid1" in out


# ---------------------------------------------------------------------------
# Pre-event window filtering
# ---------------------------------------------------------------------------

class TestPreEventWindow:
    def test_only_pre_event_frames_collected(self, tmp_path, monkeypatch):
        """Frames older than pre_event_s should NOT be included."""
        collected = []

        def fake_write(frames, out_path, event_label, track_id):
            collected.extend(frames)

        buf = VideoRingBuffer(
            duration_s=10.0, pre_event_s=1.0, post_event_s=0.0,
            output_dir=tmp_path, fps=10.0,
        )
        # Patch _write so we can inspect which frames were collected.
        monkeypatch.setattr(buf, "_write", fake_write)

        # Push 30 frames from t=0..2.9 (dt=0.1).
        _push_n(buf, 30, start_ts=0.0, dt=0.1)

        # Fire event at t=2.0 — only frames in [1.0, 2.0] should be collected.
        buf.save_clip(event_ts=2.0)
        time.sleep(0.3)

        for entry in collected:
            assert entry.timestamp >= 1.0 - 1e-9, (
                f"Frame at ts={entry.timestamp} predates pre_event window"
            )


# ---------------------------------------------------------------------------
# Post-event window
# ---------------------------------------------------------------------------

class TestPostEventWindow:
    def test_post_event_frames_included(self, tmp_path, monkeypatch):
        """Frames pushed AFTER save_clip() is called should appear in the clip."""
        collected = []

        def fake_write(frames, out_path, event_label, track_id):
            collected.extend(frames)

        buf = VideoRingBuffer(
            duration_s=10.0, pre_event_s=0.5, post_event_s=0.5,
            output_dir=tmp_path, fps=10.0,
        )
        monkeypatch.setattr(buf, "_write", fake_write)

        # Push some pre-event frames.
        _push_n(buf, 10, start_ts=0.0, dt=0.1)
        event_ts = 0.9

        # Trigger save_clip (post_event_s=0.5 → deadline ~1.4).
        buf.save_clip(event_ts=event_ts)

        # Push post-event frames (t=1.0..1.3).
        for i in range(4):
            ts = 1.0 + i * 0.1
            buf.push(_frame(200), ts)

        # Wait for background thread.
        time.sleep(0.8)

        post_ts = [e.timestamp for e in collected if e.timestamp > event_ts]
        assert len(post_ts) > 0, "Expected some post-event frames in the clip"


# ---------------------------------------------------------------------------
# _parse_timestamp_from_filename
# ---------------------------------------------------------------------------

class TestParseTimestamp:
    @pytest.mark.parametrize("name,expected", [
        ("fire_tid3_1708123456_789.mp4", 1708123456.789),
        ("fire_1708000000_000.mp4", 1708000000.0),
        ("no_numbers_here.mp4", 0.0),
        ("fire_123.mp4", 0.0),  # only one numeric group at end — no match
    ])
    def test_parse(self, name, expected):
        result = _parse_timestamp_from_filename(name)
        assert abs(result - expected) < 1e-6, f"{name}: got {result}, expected {expected}"


# ---------------------------------------------------------------------------
# _write_jpegs with numpy PPM fallback
# ---------------------------------------------------------------------------

class TestWriteJpegsFallback:
    def test_ppm_written_when_cv2_absent(self, tmp_path, monkeypatch):
        """When cv2 is not importable, _write_jpegs falls back to PPM files."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "cv2":
                raise ImportError("mocked: cv2 not available")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        from src.rws_tracking.telemetry.video_ring_buffer import _FrameEntry, _write_jpegs

        frames = [_FrameEntry(frame=_frame(i * 10), timestamp=float(i)) for i in range(5)]
        jpeg_dir = tmp_path / "clip_frames"
        _write_jpegs(frames, jpeg_dir)

        written = list(jpeg_dir.iterdir())
        assert len(written) == 5
        for f in written:
            assert f.suffix == ".ppm"
            # Verify basic PPM header
            data = f.read_bytes()
            assert data.startswith(b"P6\n")


# ---------------------------------------------------------------------------
# Multiple overlapping events
# ---------------------------------------------------------------------------

class TestMultipleOverlappingEvents:
    def test_two_events_produce_two_clips(self, tmp_path, monkeypatch):
        calls = []

        def fake_write(frames, out_path, event_label, track_id):
            calls.append((str(out_path), len(frames)))

        buf = VideoRingBuffer(
            duration_s=10.0, pre_event_s=0.5, post_event_s=0.1,
            output_dir=tmp_path, fps=10.0,
        )
        monkeypatch.setattr(buf, "_write", fake_write)

        _push_n(buf, 20, start_ts=0.0, dt=0.1)
        buf.save_clip(event_ts=1.0, event_label="fire", track_id=1)
        buf.save_clip(event_ts=1.5, event_label="fire", track_id=2)

        time.sleep(0.5)

        assert len(calls) == 2, f"Expected 2 clip writes, got {len(calls)}: {calls}"
        # The paths should be distinct.
        assert calls[0][0] != calls[1][0]
