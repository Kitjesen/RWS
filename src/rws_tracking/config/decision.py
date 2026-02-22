"""决策层配置：威胁权重、交战策略。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThreatWeightsConfig:
    distance: float = 0.30
    velocity: float = 0.25
    class_threat: float = 0.20
    heading: float = 0.15
    size: float = 0.10


@dataclass(frozen=True)
class EngagementConfig:
    enabled: bool = False
    weights: ThreatWeightsConfig = ThreatWeightsConfig()
    strategy: str = "threat_first"
    max_engagement_range_m: float = 500.0
    min_threat_threshold: float = 0.1
    distance_decay_m: float = 50.0
    velocity_norm_px_s: float = 200.0
    target_height_m: float = 1.8
    sector_size_deg: float = 30.0
    # Minimum time (s) a target must remain LOCK+fire_authorized before the
    # engagement queue auto-advances to the next target.  Set to 0 to disable.
    engagement_dwell_time_s: float = 2.0
