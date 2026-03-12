"""Session, lifecycle, and clip recording configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SessionConfig:
    """Mission session and audit log paths."""

    fire_cooldown_s: float = 3.0
    audit_log_path: str = "logs/audit.jsonl"
    telemetry_log_path: str = "logs/telemetry.jsonl"


@dataclass(frozen=True)
class LifecycleConfig:
    """Target lifecycle management parameters."""

    confirm_frames: int = 3
    archive_timeout_s: float = 10.0


@dataclass(frozen=True)
class ClipConfig:
    """Event clip (VideoRingBuffer) recording parameters."""

    buffer_duration_s: float = 10.0
    pre_event_s: float = 3.0
    post_event_s: float = 2.0
    output_dir: str = "logs/clips"
    fps: float = 30.0
