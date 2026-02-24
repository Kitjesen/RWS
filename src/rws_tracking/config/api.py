"""API / 视频流配置。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VideoStreamConfig:
    enabled: bool = False
    jpeg_quality: int = 70
    max_fps: float = 30.0
    scale_factor: float = 1.0
    buffer_size: int = 3
    annotate_detections: bool = True
    annotate_tracks: bool = True
    annotate_crosshair: bool = True
    annotate_safety_zones: bool = False


# Backward-compat alias — remove after next major version
VideoStreamCfg = VideoStreamConfig
