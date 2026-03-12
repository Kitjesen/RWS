"""Thread-safe video ring buffer for fire-event clip saving.

Retains the last N seconds of frames in memory.  When a fire event occurs,
:meth:`save_clip` writes the surrounding footage (pre-event + post-event) to
disk as an MP4 via ``cv2.VideoWriter``.  If OpenCV is unavailable or the
writer fails to open, it falls back to saving individual JPEG frames inside a
timestamped subdirectory.
"""

from __future__ import annotations

import logging
import re as _re
import threading
import time
from collections import deque
from pathlib import Path
from typing import NamedTuple

import numpy as np

logger = logging.getLogger(__name__)


class _FrameEntry(NamedTuple):
    frame: np.ndarray
    timestamp: float


class VideoRingBuffer:
    """Thread-safe ring buffer that retains the last N seconds of frames.

    When a fire event occurs, call :meth:`save_clip` to write frames around
    the event timestamp to disk as an MP4 file (or a series of JPEG images if
    ``cv2.VideoWriter`` is not available or fails to open).

    Parameters
    ----------
    duration_s : float
        How many seconds of history to retain.
    pre_event_s : float
        Seconds of pre-event footage to include in the saved clip.
    post_event_s : float
        Seconds to wait/capture after the event for the clip.
    output_dir : str | Path
        Where to save event clips.
    fps : float
        Expected frame rate (used to size the deque and estimate clip duration).
    """

    def __init__(
        self,
        duration_s: float = 10.0,
        pre_event_s: float = 3.0,
        post_event_s: float = 2.0,
        output_dir: str | Path = "logs/clips",
        fps: float = 30.0,
    ) -> None:
        self.duration_s = float(duration_s)
        self.pre_event_s = float(pre_event_s)
        self.post_event_s = float(post_event_s)
        self.output_dir = Path(output_dir)
        self.fps = float(fps)

        maxlen = max(1, int(self.duration_s * self.fps))
        self._buffer: deque[_FrameEntry] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

        # Frames collected after a fire event (pending post-event capture).
        # Maps event_id -> list of (entry, deadline_ts) so multiple overlapping
        # events can be tracked simultaneously.
        self._pending_post: list[dict] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def push(self, frame: np.ndarray, timestamp: float) -> None:
        """Add a frame to the ring buffer.  Thread-safe."""
        entry = _FrameEntry(frame=frame, timestamp=timestamp)
        with self._lock:
            self._buffer.append(entry)
            # Feed any pending post-event windows using the domain timestamp.
            for pending in self._pending_post:
                if timestamp <= pending["stream_deadline"]:
                    pending["frames"].append(entry)

    def save_clip(
        self,
        event_ts: float,
        event_label: str = "fire",
        track_id: int | None = None,
    ) -> str | None:
        """Save a clip around *event_ts*.

        Collects frames from ``[event_ts - pre_event_s, event_ts +
        post_event_s]``.  Frames already in the ring buffer cover the
        pre-event window; post-event frames are captured by registering a
        pending-capture record (subsequent :meth:`push` calls will fill it).

        Saving is done in a background thread so this method returns quickly.

        Returns
        -------
        str | None
            The planned output file path (MP4 or JPEG directory).  ``None``
            if the buffer is empty.
        """
        with self._lock:
            pre_frames = [e for e in self._buffer if e.timestamp >= event_ts - self.pre_event_s]
            if not pre_frames and len(self._buffer) == 0:
                logger.warning("VideoRingBuffer.save_clip: buffer empty, skipping")
                return None

            # wall-clock deadline: post_event_s seconds from *now* (not from event_ts,
            # which may be a simulated/domain timestamp rather than time.monotonic()).
            wall_deadline = time.monotonic() + self.post_event_s
            # stream-timestamp deadline: used to filter incoming push() frames by
            # their domain timestamp so we don't include frames far after the event.
            stream_deadline = event_ts + self.post_event_s
            pending: dict = {
                "frames": list(pre_frames),
                "deadline": wall_deadline,  # wall-clock → used for sleep
                "stream_deadline": stream_deadline,  # domain ts → used in push()
                "event_ts": event_ts,
                "event_label": event_label,
                "track_id": track_id,
            }
            self._pending_post.append(pending)

        # Launch a background thread that waits for the post-event window to
        # close then writes the clip to disk.
        stem = _clip_stem(event_ts, event_label, track_id)
        out_path = self.output_dir / f"{stem}.mp4"

        t = threading.Thread(
            target=self._write_clip_when_ready,
            args=(pending, out_path),
            daemon=True,
        )
        t.start()

        return str(out_path)

    def __len__(self) -> int:
        with self._lock:
            return len(self._buffer)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_clip_when_ready(self, pending: dict, out_path: Path) -> None:
        """Block until the post-event deadline passes, then write the clip."""
        deadline = pending["deadline"]
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)

        with self._lock:
            frames = list(pending["frames"])
            try:
                self._pending_post.remove(pending)
            except ValueError:
                pass

        if not frames:
            logger.warning("VideoRingBuffer: no frames collected for clip %s", out_path)
            return

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._write(frames, out_path, pending["event_label"], pending["track_id"])

    def _write(
        self,
        frames: list[_FrameEntry],
        out_path: Path,
        event_label: str,
        track_id: int | None,
    ) -> None:
        """Attempt to write frames as MP4; fall back to JPEG directory."""
        if not frames:
            return

        h, w = frames[0].frame.shape[:2]

        if _try_write_mp4(frames, out_path, w, h, self.fps):
            logger.info("VideoRingBuffer: saved %d-frame clip -> %s", len(frames), out_path)
        else:
            # Fall back to JPEG frames in a subdirectory.
            stem = out_path.stem
            jpeg_dir = out_path.parent / stem
            _write_jpegs(frames, jpeg_dir)
            logger.info("VideoRingBuffer: saved %d JPEG frames -> %s/", len(frames), jpeg_dir)


# ---------------------------------------------------------------------------
# Module-level helpers (no class state needed)
# ---------------------------------------------------------------------------


def _clip_stem(event_ts: float, label: str, track_id: int | None) -> str:
    safe_label = label.replace(" ", "_")
    ts_str = f"{event_ts:.3f}".replace(".", "_")
    if track_id is not None:
        return f"{safe_label}_tid{track_id}_{ts_str}"
    return f"{safe_label}_{ts_str}"


def _try_write_mp4(
    frames: list[_FrameEntry],
    out_path: Path,
    width: int,
    height: int,
    fps: float,
) -> bool:
    """Try to write frames as an MP4 using cv2.VideoWriter.

    Returns True on success, False if cv2 is unavailable or the writer fails.
    """
    try:
        import cv2  # type: ignore[import]
    except ImportError:
        logger.debug("cv2 not available; falling back to JPEG frames")
        return False

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(out_path), fourcc, fps, (width, height))
    if not writer.isOpened():
        logger.debug("cv2.VideoWriter failed to open %s; falling back to JPEG", out_path)
        writer.release()
        return False

    try:
        for entry in frames:
            frame = entry.frame
            # Ensure the frame is 3-channel BGR uint8 as VideoWriter expects.
            if frame.ndim == 2:
                frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            elif frame.shape[2] == 4:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            if frame.dtype != np.uint8:
                frame = np.clip(frame, 0, 255).astype(np.uint8)
            writer.write(frame)
    finally:
        writer.release()

    return True


def _write_jpegs(frames: list[_FrameEntry], jpeg_dir: Path) -> None:
    """Write each frame as a JPEG inside *jpeg_dir*."""
    jpeg_dir.mkdir(parents=True, exist_ok=True)
    try:
        import cv2  # type: ignore[import]

        for i, entry in enumerate(frames):
            fname = jpeg_dir / f"frame_{i:05d}_{entry.timestamp:.3f}.jpg"
            cv2.imwrite(str(fname), entry.frame)
    except ImportError:
        # Last resort: use numpy to write raw PPM (no external deps).
        for i, entry in enumerate(frames):
            fname = jpeg_dir / f"frame_{i:05d}_{entry.timestamp:.3f}.ppm"
            _write_ppm(entry.frame, fname)


def _write_ppm(frame: np.ndarray, path: Path) -> None:
    """Write a numpy RGB/BGR array as a binary PPM file (no cv2/PIL needed)."""
    h, w = frame.shape[:2]
    if frame.ndim == 2:
        # Grayscale -> RGB
        rgb = np.stack([frame, frame, frame], axis=2)
    else:
        rgb = frame[:, :, :3]
    # PPM stores RGB; we assume frame may be BGR — swap channels.
    rgb = rgb[:, :, ::-1].astype(np.uint8)
    header = f"P6\n{w} {h}\n255\n".encode()
    with open(path, "wb") as f:
        f.write(header)
        f.write(rgb.tobytes())


# Matches the last two numeric groups at end of a stem, e.g. _1708123456_789
_TS_RE = _re.compile(r"_(\d+)_(\d{3})$")


def _parse_timestamp_from_filename(name: str) -> float:
    """Extract a float timestamp from a clip filename.

    Clip filenames follow the pattern ``<label>_<ts_int>_<ts_frac>.mp4`` where
    the timestamp seconds were formatted as ``{ts:.3f}`` with the ``.``
    replaced by ``_``.  For example ``fire_1708123456_789.mp4`` encodes
    ``1708123456.789``.

    Falls back to 0.0 if no numeric pattern is found.
    """
    stem = Path(name).stem  # strip extension
    m = _TS_RE.search(stem)
    if m:
        try:
            return float(f"{m.group(1)}.{m.group(2)}")
        except ValueError:
            pass
    return 0.0
