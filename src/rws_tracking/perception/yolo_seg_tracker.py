"""
YoloSegTracker: YOLO11-Seg + BoT-SORT combined detection & tracking.
=====================================================================

Responsibilities (single):
    - Run YOLO-Seg inference with built-in BoT-SORT/ByteTrack tracking.
    - Output Track list with stable IDs, Kalman-smoothed bboxes, mask centroids.
    - Replaces separate YoloDetector + SimpleIoUTracker for production use.

Key features:
    - BoT-SORT maintains stable track IDs with re-identification.
    - Instance segmentation masks give pixel-tight contours (no oversized boxes).
    - Per-track **Constant-Acceleration Kalman filter** on mask centroid:
      smooth position, robust velocity, estimated acceleration, and
      parabolic inter-frame prediction for curved trajectory at low FPS.
    - cv2.moments for sub-pixel precise centroid computation.
    - Single model.track() call — simpler and faster than two-step pipeline.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Union

import cv2 as _cv2
import numpy as np

from ..algebra.kalman2d import (
    CentroidKalman2D,
    CentroidKalmanCA,
    KalmanCAConfig,
    KalmanConfig,
)
from ..types import BoundingBox, Track

logger = logging.getLogger(__name__)

# Type alias: either CV or CA filter
_KalmanFilter = Union[CentroidKalman2D, CentroidKalmanCA]


class YoloSegTracker:
    """
    Combined YOLO-Seg detection + BoT-SORT tracking in one call.

    Each detected track maintains its own Kalman filter that fuses raw mask
    centroids into a smooth (position, velocity[, acceleration]) estimate.

    Parameters
    ----------
    model_path : str
        Path to a seg model weight (e.g. ``"yolo11n-seg.pt"``).
    confidence_threshold : float
        Detections below this confidence are discarded.
    nms_iou_threshold : float
        IoU threshold for NMS.
    tracker : str
        Tracker config name: ``"botsort.yaml"`` (default) or ``"bytetrack.yaml"``.
    class_whitelist : optional sequence of class names
        If provided, only these COCO class names are kept.
    device : str
        ``"cuda:0"``, ``"cpu"``, or ``""`` for auto.
    img_size : int
        Input image size (longer side).
    kalman_config : KalmanCAConfig or KalmanConfig
        Pass ``KalmanCAConfig`` (default) to use the 6-state Constant-Acceleration
        model, or ``KalmanConfig`` for the 4-state Constant-Velocity model.
    """

    def __init__(
        self,
        model_path: str = "yolo11n-seg.pt",
        confidence_threshold: float = 0.40,
        nms_iou_threshold: float = 0.45,
        tracker: str = "botsort.yaml",
        class_whitelist: Sequence[str] | None = None,
        device: str = "",
        img_size: int = 640,
        kalman_config: KalmanCAConfig | KalmanConfig | None = None,
    ) -> None:
        from ultralytics import YOLO  # type: ignore[import-untyped]

        self._model = YOLO(model_path)
        self._conf = confidence_threshold
        self._iou = nms_iou_threshold
        self._tracker = tracker
        self._device = device
        self._img_size = img_size

        self._id_to_name: dict[int, str] = self._model.names
        self._allowed_ids: list[int] | None = None
        if class_whitelist is not None:
            name_lower_map = {v.lower(): k for k, v in self._id_to_name.items()}
            self._allowed_ids = [
                name_lower_map[n.lower()] for n in class_whitelist if n.lower() in name_lower_map
            ]
            if not self._allowed_ids:
                logger.warning(
                    "class_whitelist %s matched no model classes; detections will be empty.",
                    class_whitelist,
                )

        # Kalman filter configuration
        self._kalman_cfg = kalman_config or KalmanCAConfig()
        self._use_ca = isinstance(self._kalman_cfg, KalmanCAConfig)
        self._filters: dict[int, _KalmanFilter] = {}
        self._filter_last_seen: dict[int, float] = {}
        self._first_seen: dict[int, float] = {}
        self._last_ts: float = 0.0

        # Cache last raw ultralytics results (for visualization)
        self._last_raw_results: list | None = None

        model_name = "CA (6-state)" if self._use_ca else "CV (4-state)"
        logger.info(
            "YoloSegTracker ready  model=%s  tracker=%s  conf=%.2f  "
            "kalman=%s  whitelist=%s  device=%s",
            model_path,
            tracker,
            self._conf,
            model_name,
            class_whitelist,
            device or "auto",
        )

    @property
    def last_raw_results(self) -> list | None:
        """Last raw ultralytics results (for visualization / debug)."""
        return self._last_raw_results

    @property
    def filters(self) -> dict[int, _KalmanFilter]:
        """Per-track Kalman filters (read-only access for visualization)."""
        return self._filters

    # ------------------------------------------------------------------
    # Public API — matches the CombinedTracker protocol
    # ------------------------------------------------------------------

    def detect_and_track(self, frame: object, timestamp: float) -> list[Track]:
        """
        Run YOLO-Seg + BoT-SORT on a single BGR frame.

        Returns a list of ``Track`` objects with:
          - Stable ``track_id`` from BoT-SORT.
          - ``mask_center`` from Kalman-filtered centroid (smooth & predicted).
          - ``velocity_px_per_s`` from Kalman state.
        """
        if not isinstance(frame, np.ndarray):
            logger.warning("YoloSegTracker received non-ndarray frame; returning empty.")
            return []

        # ── Kalman predict step for ALL existing tracks ──
        dt = max(timestamp - self._last_ts, 1e-3) if self._last_ts > 0.0 else 0.033
        for kf in self._filters.values():
            kf.predict(dt)

        # ── YOLO-Seg + BoT-SORT inference ──
        results = self._model.track(
            source=frame,
            persist=True,
            tracker=self._tracker,
            conf=self._conf,
            iou=self._iou,
            imgsz=self._img_size,
            device=self._device or None,
            classes=self._allowed_ids,
            verbose=False,
        )
        self._last_raw_results = results

        tracks: list[Track] = []
        seen_ids: set = set()

        for result in results:
            boxes = result.boxes
            if boxes is None or len(boxes) == 0:
                continue

            has_ids = boxes.id is not None
            track_ids = boxes.id.cpu().numpy().astype(int) if has_ids else None

            xyxy = boxes.xyxy.cpu().numpy()
            confs = boxes.conf.cpu().numpy()
            cls_ids = boxes.cls.cpu().numpy().astype(int)
            masks = result.masks

            for i in range(len(xyxy)):
                x1, y1, x2, y2 = xyxy[i]
                w, h = x2 - x1, y2 - y1
                if w <= 0 or h <= 0:
                    continue

                tid = int(track_ids[i]) if track_ids is not None else (i + 1)
                cls_name = self._id_to_name.get(int(cls_ids[i]), "unknown")
                conf = float(confs[i])
                seen_ids.add(tid)

                # Raw mask centroid via cv2.moments (sub-pixel precise)
                raw_mask_center = self._compute_mask_centroid(masks, i)
                bbox = BoundingBox(x=float(x1), y=float(y1), w=float(w), h=float(h))
                raw_center = raw_mask_center if raw_mask_center is not None else bbox.center

                # ── Kalman update step ──
                if tid not in self._filters:
                    self._filters[tid] = self._create_filter(raw_center[0], raw_center[1])
                else:
                    self._filters[tid].update(raw_center[0], raw_center[1])

                self._filter_last_seen[tid] = timestamp
                if tid not in self._first_seen:
                    self._first_seen[tid] = timestamp

                kf = self._filters[tid]
                filtered_pos = kf.position
                filtered_vel = kf.velocity
                filtered_acc = kf.acceleration if hasattr(kf, "acceleration") else (0.0, 0.0)
                mask_center = filtered_pos if raw_mask_center is not None else None

                tracks.append(
                    Track(
                        track_id=tid,
                        bbox=bbox,
                        confidence=conf,
                        class_id=cls_name,
                        first_seen_ts=self._first_seen[tid],
                        last_seen_ts=timestamp,
                        age_frames=1,
                        misses=0,
                        velocity_px_per_s=filtered_vel,
                        acceleration_px_per_s2=filtered_acc,
                        mask_center=mask_center,
                    )
                )

        # Purge Kalman filters for tracks not seen recently (grace period)
        stale_ids = [
            tid
            for tid in self._filters
            if tid not in seen_ids and (timestamp - self._filter_last_seen.get(tid, 0.0)) > 0.5
        ]
        for stale_id in stale_ids:
            del self._filters[stale_id]
            self._filter_last_seen.pop(stale_id, None)
            self._first_seen.pop(stale_id, None)

        self._last_ts = timestamp
        return tracks

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_filter(self, cx0: float, cy0: float) -> _KalmanFilter:
        """Instantiate the appropriate Kalman filter for a new track."""
        if self._use_ca:
            return CentroidKalmanCA(cx0=cx0, cy0=cy0, config=self._kalman_cfg)
        return CentroidKalman2D(cx0=cx0, cy0=cy0, config=self._kalman_cfg)

    @staticmethod
    def _compute_mask_centroid(masks: object, idx: int) -> tuple[float, float] | None:
        """
        Extract the centroid of the i-th segmentation mask using cv2.moments.

        cv2.moments gives sub-pixel precision by computing the first-order
        spatial moments of the binary mask, which is more accurate than a
        simple np.mean of pixel coordinates.
        """
        if masks is None:
            return None
        try:
            mask_tensor = masks.data[idx].cpu().numpy()
            # Convert to uint8 for cv2.moments
            binary = (mask_tensor > 0.5).astype(np.uint8)
            M = _cv2.moments(binary)
            if M["m00"] < 1.0:
                return None
            # Centroid in mask coordinates
            mcx = M["m10"] / M["m00"]
            mcy = M["m01"] / M["m00"]
            # Scale to original image coordinates
            orig_h, orig_w = masks.orig_shape
            mask_h, mask_w = mask_tensor.shape
            cx = mcx * (orig_w / mask_w)
            cy = mcy * (orig_h / mask_h)
            return (float(cx), float(cy))
        except (IndexError, AttributeError, _cv2.error) as exc:
            logger.warning("mask centroid computation failed for idx=%d: %s", idx, exc)
            return None
