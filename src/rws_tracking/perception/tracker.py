"""Re-export from qp-perception with legacy helper compatibility."""

from qp_perception.tracking.iou import SimpleIoUTracker, _iou

__all__ = ["SimpleIoUTracker", "_iou"]
