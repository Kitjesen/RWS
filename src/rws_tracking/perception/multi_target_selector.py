"""Multi-target selector implementation using weighted scoring."""

from __future__ import annotations

import logging

from ..config import SelectorConfig
from ..types import TargetObservation, Track

logger = logging.getLogger(__name__)


class WeightedMultiTargetSelector:
    """Selects multiple targets using weighted scoring.

    Scores each track based on:
    - Confidence
    - Size (bbox area)
    - Distance from center
    - Age (track stability)
    - Class preference

    Returns top N targets sorted by score.
    """

    def __init__(
        self,
        frame_width: int,
        frame_height: int,
        config: SelectorConfig | None = None,
    ):
        self._w = frame_width
        self._h = frame_height
        self._cfg = config if config is not None else SelectorConfig()
        self._last_selected_ids: list[int] = []

    def select_multiple(
        self, tracks: list[Track], timestamp: float, max_targets: int = 3
    ) -> list[TargetObservation]:
        """Select up to max_targets best targets.

        Parameters
        ----------
        tracks : List[Track]
            Available tracked objects
        timestamp : float
            Current timestamp
        max_targets : int
            Maximum number of targets to return

        Returns
        -------
        List[TargetObservation]
            Ranked list of targets (best first)
        """
        if not tracks:
            self._last_selected_ids = []
            return []

        # Score all tracks
        scored = []
        for track in tracks:
            score = self._compute_score(track, timestamp)
            scored.append((score, track))

        # Sort by score (descending)
        scored.sort(key=lambda x: x[0], reverse=True)

        # Take top N
        selected = []
        for _score, track in scored[:max_targets]:
            obs = TargetObservation(
                timestamp=timestamp,
                track_id=track.track_id,
                bbox=track.bbox,
                confidence=track.confidence,
                class_id=track.class_id,
                velocity_px_per_s=track.velocity_px_per_s,
                acceleration_px_per_s2=track.acceleration_px_per_s2,
                mask_center=track.mask_center,
            )
            selected.append(obs)

        # Update tracking
        self._last_selected_ids = [obs.track_id for obs in selected]

        logger.debug(
            "Selected %d targets: %s (scores: %s)",
            len(selected),
            [obs.track_id for obs in selected],
            [f"{score:.2f}" for score, _ in scored[:max_targets]],
        )

        return selected

    # Backwards-compatible alias
    def select(self, tracks: list[Track], timestamp: float, max_targets: int = 3) -> list[TargetObservation]:
        return self.select_multiple(tracks, timestamp, max_targets=max_targets)

    def _compute_score(self, track: Track, timestamp: float) -> float:
        """Compute weighted score for a track."""
        cx, cy = track.bbox.center
        area = track.bbox.area

        # 1. Confidence weight
        conf_score = track.confidence

        # 2. Size weight (normalized)
        max_area = self._w * self._h
        size_score = min(area / max_area, 1.0)

        # 3. Center distance weight (closer to center = higher score)
        dx = (cx - self._w / 2) / (self._w / 2)
        dy = (cy - self._h / 2) / (self._h / 2)
        dist = (dx**2 + dy**2) ** 0.5
        center_score = max(0.0, 1.0 - dist)

        # 4. Age weight (older tracks = more stable)
        age_norm = min(track.age_frames / self._cfg.age_norm_frames, 1.0)
        age_score = age_norm

        # 5. Class preference
        preferred = self._cfg.preferred_classes or {}
        class_bonus = preferred.get(track.class_id, 0.5)

        # 6. Continuity bonus (was selected before)
        continuity_bonus = 1.2 if track.track_id in self._last_selected_ids else 1.0

        # Weighted combination using SelectorWeights
        weights = self._cfg.weights
        score = (
            conf_score * weights.confidence
            + size_score * weights.size
            + center_score * weights.center_proximity
            + age_score * weights.track_age
            + class_bonus * weights.class_weight
        ) * continuity_bonus

        return score
