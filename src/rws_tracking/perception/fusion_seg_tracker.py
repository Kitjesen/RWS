"""
FusionSegTracker: YOLO-Seg detection + FusionMOT tracking.
============================================================

Replaces the BoT-SORT-based YoloSegTracker with a fully self-contained
tracking pipeline:

    YOLO-Seg (raw detect, no built-in tracker)
        → OSNet Re-ID feature extraction
        → FusionMOT (multi-cue Hungarian matching + Kalman CA)
        → Track output

Kalman CA (6-state constant-acceleration) is now **embedded inside each
FusionMOT tracklet** — no external Kalman layer needed.  The Kalman
filter provides:

  * Parabolic position prediction during occlusion (vs old linear extrap)
  * Mahalanobis gating (uncertainty-aware matching radius)
  * Smoothed velocity & acceleration estimates in the Track output
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import cv2 as _cv2
import numpy as np

from ..types import BoundingBox, Track
from .fusion_mot import FusionMOT, FusionMOTConfig
from .reid_extractor import ReIDConfig, ReIDExtractor

logger = logging.getLogger(__name__)


class FusionSegTracker:
    """YOLO-Seg + FusionMOT (with internal Kalman CA) + OSNet.

    Parameters
    ----------
    model_path : str
        YOLO-Seg model weights (e.g. "yolo11n-seg.pt").
    confidence_threshold : float
        High-confidence detection threshold for Stage 1.
    low_confidence_threshold : float
        Low-confidence threshold for ByteTrack Stage 2.
    class_whitelist : optional
        Only track these COCO class names (e.g. ["person"]).
    device : str
        PyTorch device ("cuda:0", "cpu", "" for auto).
    img_size : int
        YOLO input size (longer side).
    reid_config : ReIDConfig
        Re-ID feature extraction configuration.
    mot_config : FusionMOTConfig
        Tracking algorithm configuration (includes kalman_config).
    """

    def __init__(
        self,
        model_path: str = "yolo11n-seg.pt",
        confidence_threshold: float = 0.35,
        low_confidence_threshold: float = 0.15,
        class_whitelist: Sequence[str] | None = None,
        device: str = "",
        img_size: int = 640,
        reid_config: ReIDConfig | None = None,
        mot_config: FusionMOTConfig | None = None,
    ) -> None:
        from ultralytics import YOLO  # type: ignore[import-untyped]

        self._model = YOLO(model_path)
        self._conf_high = confidence_threshold
        self._conf_low = low_confidence_threshold
        self._device = device
        self._img_size = img_size

        self._id_to_name: dict[int, str] = self._model.names
        self._allowed_ids: list[int] | None = None
        if class_whitelist is not None:
            name_map = {v.lower(): k for k, v in self._id_to_name.items()}
            self._allowed_ids = [
                name_map[n.lower()] for n in class_whitelist if n.lower() in name_map
            ]

        self._reid = ReIDExtractor(reid_config or ReIDConfig())

        mot_cfg = mot_config or FusionMOTConfig()
        mot_cfg.high_conf = confidence_threshold
        mot_cfg.low_conf = low_confidence_threshold
        self._mot = FusionMOT(mot_cfg, feature_dim=self._reid.feature_dim)

        self._first_seen: dict[int, float] = {}
        self._last_raw_results: list | None = None
        self._total_extractions = 0
        self._total_skips = 0

        logger.info(
            "FusionSegTracker ready  model=%s  reid=%s  device=%s  kalman=internal_CA",
            model_path,
            (reid_config or ReIDConfig()).backbone,
            device or "auto",
        )

    @property
    def last_raw_results(self) -> list | None:
        return self._last_raw_results

    @property
    def reid_stats(self) -> dict[str, int]:
        active = sum(1 for t in self._mot.active_tracks.values() if t.state == "confirmed")
        lost = sum(1 for t in self._mot.active_tracks.values() if t.state == "lost")
        return {
            "enabled": 1,
            "active": active,
            "lost": lost,
            "remaps": 0,
            "extractions": self._total_extractions,
            "skips": self._total_skips,
        }

    def detect_and_track(self, frame: np.ndarray, timestamp: float) -> list[Track]:
        """Run full pipeline: detect → extract features → FusionMOT(Kalman).

        Automatically extracts COCO-17 keypoints when the loaded model is a
        pose model (``result.keypoints`` is not None).  Keypoints are passed
        to FusionMOT so that hip center is used as the Kalman anchor and the
        skeleton proportion descriptor is included in the cost matrix
        (requires ``FusionMOTConfig.w_skeleton > 0``).
        """
        if not isinstance(frame, np.ndarray):
            return []

        results = self._model(
            source=frame,
            conf=self._conf_low,
            iou=0.45,
            imgsz=self._img_size,
            device=self._device or None,
            classes=self._allowed_ids,
            verbose=False,
        )
        self._last_raw_results = results

        all_bboxes: list[np.ndarray] = []
        all_confs: list[float] = []
        all_keypoints: list[np.ndarray] = []  # (17, 3) per detection: [x, y, vis]
        has_pose = False

        for result in results:
            boxes = result.boxes
            if boxes is None or len(boxes) == 0:
                continue
            xyxy = boxes.xyxy.cpu().numpy()
            confs = boxes.conf.cpu().numpy()

            # Pose model outputs result.keypoints; seg/detect models do not
            kpts_data = None
            if result.keypoints is not None:
                has_pose = True
                # shape: (M, 17, 3) with [x, y, visibility] per keypoint
                kpts_data = result.keypoints.data.cpu().numpy()

            for i in range(len(xyxy)):
                x1, y1, x2, y2 = xyxy[i]
                w, h = x2 - x1, y2 - y1
                if w <= 0 or h <= 0:
                    continue
                all_bboxes.append(np.array([x1, y1, w, h], dtype=np.float64))
                all_confs.append(float(confs[i]))
                if kpts_data is not None and i < len(kpts_data):
                    all_keypoints.append(kpts_data[i].astype(np.float64))  # (17, 3)

        N = len(all_bboxes)
        if N == 0:
            self._mot.update(np.empty((0, 4)), np.empty(0), None, timestamp)
            return []

        bboxes_arr = np.stack(all_bboxes)
        confs_arr = np.array(all_confs)

        # Build keypoints array — only when all detections have pose data
        keypoints_arr: np.ndarray | None = None
        if has_pose and len(all_keypoints) == N:
            keypoints_arr = np.stack(all_keypoints)  # (N, 17, 3)

        bbox_tuples = [(b[0], b[1], b[2], b[3]) for b in all_bboxes]
        features = self._reid.extract(frame, bbox_tuples)
        self._total_extractions += N

        mot_results = self._mot.update(
            bboxes_arr,
            confs_arr,
            features,
            timestamp,
            keypoints=keypoints_arr,
        )

        tracks: list[Track] = []
        for tid, bbox_xywh, conf in mot_results:
            if tid not in self._first_seen:
                self._first_seen[tid] = timestamp

            tracklet = self._mot.active_tracks.get(tid)
            vel = tracklet.kf.velocity if tracklet else (0.0, 0.0)
            acc = tracklet.kf.acceleration if tracklet else (0.0, 0.0)
            kf_pos = (
                tracklet.kf.position
                if tracklet
                else (
                    float(bbox_xywh[0] + bbox_xywh[2] / 2),
                    float(bbox_xywh[1] + bbox_xywh[3] / 2),
                )
            )

            tracks.append(
                Track(
                    track_id=tid,
                    bbox=BoundingBox(
                        x=float(bbox_xywh[0]),
                        y=float(bbox_xywh[1]),
                        w=float(bbox_xywh[2]),
                        h=float(bbox_xywh[3]),
                    ),
                    confidence=conf,
                    class_id="person",
                    first_seen_ts=self._first_seen[tid],
                    last_seen_ts=timestamp,
                    age_frames=tracklet.total_frames if tracklet else 1,
                    misses=tracklet.frames_since_update if tracklet else 0,
                    velocity_px_per_s=vel,
                    acceleration_px_per_s2=acc,
                    mask_center=kf_pos,
                )
            )

        # Purge first_seen for tracks that are fully deleted
        active_ids = set(self._mot.active_tracks.keys())
        stale = [k for k in self._first_seen if k not in active_ids]
        for k in stale:
            del self._first_seen[k]

        return tracks

    @staticmethod
    def _compute_mask_centroid(masks: object, idx: int) -> tuple[float, float] | None:
        if masks is None:
            return None
        try:
            mask_tensor = masks.data[idx].cpu().numpy()
            binary = (mask_tensor > 0.5).astype(np.uint8)
            M = _cv2.moments(binary)
            if M["m00"] < 1.0:
                return None
            mcx = M["m10"] / M["m00"]
            mcy = M["m01"] / M["m00"]
            orig_h, orig_w = masks.orig_shape
            mask_h, mask_w = mask_tensor.shape
            return (float(mcx * orig_w / mask_w), float(mcy * orig_h / mask_h))
        except (IndexError, AttributeError, _cv2.error):
            return None
