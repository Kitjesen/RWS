"""视频片段录制 REST API。

操作员可手动开始/停止录制跟踪会话的视频片段，并通过 API 管理已保存的片段。

Routes
------
POST   /api/video/record/start        — 开始录制
POST   /api/video/record/stop         — 停止录制，保存片段
GET    /api/video/record/status       — {"recording": bool, "filename": str|null, "elapsed_s": float}
GET    /api/video/clips               — 列出已保存片段 [{filename, size_mb, created_at}]
GET    /api/video/clips/<filename>    — 下载片段
DELETE /api/video/clips/<filename>    — 删除片段
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from flask import Blueprint, jsonify, request, send_file

logger = logging.getLogger(__name__)

record_bp = Blueprint("video_record", __name__, url_prefix="/api/video")

# ---------------------------------------------------------------------------
# Module-level recorder state (thread-safe)
# ---------------------------------------------------------------------------

_recording: bool = False
_writer = None  # cv2.VideoWriter | None
_clip_filename: str | None = None
_started_at: float | None = None
_lock = threading.Lock()
_clips_dir = Path("logs/clips")

# Recording parameters
_RECORD_FPS = 15
_RECORD_WIDTH = 640
_RECORD_HEIGHT = 480


# ---------------------------------------------------------------------------
# Public helper — called from video_stream.py per frame
# ---------------------------------------------------------------------------


def record_frame(frame: np.ndarray) -> None:
    """Write *frame* to the active VideoWriter if recording is active.

    This function is intentionally a no-op when not recording.
    All exceptions are swallowed so that a broken writer never crashes the
    pipeline.
    """
    with _lock:
        if not _recording or _writer is None:
            return
        writer = _writer

    try:
        import cv2

        h, w = frame.shape[:2]
        if w != _RECORD_WIDTH or h != _RECORD_HEIGHT:
            frame = cv2.resize(frame, (_RECORD_WIDTH, _RECORD_HEIGHT))
        writer.write(frame)
    except Exception as exc:  # noqa: BLE001
        logger.warning("record_frame: write failed: %s", exc)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@record_bp.route("/record/start", methods=["POST"])
def start_recording():
    """Start recording a new video clip.

    Creates ``logs/clips/`` if not exists, opens a cv2.VideoWriter, and
    sets the module-level recording flag.

    Response::

        {"ok": true, "filename": "clip_YYYYMMDD_HHMMSS.mp4"}
    """
    global _recording, _writer, _clip_filename, _started_at

    with _lock:
        if _recording:
            # Idempotent — return current clip name.
            return jsonify({"ok": True, "filename": _clip_filename, "already_recording": True})

        try:
            import cv2

            _clips_dir.mkdir(parents=True, exist_ok=True)

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"clip_{ts}.mp4"
            filepath = _clips_dir / filename

            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(
                str(filepath), fourcc, _RECORD_FPS, (_RECORD_WIDTH, _RECORD_HEIGHT)
            )
            if not writer.isOpened():
                logger.error("VideoWriter failed to open: %s", filepath)
                return jsonify({"ok": False, "error": "VideoWriter failed to open"}), 500

            _writer = writer
            _clip_filename = filename
            _started_at = time.monotonic()
            _recording = True

            logger.info("Video recording started: %s", filename)
            return jsonify({"ok": True, "filename": filename})

        except Exception as exc:
            logger.error("Failed to start recording: %s", exc)
            return jsonify({"ok": False, "error": str(exc)}), 500


@record_bp.route("/record/stop", methods=["POST"])
def stop_recording():
    """Stop the current recording and flush the clip to disk.

    Response::

        {"ok": true, "filename": "clip_YYYYMMDD_HHMMSS.mp4", "elapsed_s": 12.3}
    """
    global _recording, _writer, _clip_filename, _started_at

    with _lock:
        if not _recording:
            return jsonify({"ok": False, "error": "Not recording"}), 400

        filename = _clip_filename
        elapsed = time.monotonic() - (_started_at or time.monotonic())
        writer = _writer

        _recording = False
        _writer = None
        _clip_filename = None
        _started_at = None

    try:
        if writer is not None:
            writer.release()
        logger.info("Video recording stopped: %s (%.1f s)", filename, elapsed)
    except Exception as exc:
        logger.warning("Error releasing VideoWriter: %s", exc)

    return jsonify({"ok": True, "filename": filename, "elapsed_s": round(elapsed, 2)})


@record_bp.route("/record/status", methods=["GET"])
def recording_status():
    """Return current recording state.

    Response::

        {"recording": bool, "filename": str|null, "elapsed_s": float}
    """
    with _lock:
        recording = _recording
        filename = _clip_filename
        started = _started_at

    elapsed = (time.monotonic() - started) if (recording and started is not None) else 0.0
    return jsonify({
        "recording": recording,
        "filename": filename,
        "elapsed_s": round(elapsed, 2),
    })


@record_bp.route("/clips", methods=["GET"])
def list_clips():
    """List all saved video clips sorted by modification time (newest first).

    Response::

        {
          "clips": [
            {"filename": "clip_20240101_120000.mp4", "size_mb": 3.2,
             "created_at": "2024-01-01T12:00:00"},
            ...
          ]
        }
    """
    if not _clips_dir.exists():
        return jsonify({"clips": []})

    clips = []
    for f in sorted(_clips_dir.glob("*.mp4"), key=lambda x: x.stat().st_mtime, reverse=True):
        size_mb = f.stat().st_size / 1e6
        clips.append({
            "filename": f.name,
            "size_mb": round(size_mb, 2),
            "created_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        })
    return jsonify({"clips": clips})


@record_bp.route("/clips/<path:filename>", methods=["GET"])
def download_clip(filename: str):
    """Download a saved clip by filename.

    Returns 404 if the file does not exist.
    """
    # Sanitise: reject path traversal attempts.
    safe_name = Path(filename).name
    filepath = _clips_dir / safe_name
    if not filepath.exists() or not filepath.is_file():
        return jsonify({"error": f"Clip '{safe_name}' not found"}), 404

    return send_file(str(filepath.resolve()), mimetype="video/mp4", as_attachment=True)


@record_bp.route("/clips/<path:filename>", methods=["DELETE"])
def delete_clip(filename: str):
    """Delete a saved clip by filename.

    Returns 404 if the file does not exist.
    Response::

        {"ok": true, "filename": "clip_...mp4"}
    """
    safe_name = Path(filename).name
    filepath = _clips_dir / safe_name
    if not filepath.exists() or not filepath.is_file():
        return jsonify({"error": f"Clip '{safe_name}' not found"}), 404

    try:
        filepath.unlink()
        logger.info("Clip deleted: %s", safe_name)
        return jsonify({"ok": True, "filename": safe_name})
    except Exception as exc:
        logger.error("Failed to delete clip '%s': %s", safe_name, exc)
        return jsonify({"ok": False, "error": str(exc)}), 500
