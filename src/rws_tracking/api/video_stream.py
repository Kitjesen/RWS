"""视频流传输模块 — MJPEG / gRPC 帧流。

职责（单一）：
    将 pipeline 的视频帧（含标注叠加）编码后通过网络传输。

支持的传输方式：
    1. MJPEG over HTTP — 浏览器直接播放，兼容性最好
    2. gRPC 帧流      — 二进制帧流，延迟低，适合客户端程序
    3. WebSocket 帧流  — 浏览器低延迟方案（可选扩展）

帧处理流水线：
    原始帧 → 标注叠加 → 分辨率缩放 → JPEG 编码 → 网络传输

数据流向：
    Pipeline.step() 产出帧 → FrameBuffer (线程安全环形缓冲)
    → StreamServer 读取最新帧 → 编码传输
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Generator

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VideoStreamConfig:
    """视频流配置。

    Attributes
    ----------
    enabled : bool
        是否启用视频流。
    jpeg_quality : int
        JPEG 编码质量 (1–100)。
    max_fps : float
        最大推流帧率。
    scale_factor : float
        分辨率缩放比例 (0–1), 1.0 = 原始分辨率。
    buffer_size : int
        帧缓冲区大小。
    annotate_detections : bool
        是否叠加检测框。
    annotate_tracks : bool
        是否叠加跟踪信息。
    annotate_crosshair : bool
        是否叠加准星。
    annotate_safety_zones : bool
        是否叠加禁射区。
    """

    enabled: bool = False
    jpeg_quality: int = 70
    max_fps: float = 30.0
    scale_factor: float = 1.0
    buffer_size: int = 3
    annotate_detections: bool = True
    annotate_tracks: bool = True
    annotate_crosshair: bool = True
    annotate_safety_zones: bool = False


# ---------------------------------------------------------------------------
# 线程安全帧缓冲
# ---------------------------------------------------------------------------


class FrameBuffer:
    """线程安全的环形帧缓冲。

    生产者 (pipeline 线程) push 帧，
    消费者 (流媒体线程) get 最新帧。
    缓冲满时丢弃最旧帧（不阻塞生产者）。
    """

    def __init__(self, max_size: int = 3) -> None:
        self._buffer: list[tuple[np.ndarray, float]] = []
        self._max_size = max_size
        self._lock = threading.Lock()
        self._event = threading.Event()

    def push(self, frame: np.ndarray, timestamp: float) -> None:
        """推入新帧（线程安全, 非阻塞）。"""
        with self._lock:
            self._buffer.append((frame, timestamp))
            if len(self._buffer) > self._max_size:
                self._buffer.pop(0)
            self._event.set()

    def get_latest(self, timeout: float = 1.0) -> tuple[np.ndarray, float] | None:
        """获取最新帧（阻塞等待, 超时返回 None）。"""
        if not self._event.wait(timeout=timeout):
            return None

        with self._lock:
            if not self._buffer:
                self._event.clear()
                return None
            frame, ts = self._buffer[-1]
            self._event.clear()
            return frame.copy(), ts

    def put(self, frame: np.ndarray) -> None:
        """Alias for push() with timestamp=0.0."""
        self.push(frame, 0.0)

    def get(self) -> np.ndarray | None:
        """Dequeue oldest frame. Returns None if empty."""
        with self._lock:
            if not self._buffer:
                return None
            frame, _ = self._buffer.pop(0)
            return frame

    def latest(self) -> np.ndarray | None:
        """Return copy of latest frame without blocking. Returns None if empty."""
        with self._lock:
            if not self._buffer:
                return None
            frame, _ = self._buffer[-1]
            return frame.copy()

    def clear(self) -> None:
        with self._lock:
            self._buffer.clear()
            self._event.clear()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._buffer)


# ---------------------------------------------------------------------------
# 帧标注器
# ---------------------------------------------------------------------------


class FrameAnnotator:
    """帧标注叠加器。

    在视频帧上叠加：
    - 检测框 (绿色)
    - 跟踪 ID 和速度
    - 准星 (红色十字)
    - 禁射区 (红色半透明)
    - 系统状态文字
    """

    def __init__(self, config: VideoStreamConfig = VideoStreamConfig()) -> None:
        self._cfg = config
        self._cv2 = None

    def _ensure_cv2(self) -> None:
        if self._cv2 is None:
            import cv2
            self._cv2 = cv2

    def annotate(
        self,
        frame: np.ndarray,
        detections: list | None = None,
        tracks: list | None = None,
        selected_id: int | None = None,
        safety_zones: list | None = None,
        status_text: str = "",
    ) -> np.ndarray:
        """在帧上叠加标注。

        Parameters
        ----------
        frame : np.ndarray
            原始帧 (BGR)。
        detections : list, optional
            检测结果列表。
        tracks : list, optional
            Track 列表。
        selected_id : int, optional
            当前选中目标 ID。
        safety_zones : list, optional
            SafetyZone 列表。
        status_text : str
            状态文字。

        Returns
        -------
        np.ndarray
            标注后的帧。
        """
        self._ensure_cv2()
        cv2 = self._cv2
        annotated = frame.copy()
        h, w = annotated.shape[:2]

        # 准星
        if self._cfg.annotate_crosshair:
            cx, cy = w // 2, h // 2
            color = (0, 0, 255)  # 红色
            cv2.line(annotated, (cx - 20, cy), (cx + 20, cy), color, 1)
            cv2.line(annotated, (cx, cy - 20), (cx, cy + 20), color, 1)
            cv2.circle(annotated, (cx, cy), 5, color, 1)

        # 跟踪框
        if self._cfg.annotate_tracks and tracks:
            for track in tracks:
                bbox = track.bbox
                x1, y1 = int(bbox.x), int(bbox.y)
                x2, y2 = int(bbox.x + bbox.w), int(bbox.y + bbox.h)

                # 选中目标用黄色, 其他用绿色
                is_selected = track.track_id == selected_id
                color = (0, 255, 255) if is_selected else (0, 255, 0)
                thickness = 2 if is_selected else 1

                cv2.rectangle(annotated, (x1, y1), (x2, y2), color, thickness)

                label = f"ID:{track.track_id} {track.class_id} {track.confidence:.2f}"
                cv2.putText(
                    annotated, label, (x1, y1 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1,
                )

                # 速度向量
                if abs(track.velocity_px_per_s[0]) > 1 or abs(track.velocity_px_per_s[1]) > 1:
                    cx_t, cy_t = int(bbox.x + bbox.w / 2), int(bbox.y + bbox.h / 2)
                    vx, vy = track.velocity_px_per_s
                    scale = 0.3
                    ex = int(cx_t + vx * scale)
                    ey = int(cy_t + vy * scale)
                    cv2.arrowedLine(annotated, (cx_t, cy_t), (ex, ey), color, 1)

        # 状态文字
        if status_text:
            cv2.putText(
                annotated, status_text, (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1,
            )

        return annotated


# ---------------------------------------------------------------------------
# MJPEG 流生成器
# ---------------------------------------------------------------------------


class MJPEGStreamer:
    """MJPEG over HTTP 流生成器。

    用于 Flask/Starlette 的 StreamingResponse。

    用法 (Flask):
        @app.route('/video_feed')
        def video_feed():
            return Response(
                streamer.generate(),
                mimetype='multipart/x-mixed-replace; boundary=frame',
            )
    """

    def __init__(
        self,
        frame_buffer: FrameBuffer,
        config: VideoStreamConfig = VideoStreamConfig(),
    ) -> None:
        self._buffer = frame_buffer
        self._cfg = config
        self._cv2 = None

    def _ensure_cv2(self) -> None:
        if self._cv2 is None:
            import cv2
            self._cv2 = cv2

    def generate(self) -> Generator[bytes, None, None]:
        """生成 MJPEG 字节流。

        Yields
        ------
        bytes
            MIME multipart boundary + JPEG 数据。
        """
        self._ensure_cv2()
        cv2 = self._cv2

        min_interval = 1.0 / max(self._cfg.max_fps, 1.0)
        last_send = 0.0

        while True:
            result = self._buffer.get_latest(timeout=2.0)
            if result is None:
                continue

            frame, ts = result
            now = time.monotonic()
            if now - last_send < min_interval:
                continue

            # 缩放
            if 0 < self._cfg.scale_factor < 1.0:
                h, w = frame.shape[:2]
                new_w = int(w * self._cfg.scale_factor)
                new_h = int(h * self._cfg.scale_factor)
                frame = cv2.resize(frame, (new_w, new_h))

            # JPEG 编码
            encode_param = [cv2.IMWRITE_JPEG_QUALITY, self._cfg.jpeg_quality]
            success, encoded = cv2.imencode(".jpg", frame, encode_param)
            if not success:
                continue

            data = encoded.tobytes()
            last_send = now

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(data)).encode() + b"\r\n"
                b"\r\n" + data + b"\r\n"
            )


# ---------------------------------------------------------------------------
# gRPC 帧流辅助
# ---------------------------------------------------------------------------


class GrpcFrameEncoder:
    """gRPC 帧编码器。

    将 numpy 帧编码为 JPEG 字节, 供 gRPC StreamFrames RPC 使用。
    """

    def __init__(self, config: VideoStreamConfig = VideoStreamConfig()) -> None:
        self._cfg = config
        self._cv2 = None

    def _ensure_cv2(self) -> None:
        if self._cv2 is None:
            import cv2
            self._cv2 = cv2

    def encode(self, frame: np.ndarray, timestamp: float) -> dict:
        """编码单帧。

        Returns
        -------
        dict
            {"timestamp": float, "jpeg_data": bytes, "width": int, "height": int}
        """
        self._ensure_cv2()
        cv2 = self._cv2

        if 0 < self._cfg.scale_factor < 1.0:
            h, w = frame.shape[:2]
            new_w = int(w * self._cfg.scale_factor)
            new_h = int(h * self._cfg.scale_factor)
            frame = cv2.resize(frame, (new_w, new_h))

        h, w = frame.shape[:2]
        encode_param = [cv2.IMWRITE_JPEG_QUALITY, self._cfg.jpeg_quality]
        success, encoded = cv2.imencode(".jpg", frame, encode_param)

        if not success:
            return {"timestamp": timestamp, "jpeg_data": b"", "width": w, "height": h}

        return {
            "timestamp": timestamp,
            "jpeg_data": encoded.tobytes(),
            "width": w,
            "height": h,
        }
