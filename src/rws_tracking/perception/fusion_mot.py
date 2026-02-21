"""
FusionMOT: Multi-cue Fused Multi-Object Tracker.
==================================================

A self-contained MOT algorithm that replaces external trackers (BoT-SORT/
ByteTrack) with a unified cost matrix approach.  All association cues are
fused **before** the Hungarian algorithm runs, so the optimal global
assignment already accounts for appearance, motion, shape, and spatial
information — no post-hoc ID repair needed.

Design references:
    - Deep OC-SORT (ICASSP 2023): fused cost = IoU + α·appearance
    - ByteTrack (ECCV 2022): two-stage matching (high + low confidence)
    - Hybrid-SORT (AAAI 2024): weak cues (confidence state, height state)
    - DeconfuseTrack (CVPR 2024): occlusion-aware NMS + decomposed matching
    - OC-SORT (CVPR 2023): observation-centric momentum for lost tracks
    - MOTIP (CVPR 2025): multi-frame temporal context for ID prediction

Architecture::

    YOLO detect (raw)
         │
         ▼
    ┌─────────────────────────────┐
    │  Stage 1: High-conf dets    │  IoU + Appearance + Motion + Height
    │  vs ALL active tracks       │  → Hungarian assignment
    │  (fused cost matrix)        │
    └────────────┬────────────────┘
                 │ unmatched tracks
                 ▼
    ┌─────────────────────────────┐
    │  Stage 2: Low-conf dets     │  IoU-only (ByteTrack style)
    │  vs remaining tracks        │  → Hungarian assignment
    └────────────┬────────────────┘
                 │
                 ▼
    Kalman update matched tracks
    Init new tracks / retire lost
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment

logger = logging.getLogger(__name__)

_UNMATCHED = 1e6


@dataclass
class FusionMOTConfig:
    """Tuning knobs for the fused tracker."""

    # Detection thresholds
    high_conf: float = 0.35
    low_conf: float = 0.15

    # Cost matrix weights (Deep OC-SORT Eq.6 style)
    w_iou: float = 0.35
    w_appearance: float = 0.35
    w_motion: float = 0.20
    w_height: float = 0.10

    # Gating thresholds
    iou_gate: float = 0.05
    appearance_gate: float = 0.15
    motion_gate_px: float = 250.0

    # Track lifecycle
    confirm_frames: int = 2
    lost_patience: int = 3
    max_lost_frames: int = 60
    max_lost_seconds: float = 8.0

    # Feature bank
    feature_bank_size: int = 15
    ema_alpha: float = 0.90

    # ByteTrack Stage 2: IoU-only for low-conf
    stage2_iou_gate: float = 0.12

    # Lost track recovery (Stage 3)
    lost_motion_gate_multiplier: float = 3.0
    lost_appearance_gate: float = 0.10
    lost_match_threshold: float = 0.80


@dataclass
class _Tracklet:
    """Internal tracklet state."""

    track_id: int
    feature_ema: np.ndarray | None = None
    feature_bank: list = field(default_factory=list)
    bbox: np.ndarray = field(default_factory=lambda: np.zeros(4))  # x,y,w,h
    last_position: np.ndarray = field(default_factory=lambda: np.zeros(2))
    velocity: np.ndarray = field(default_factory=lambda: np.zeros(2))
    height_ema: float = 0.0
    confidence: float = 0.0
    state: str = "tentative"  # tentative → confirmed → lost → deleted
    frames_since_update: int = 0
    total_frames: int = 0
    last_ts: float = 0.0
    created_ts: float = 0.0
    observations: list = field(default_factory=list)  # OCM: [(cx, cy, ts)]


class FusionMOT:
    """Multi-Object Tracker with fused multi-cue cost matrix.

    Usage::

        tracker = FusionMOT(config, reid_extractor)

        # Each frame:
        detections = yolo_model(frame)  # raw detections
        tracks = tracker.update(detections, features, timestamp)
    """

    def __init__(self, config: FusionMOTConfig | None = None,
                 feature_dim: int = 512) -> None:
        self._cfg = config or FusionMOTConfig()
        self._feature_dim = feature_dim
        self._tracklets: dict[int, _Tracklet] = {}
        self._next_id = 1
        self._frame_count = 0

        logger.info("FusionMOT initialized  weights=(iou=%.2f, app=%.2f, "
                     "motion=%.2f, height=%.2f)  stage2_iou=%.2f",
                     self._cfg.w_iou, self._cfg.w_appearance,
                     self._cfg.w_motion, self._cfg.w_height,
                     self._cfg.stage2_iou_gate)

    @property
    def active_tracks(self) -> dict[int, _Tracklet]:
        return self._tracklets

    def update(
        self,
        bboxes: np.ndarray,
        confidences: np.ndarray,
        features: np.ndarray | None,
        timestamp: float,
    ) -> list[tuple[int, np.ndarray, float]]:
        """Run one frame of tracking.

        Parameters
        ----------
        bboxes : (N, 4) float array — [x, y, w, h] per detection
        confidences : (N,) float array
        features : (N, D) float array or None — appearance features
        timestamp : float

        Returns
        -------
        list of (track_id, bbox_xywh, confidence) for confirmed tracks
        """
        self._frame_count += 1
        dt = 0.033  # will be overridden

        if self._tracklets:
            any_t = next(iter(self._tracklets.values()))
            dt = max(timestamp - any_t.last_ts, 1e-3) if any_t.last_ts > 0 else 0.033

        # Predict step: advance all tracklets by velocity
        for t in self._tracklets.values():
            t.last_position = t.last_position + t.velocity * dt
            t.bbox[:2] = t.last_position - t.bbox[2:4] / 2

        N = len(bboxes)
        if N == 0:
            self._mark_unmatched_tracks(timestamp)
            self._cleanup(timestamp)
            return self._get_output(timestamp)

        # Split detections by confidence
        high_mask = confidences >= self._cfg.high_conf
        low_mask = (~high_mask) & (confidences >= self._cfg.low_conf)

        high_idx = np.where(high_mask)[0]
        low_idx = np.where(low_mask)[0]

        # Get active + lost tracklet IDs for matching
        track_ids = [tid for tid, t in self._tracklets.items()
                     if t.state in ("confirmed", "tentative", "lost")]

        matched_track_set: set[int] = set()
        matched_det_set: set[int] = set()

        # ═══ Stage 1: High-conf detections vs ALL tracks (full cost) ═══
        if len(high_idx) > 0 and len(track_ids) > 0:
            cost = self._build_cost_matrix(
                track_ids, bboxes[high_idx],
                features[high_idx] if features is not None else None,
            )
            t_matched, d_matched = self._hungarian_match(cost, threshold=0.70)

            for ti, di in zip(t_matched, d_matched):
                tid = track_ids[ti]
                det_i = high_idx[di]
                self._update_tracklet(
                    tid, bboxes[det_i], confidences[det_i],
                    features[det_i] if features is not None else None,
                    timestamp,
                )
                matched_track_set.add(tid)
                matched_det_set.add(int(det_i))

        # ═══ Stage 2: Low-conf detections vs UNMATCHED tracks (IoU only) ═══
        remaining_tracks = [tid for tid in track_ids
                           if tid not in matched_track_set]

        if len(low_idx) > 0 and len(remaining_tracks) > 0:
            cost_s2 = self._build_iou_cost(remaining_tracks, bboxes[low_idx])
            t_matched2, d_matched2 = self._hungarian_match(
                cost_s2, threshold=1.0 - self._cfg.stage2_iou_gate)

            for ti, di in zip(t_matched2, d_matched2):
                tid = remaining_tracks[ti]
                det_i = low_idx[di]
                self._update_tracklet(
                    tid, bboxes[det_i], confidences[det_i],
                    None,  # no appearance update for low-conf
                    timestamp,
                )
                matched_track_set.add(tid)
                matched_det_set.add(int(det_i))

        # ═══ Stage 3: Unmatched high-conf dets vs lost tracks (Re-ID recovery) ═══
        unmatched_high = [int(i) for i in high_idx if int(i) not in matched_det_set]
        lost_tracks = [tid for tid, t in self._tracklets.items()
                       if t.state == "lost" and tid not in matched_track_set]

        # Also include confirmed tracks that weren't matched (brief occlusion)
        patience_tracks = [tid for tid, t in self._tracklets.items()
                           if t.state == "confirmed"
                           and t.frames_since_update > 0
                           and tid not in matched_track_set]
        recovery_tracks = lost_tracks + patience_tracks

        if unmatched_high and recovery_tracks:
            uh_bboxes = bboxes[unmatched_high]
            uh_feats = features[unmatched_high] if features is not None else None
            cost_s3 = self._build_recovery_cost(
                recovery_tracks, uh_bboxes, uh_feats)
            t_m3, d_m3 = self._hungarian_match(
                cost_s3, threshold=self._cfg.lost_match_threshold)

            for ti, di in zip(t_m3, d_m3):
                tid = recovery_tracks[ti]
                det_i = unmatched_high[di]
                self._update_tracklet(
                    tid, bboxes[det_i], confidences[det_i],
                    features[det_i] if features is not None else None,
                    timestamp,
                )
                matched_track_set.add(tid)
                matched_det_set.add(det_i)

        # ═══ Init new tracks from unmatched high-conf detections ═══
        for i in high_idx:
            if int(i) not in matched_det_set:
                self._init_tracklet(
                    bboxes[i], confidences[i],
                    features[i] if features is not None else None,
                    timestamp,
                )

        # Mark unmatched tracks (with patience before declaring lost)
        for tid in track_ids:
            if tid not in matched_track_set:
                t = self._tracklets[tid]
                t.frames_since_update += 1
                if (t.state == "confirmed"
                        and t.frames_since_update > self._cfg.lost_patience):
                    t.state = "lost"

        self._cleanup(timestamp)
        return self._get_output(timestamp)

    # ------------------------------------------------------------------
    # Cost matrix construction
    # ------------------------------------------------------------------

    def _build_cost_matrix(
        self,
        track_ids: list[int],
        det_bboxes: np.ndarray,
        det_features: np.ndarray | None,
    ) -> np.ndarray:
        """Build fused cost matrix: (num_tracks, num_dets).

        cost = w_iou * (1 - IoU) + w_app * (1 - cosine) + w_motion * motion_dist + w_height * height_dist

        Gated entries are set to _UNMATCHED.
        """
        M = len(track_ids)
        N = len(det_bboxes)
        cost = np.full((M, N), _UNMATCHED, dtype=np.float64)

        cfg = self._cfg
        det_centers = det_bboxes[:, :2] + det_bboxes[:, 2:4] / 2  # (N, 2)
        det_heights = det_bboxes[:, 3]  # (N,)

        for i, tid in enumerate(track_ids):
            t = self._tracklets[tid]
            t_bbox = t.bbox  # (4,) x, y, w, h
            t_center = t.last_position  # (2,)
            t_height = t.height_ema if t.height_ema > 1.0 else t_bbox[3]

            for j in range(N):
                # --- IoU distance ---
                iou = self._iou(t_bbox, det_bboxes[j])
                if iou < cfg.iou_gate and t.state != "lost":
                    continue  # gate: skip if no spatial overlap (except lost)
                iou_cost = 1.0 - iou

                # --- Motion distance (Kalman-free: direct position match) ---
                dx = det_centers[j, 0] - t_center[0]
                dy = det_centers[j, 1] - t_center[1]
                dist = (dx * dx + dy * dy) ** 0.5
                gate_r = cfg.motion_gate_px
                if t.state == "lost":
                    lost_dt = max(0.033, 0.0)
                    gate_r *= (1.0 + t.frames_since_update * 0.5)
                if dist > gate_r:
                    continue  # gate: too far
                motion_cost = min(dist / max(gate_r, 1.0), 1.0)

                # --- Appearance distance ---
                app_cost = 0.5  # neutral if no features
                if det_features is not None and t.feature_ema is not None:
                    cos_sim = float(t.feature_ema @ det_features[j])
                    # Also check feature bank (best-of-K)
                    if t.feature_bank:
                        bank_sims = [float(f @ det_features[j])
                                     for f, _, _ in t.feature_bank[-cfg.feature_bank_size:]]
                        bank_best = max(bank_sims)
                        cos_sim = max(cos_sim, 0.7 * cos_sim + 0.3 * bank_best)

                    if cos_sim < cfg.appearance_gate and t.state != "lost":
                        continue  # gate: appearance too different
                    app_cost = (1.0 - cos_sim) / 2.0  # map [-1,1] → [0,1]

                # --- Height distance (Hybrid-SORT weak cue) ---
                h_cost = 0.0
                if t_height > 1.0 and det_heights[j] > 1.0:
                    h_ratio = min(t_height, det_heights[j]) / max(t_height, det_heights[j])
                    h_cost = 1.0 - h_ratio

                # --- Fuse ---
                total = (cfg.w_iou * iou_cost
                         + cfg.w_appearance * app_cost
                         + cfg.w_motion * motion_cost
                         + cfg.w_height * h_cost)
                cost[i, j] = total

        return cost

    def _build_recovery_cost(
        self,
        track_ids: list[int],
        det_bboxes: np.ndarray,
        det_features: np.ndarray | None,
    ) -> np.ndarray:
        """Cost matrix for lost track recovery (Stage 3).

        Compared to Stage 1:
        - Much wider motion gate (lost tracks may have drifted)
        - Appearance-dominant weighting (motion is unreliable for lost tracks)
        - Feature bank matching (best-of-K across temporal history)
        """
        M = len(track_ids)
        N = len(det_bboxes)
        cost = np.full((M, N), _UNMATCHED, dtype=np.float64)

        cfg = self._cfg
        det_centers = det_bboxes[:, :2] + det_bboxes[:, 2:4] / 2
        det_heights = det_bboxes[:, 3]

        for i, tid in enumerate(track_ids):
            t = self._tracklets[tid]
            t_center = t.last_position
            t_height = t.height_ema if t.height_ema > 1.0 else t.bbox[3]
            lost_frames = t.frames_since_update

            for j in range(N):
                # Wider motion gate for lost tracks
                dx = det_centers[j, 0] - t_center[0]
                dy = det_centers[j, 1] - t_center[1]
                dist = (dx * dx + dy * dy) ** 0.5
                gate_r = cfg.motion_gate_px * cfg.lost_motion_gate_multiplier
                gate_r *= (1.0 + lost_frames * 0.3)
                if dist > gate_r:
                    continue
                motion_cost = min(dist / max(gate_r, 1.0), 1.0)

                # Appearance matching with feature bank
                app_cost = 0.5
                if det_features is not None and t.feature_ema is not None:
                    cos_sim = float(t.feature_ema @ det_features[j])
                    # Bank matching: best of K
                    if t.feature_bank:
                        bank_sims = [float(f @ det_features[j])
                                     for f, _, _ in t.feature_bank]
                        bank_best = max(bank_sims)
                        cos_sim = max(cos_sim, bank_best)

                    if cos_sim < cfg.lost_appearance_gate:
                        continue
                    app_cost = (1.0 - cos_sim) / 2.0

                # Height
                h_cost = 0.0
                if t_height > 1.0 and det_heights[j] > 1.0:
                    h_ratio = min(t_height, det_heights[j]) / max(t_height, det_heights[j])
                    h_cost = 1.0 - h_ratio

                # Lost recovery: appearance-dominant weighting
                total = (0.15 * motion_cost
                         + 0.65 * app_cost
                         + 0.10 * h_cost
                         + 0.10 * (1.0 - self._iou(t.bbox, det_bboxes[j])))
                cost[i, j] = total

        return cost

    def _build_iou_cost(self, track_ids: list[int],
                        det_bboxes: np.ndarray) -> np.ndarray:
        """IoU-only cost matrix for ByteTrack Stage 2."""
        M = len(track_ids)
        N = len(det_bboxes)
        cost = np.full((M, N), _UNMATCHED, dtype=np.float64)

        for i, tid in enumerate(track_ids):
            t_bbox = self._tracklets[tid].bbox
            for j in range(N):
                iou = self._iou(t_bbox, det_bboxes[j])
                if iou > self._cfg.stage2_iou_gate:
                    cost[i, j] = 1.0 - iou

        return cost

    @staticmethod
    def _hungarian_match(cost: np.ndarray,
                         threshold: float) -> tuple[list[int], list[int]]:
        """Run Hungarian algorithm with gating threshold."""
        if cost.size == 0:
            return [], []

        row_idx, col_idx = linear_sum_assignment(cost)
        t_matched: list[int] = []
        d_matched: list[int] = []

        for r, c in zip(row_idx, col_idx):
            if cost[r, c] < threshold:
                t_matched.append(int(r))
                d_matched.append(int(c))

        return t_matched, d_matched

    # ------------------------------------------------------------------
    # Tracklet lifecycle
    # ------------------------------------------------------------------

    def _init_tracklet(self, bbox: np.ndarray, conf: float,
                       feat: np.ndarray | None, ts: float) -> int:
        tid = self._next_id
        self._next_id += 1
        center = bbox[:2] + bbox[2:4] / 2

        t = _Tracklet(
            track_id=tid,
            bbox=bbox.copy(),
            last_position=center.copy(),
            velocity=np.zeros(2),
            height_ema=float(bbox[3]),
            confidence=conf,
            state="tentative",
            frames_since_update=0,
            total_frames=1,
            last_ts=ts,
            created_ts=ts,
            observations=[(float(center[0]), float(center[1]), ts)],
        )

        if feat is not None:
            f = feat.copy()
            n = np.linalg.norm(f)
            if n > 1e-6:
                f /= n
            t.feature_ema = f
            t.feature_bank = [(f.copy(), conf, ts)]

        self._tracklets[tid] = t
        return tid

    def _update_tracklet(self, tid: int, bbox: np.ndarray, conf: float,
                         feat: np.ndarray | None, ts: float) -> None:
        t = self._tracklets[tid]
        center = bbox[:2] + bbox[2:4] / 2
        dt = max(ts - t.last_ts, 1e-3)

        # Velocity from position delta (smoothed)
        new_vel = (center - t.last_position) / dt
        alpha_v = 0.7
        t.velocity = alpha_v * t.velocity + (1.0 - alpha_v) * new_vel

        t.bbox = bbox.copy()
        t.last_position = center.copy()
        t.confidence = conf
        t.frames_since_update = 0
        t.total_frames += 1
        t.last_ts = ts

        # Height EMA (Hybrid-SORT stable weak cue)
        if bbox[3] > 1.0:
            t.height_ema = 0.9 * t.height_ema + 0.1 * float(bbox[3])

        # OCM: store observations
        t.observations.append((float(center[0]), float(center[1]), ts))
        if len(t.observations) > 10:
            t.observations = t.observations[-10:]

        # Appearance update (Dynamic Appearance EMA)
        if feat is not None and t.feature_ema is not None:
            f = feat.copy()
            n = np.linalg.norm(f)
            if n > 1e-6:
                f /= n
            # Confidence-modulated alpha (Deep OC-SORT)
            sigma = 0.4
            if conf > sigma:
                a = 0.9 + 0.1 * (1.0 - (conf - sigma) / (1.0 - sigma))
            else:
                a = 1.0  # reject low-confidence features
            t.feature_ema = a * t.feature_ema + (1.0 - a) * f
            en = np.linalg.norm(t.feature_ema)
            if en > 1e-6:
                t.feature_ema /= en

            # Feature bank
            if conf > sigma:
                t.feature_bank.append((f.copy(), conf, ts))
                if len(t.feature_bank) > self._cfg.feature_bank_size:
                    t.feature_bank = t.feature_bank[-self._cfg.feature_bank_size:]
        elif feat is not None and t.feature_ema is None:
            f = feat.copy()
            n = np.linalg.norm(f)
            if n > 1e-6:
                f /= n
            t.feature_ema = f
            t.feature_bank = [(f.copy(), conf, ts)]

        # State transition
        if t.state == "tentative" and t.total_frames >= self._cfg.confirm_frames:
            t.state = "confirmed"
        elif t.state == "lost":
            t.state = "confirmed"
            logger.info("Track %d recovered from lost state", tid)

    def _mark_unmatched_tracks(self, timestamp: float) -> None:
        for t in self._tracklets.values():
            if t.state in ("confirmed", "tentative"):
                t.frames_since_update += 1
                if (t.state == "confirmed"
                        and t.frames_since_update > self._cfg.lost_patience):
                    t.state = "lost"

    def _cleanup(self, timestamp: float) -> None:
        """Remove dead tracklets."""
        to_delete: list[int] = []
        cfg = self._cfg

        for tid, t in self._tracklets.items():
            if t.state == "tentative" and t.frames_since_update > 2:
                to_delete.append(tid)
            elif t.state == "lost":
                if t.frames_since_update > cfg.max_lost_frames:
                    to_delete.append(tid)
                elif (timestamp - t.last_ts) > cfg.max_lost_seconds:
                    to_delete.append(tid)

        for tid in to_delete:
            del self._tracklets[tid]

    def _get_output(self, timestamp: float) -> list[tuple[int, np.ndarray, float]]:
        """Return confirmed tracks (including those within patience window)."""
        results: list[tuple[int, np.ndarray, float]] = []
        for t in self._tracklets.values():
            if t.state == "confirmed":
                if t.frames_since_update <= self._cfg.lost_patience:
                    results.append((t.track_id, t.bbox.copy(), t.confidence))
        return results

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    @staticmethod
    def _iou(a: np.ndarray, b: np.ndarray) -> float:
        """IoU for (x, y, w, h) boxes."""
        ax1, ay1, aw, ah = a[0], a[1], a[2], a[3]
        bx1, by1, bw, bh = b[0], b[1], b[2], b[3]
        ax2, ay2 = ax1 + aw, ay1 + ah
        bx2, by2 = bx1 + bw, by1 + bh
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        iw = max(0.0, ix2 - ix1)
        ih = max(0.0, iy2 - iy1)
        inter = iw * ih
        union = aw * ah + bw * bh - inter
        return float(inter / union) if union > 1e-6 else 0.0

    def reset(self) -> None:
        """Clear all state."""
        self._tracklets.clear()
        self._next_id = 1
        self._frame_count = 0
