"""
MuJoCo Offscreen Camera Renderer
=================================

Renders the gimbal-mounted camera view as a BGR numpy array,
identical in format to what ``cv2.VideoCapture.read()`` returns.

This module owns the MuJoCo renderer/context lifecycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import cv2
import numpy as np

if TYPE_CHECKING:
    import mujoco


class MujocoCameraRenderer:
    """
    Offscreen renderer for a named MuJoCo camera.

    Parameters
    ----------
    model : mujoco.MjModel
    data  : mujoco.MjData
    camera_name : MJCF camera name (default ``"gimbal_cam"``).
    width, height : render resolution (must match MJCF ``resolution``).
    """

    def __init__(
        self,
        model: mujoco.MjModel,
        data: mujoco.MjData,
        camera_name: str = "gimbal_cam",
        width: int = 1280,
        height: int = 720,
    ) -> None:
        import mujoco as mj

        self._m = model
        self._d = data
        self._width = width
        self._height = height
        self._cam_id = mj.mj_name2id(model, mj.mjtObj.mjOBJ_CAMERA, camera_name)
        if self._cam_id < 0:
            raise ValueError(f"Camera '{camera_name}' not found in MJCF model.")

        # Create offscreen renderer
        self._renderer = mj.Renderer(model, height=height, width=width)
        # Pre-allocate output buffer to avoid per-frame allocation
        self._bgr_buf = np.empty((height, width, 3), dtype=np.uint8)

    def render(self) -> np.ndarray:
        """
        Render the current scene from the gimbal camera viewpoint.

        Returns
        -------
        frame : np.ndarray, shape (height, width, 3), dtype uint8, BGR format.
        """
        self._renderer.update_scene(self._d, camera=self._cam_id)
        rgb = self._renderer.render()  # shape (H, W, 3), RGB, uint8

        # SIMD-optimized RGB → BGR, reuse pre-allocated buffer
        cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR, dst=self._bgr_buf)
        return self._bgr_buf

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    def close(self) -> None:
        """Release renderer resources."""
        self._renderer.close()
