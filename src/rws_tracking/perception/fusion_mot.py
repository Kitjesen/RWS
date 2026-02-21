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

from ..algebra.kalman2d import CentroidKalmanCA, KalmanCAConfig

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
    use_mahalanobis: bool = True
    mahalanobis_sigma: float = 6.0
    min_motion_gate_px: float = 80.0

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

    # Kalman filter
    kalman_config: KalmanCAConfig = field(default_factory=KalmanCAConfig)


class _Tracklet:
    """Internal tracklet state with embedded Kalman CA filter."""

    __slots__ = (
        "track_id", "kf", "feature_ema", "feature_bank", "bbox",
        "height_ema", "confidence", "state", "frames_since_update",
        "total_frames", "last_ts", "created_ts",
    )

    def __init__(self, track_id: int, cx: float, cy: float,
                 kalman_cfg: KalmanCAConfig) -> None:
        self.track_id = track_id
        self.kf = CentroidKalmanCA(cx0=cx, cy0=cy, config=kalman_cfg)
        self.feature_ema: np.ndarray | None = None
        self.feature_bank: list = []
        self.bbox = np.zeros(4, dtype=np.float64)  # x, y, w, h
        self.height_ema: float = 0.0
        self.confidence: float = 0.0
        self.state: str = "tentative"
        self.frames_since_update: int = 0
        self.total_frames: int = 0
        self.last_ts: float = 0.0
        self.created_ts: float = 0.0

    @property
    def position(self) -> np.ndarray:
        """Kalman-filtered position (cx, cy)."""
        p = self.kf.position
        return np.array([p[0], p[1]], dtype=np.float64)

    @property
    def velocity(self) -> np.ndarray:
        """Kalman-filtered velocity (vx, vy) in px/s."""
        v = self.kf.velocity
        return np.array([v[0], v[1]], dtype=np.float64)

    @property
    def pos_covariance(self) -> np.ndarray:
        """2x2 position covariance from Kalman state."""
        P = self.kf._P
        return P[:2, :2].copy()

    def predicted_bbox(self) -> np.ndarray:
        """Bbox with Kalman-predicted center, preserving last w/h."""
        pos = self.position
        w, h = self.bbox[2], self.bbox[3]
        return np.array([pos[0] - w / 2, pos[1] - h / 2, w, h],
                        dtype=np.float64)


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
        self._last_global_ts: float = 0.0

        logger.info("FusionMOT initialized  weights=(iou=%.2f, app=%.2f, "
                     "motion=%.2f, height=%.2f)  kalman=CA(6-state)  "
                     "mahalanobis=%s(σ=%.1f)",
                     self._cfg.w_iou, self._cfg.w_appearance,
                     self._cfg.w_motion, self._cfg.w_height,
                     self._cfg.use_mahalanobis, self._cfg.mahalanobis_sigma)

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
        dt = max(timestamp - self._last_global_ts, 1e-3) if self._last_global_ts > 0 else 0.033
        self._last_global_ts = timestamp

        # Kalman predict: advance ALL tracklets using CA model (parabolic)
        for t in self._tracklets.values():
            t.kf.predict(dt)
            # Sync bbox position from Kalman state
            pos = t.position
            t.bbox[0] = pos[0] - t.bbox[2] / 2
            t.bbox[1] = pos[1] - t.bbox[3] / 2

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
        """Build fused cost matrix using Kalman-predicted positions.

        Motion distance uses **Mahalanobis distance** when enabled: the
        Kalman covariance provides an uncertainty-aware gate that adapts
        per-track — a track with high uncertainty (just initialized or
        recovering) gets a wider gate automatically, while a well-tracked
        target has a tight gate that rejects false matches.

        cost = w_iou·(1-IoU) + w_app·(1-cosine)/2 + w_motion·mahal_norm + w_height·h_diff
        """
        M = len(track_ids)
        N = len(det_bboxes)
        cost = np.full((M, N), _UNMATCHED, dtype=np.float64)

        cfg = self._cfg
        det_centers = det_bboxes[:, :2] + det_bboxes[:, 2:4] / 2
        det_heights = det_bboxes[:, 3]

        for i, tid in enumerate(track_ids):
            t = self._tracklets[tid]
            t_pred_bbox = t.predicted_bbox()
            t_center = t.position
            t_height = t.height_ema if t.height_ema > 1.0 else t.bbox[3]

            # Precompute inverse covariance for Mahalanobis
            if cfg.use_mahalanobis:
                cov = t.pos_covariance
                cov_reg = cov + np.eye(2) * 1e-4
                try:
                    cov_inv = np.linalg.inv(cov_reg)
                except np.linalg.LinAlgError:
                    cov_inv = np.eye(2) / (cfg.motion_gate_px ** 2)
            else:
                cov_inv = None

            for j in range(N):
                # --- IoU distance (using Kalman-predicted bbox) ---
                iou = self._iou(t_pred_bbox, det_bboxes[j])
                if iou < cfg.iou_gate and t.state != "lost":
                    continue
                iou_cost = 1.0 - iou

                # --- Motion distance (Kalman-predicted center) ---
                delta = det_centers[j] - t_center
                eucl_dist = float(np.linalg.norm(delta))
                if cov_inv is not None:
                    mahal_sq = float(delta @ cov_inv @ delta)
                    mahal_ok = mahal_sq <= cfg.mahalanobis_sigma ** 2
                    pixel_ok = eucl_dist <= cfg.min_motion_gate_px
                    if not (mahal_ok or pixel_ok) and t.state != "lost":
                        continue
                    motion_cost = min(mahal_sq ** 0.5 / cfg.mahalanobis_sigma, 1.0)
                    if pixel_ok and not mahal_ok:
                        motion_cost = min(eucl_dist / cfg.motion_gate_px, 1.0)
                else:
                    gate_r = cfg.motion_gate_px
                    if t.state == "lost":
                        gate_r *= (1.0 + t.frames_since_update * 0.5)
                    if eucl_dist > gate_r:
                        continue
                    motion_cost = min(eucl_dist / max(gate_r, 1.0), 1.0)

                # --- Appearance distance ---
                app_cost = 0.5
                if det_features is not None and t.feature_ema is not None:
                    cos_sim = float(t.feature_ema @ det_features[j])
                    if t.feature_bank:
                        bank_sims = [float(f @ det_features[j])
                                     for f, _, _ in t.feature_bank[-cfg.feature_bank_size:]]
                        bank_best = max(bank_sims)
                        cos_sim = max(cos_sim, 0.7 * cos_sim + 0.3 * bank_best)
                    if cos_sim < cfg.appearance_gate and t.state != "lost":
                        continue
                    app_cost = (1.0 - cos_sim) / 2.0

                # --- Height distance (Hybrid-SORT) ---
                h_cost = 0.0
                if t_height > 1.0 and det_heights[j] > 1.0:
                    h_ratio = min(t_height, det_heights[j]) / max(t_height, det_heights[j])
                    h_cost = 1.0 - h_ratio

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

        Uses Kalman-predicted position (which keeps drifting forward even
        during occlusion thanks to the CA model), with a much wider
        Mahalanobis gate — lost tracks accumulate covariance, so the gate
        widens naturally.
        """
        M = len(track_ids)
        N = len(det_bboxes)
        cost = np.full((M, N), _UNMATCHED, dtype=np.float64)

        cfg = self._cfg
        det_centers = det_bboxes[:, :2] + det_bboxes[:, 2:4] / 2
        det_heights = det_bboxes[:, 3]

        for i, tid in enumerate(track_ids):
            t = self._tracklets[tid]
            t_center = t.position  # Kalman-predicted even when lost
            t_height = t.height_ema if t.height_ema > 1.0 else t.bbox[3]

            for j in range(N):
                delta = det_centers[j] - t_center
                dist = float(np.linalg.norm(delta))
                gate_r = cfg.motion_gate_px * cfg.lost_motion_gate_multiplier
                gate_r *= (1.0 + t.frames_since_update * 0.3)
                if dist > gate_r:
                    continue
                motion_cost = min(dist / max(gate_r, 1.0), 1.0)

                app_cost = 0.5
                if det_features is not None and t.feature_ema is not None:
                    cos_sim = float(t.feature_ema @ det_features[j])
                    if t.feature_bank:
                        bank_sims = [float(f @ det_features[j])
                                     for f, _, _ in t.feature_bank]
                        bank_best = max(bank_sims)
                        cos_sim = max(cos_sim, bank_best)
                    if cos_sim < cfg.lost_appearance_gate:
                        continue
                    app_cost = (1.0 - cos_sim) / 2.0

                h_cost = 0.0
                if t_height > 1.0 and det_heights[j] > 1.0:
                    h_ratio = min(t_height, det_heights[j]) / max(t_height, det_heights[j])
                    h_cost = 1.0 - h_ratio

                pred_bbox = t.predicted_bbox()
                total = (0.15 * motion_cost
                         + 0.65 * app_cost
                         + 0.10 * h_cost
                         + 0.10 * (1.0 - self._iou(pred_bbox, det_bboxes[j])))
                cost[i, j] = total

        return cost

    def _build_iou_cost(self, track_ids: list[int],
                        det_bboxes: np.ndarray) -> np.ndarray:
        """IoU-only cost matrix for ByteTrack Stage 2 (Kalman-predicted bboxes)."""
        M = len(track_ids)
        N = len(det_bboxes)
        cost = np.full((M, N), _UNMATCHED, dtype=np.float64)

        for i, tid in enumerate(track_ids):
            pred_bbox = self._tracklets[tid].predicted_bbox()
            for j in range(N):
                iou = self._iou(pred_bbox, det_bboxes[j])
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
            cx=float(center[0]),
            cy=float(center[1]),
            kalman_cfg=self._cfg.kalman_config,
        )
        t.bbox = bbox.copy()
        t.height_ema = float(bbox[3])
        t.confidence = conf
        t.state = "tentative"
        t.total_frames = 1
        t.last_ts = ts
        t.created_ts = ts

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

        # Kalman measurement update (fuses position observation into state)
        t.kf.update(float(center[0]), float(center[1]))

        # Store observed bbox (w/h from detection, position from Kalman)
        t.bbox = bbox.copy()
        t.confidence = conf
        t.frames_since_update = 0
        t.total_frames += 1
        t.last_ts = ts

        # Height EMA (Hybrid-SORT stable weak cue)
        if bbox[3] > 1.0:
            t.height_ema = 0.9 * t.height_ema + 0.1 * float(bbox[3])

        # Appearance update (Dynamic Appearance EMA, Deep OC-SORT)
        if feat is not None and t.feature_ema is not None:
            f = feat.copy()
            n = np.linalg.norm(f)
            if n > 1e-6:
                f /= n
            sigma = 0.4
            if conf > sigma:
                a = 0.9 + 0.1 * (1.0 - (conf - sigma) / (1.0 - sigma))
            else:
                a = 1.0
            t.feature_ema = a * t.feature_ema + (1.0 - a) * f
            en = np.linalg.norm(t.feature_ema)
            if en > 1e-6:
                t.feature_ema /= en

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
        """Return confirmed tracks with Kalman-smoothed bboxes.

        During patience frames (no measurement yet), the Kalman CA model
        provides parabolic extrapolation — much more accurate than the
        old linear velocity × dt.
        """
        results: list[tuple[int, np.ndarray, float]] = []
        for t in self._tracklets.values():
            if t.state == "confirmed":
                if t.frames_since_update <= self._cfg.lost_patience:
                    results.append((t.track_id, t.predicted_bbox(), t.confidence))
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
        self._last_global_ts = 0.0
