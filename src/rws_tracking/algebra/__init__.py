"""
algebra - Camera model, distortion, mount extrinsics, coordinate transforms,
          Kalman filters.

Pure math / geometry, no business logic.
"""

from .coordinate_transform import (
    CameraModel,
    DistortionCoeffs,
    FullChainTransform,
    MountExtrinsics,
    PixelToGimbalTransform,
)
from .kalman2d import CentroidKalman2D, CentroidKalmanCA, KalmanCAConfig, KalmanConfig

__all__ = [
    "CameraModel",
    "CentroidKalman2D",
    "CentroidKalmanCA",
    "DistortionCoeffs",
    "FullChainTransform",
    "KalmanCAConfig",
    "KalmanConfig",
    "MountExtrinsics",
    "PixelToGimbalTransform",
]
