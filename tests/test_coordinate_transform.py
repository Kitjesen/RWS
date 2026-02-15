"""Unit tests for coordinate transformations."""
import pytest
import numpy as np
from src.rws_tracking.algebra.coordinate_transform import (
    CameraModel,
    PixelToGimbalTransform,
    FullChainTransform,
    MountExtrinsics,
)
from src.rws_tracking.types import BodyState


class TestCameraModel:
    """Test camera model and distortion."""

    def test_initialization(self):
        """Test camera model initialization."""
        cam = CameraModel(
            width=1280,
            height=720,
            fx=970.0,
            fy=965.0,
            cx=640.0,
            cy=360.0,
        )

        assert cam.width == 1280
        assert cam.height == 720
        assert cam.fx == 970.0

    def test_pixel_to_normalized(self):
        """Test pixel to normalized coordinates."""
        cam = CameraModel(1280, 720, 970.0, 965.0, 640.0, 360.0)

        # Center pixel should map to (0, 0)
        xn, yn = cam.pixel_to_normalized(640.0, 360.0)
        assert xn == pytest.approx(0.0, abs=1e-6)
        assert yn == pytest.approx(0.0, abs=1e-6)

        # Right of center
        xn, yn = cam.pixel_to_normalized(740.0, 360.0)
        assert xn > 0

        # Below center (Y-down convention)
        xn, yn = cam.pixel_to_normalized(640.0, 460.0)
        assert yn > 0

    def test_normalized_to_pixel(self):
        """Test normalized to pixel coordinates."""
        cam = CameraModel(1280, 720, 970.0, 965.0, 640.0, 360.0)

        # (0, 0) should map to center
        u, v = cam.normalized_to_pixel(0.0, 0.0)
        assert u == pytest.approx(640.0, abs=1e-3)
        assert v == pytest.approx(360.0, abs=1e-3)

    def test_roundtrip_conversion(self):
        """Test pixel -> normalized -> pixel roundtrip."""
        cam = CameraModel(1280, 720, 970.0, 965.0, 640.0, 360.0)

        test_pixels = [
            (640.0, 360.0),  # Center
            (100.0, 100.0),  # Top-left
            (1180.0, 620.0), # Bottom-right
            (320.0, 540.0),  # Random
        ]

        for u_orig, v_orig in test_pixels:
            xn, yn = cam.pixel_to_normalized(u_orig, v_orig)
            u_back, v_back = cam.normalized_to_pixel(xn, yn)

            assert u_back == pytest.approx(u_orig, abs=1e-3)
            assert v_back == pytest.approx(v_orig, abs=1e-3)

    def test_distortion_undistortion(self):
        """Test distortion and undistortion."""
        cam = CameraModel(
            1280, 720, 970.0, 965.0, 640.0, 360.0,
            k1=0.1, k2=-0.05, p1=0.01, p2=-0.01, k3=0.02
        )

        # Distorted point
        xd, yd = 0.1, 0.05

        # Undistort
        xu, yu = cam.undistort(xd, yd)

        # Distort back
        xd_back, yd_back = cam.distort(xu, yu)

        # Should be close to original
        assert xd_back == pytest.approx(xd, abs=1e-3)
        assert yd_back == pytest.approx(yd, abs=1e-3)


class TestPixelToGimbalTransform:
    """Test pixel to gimbal coordinate transform."""

    def test_center_pixel_zero_error(self):
        """Center pixel should give zero angular error."""
        cam = CameraModel(1280, 720, 970.0, 965.0, 640.0, 360.0)
        transform = PixelToGimbalTransform(cam)

        yaw_err, pitch_err = transform.pixel_to_gimbal_error(640.0, 360.0, 0.0, 0.0)

        assert yaw_err == pytest.approx(0.0, abs=1e-3)
        assert pitch_err == pytest.approx(0.0, abs=1e-3)

    def test_right_of_center_positive_yaw(self):
        """Pixel right of center should give positive yaw error."""
        cam = CameraModel(1280, 720, 970.0, 965.0, 640.0, 360.0)
        transform = PixelToGimbalTransform(cam)

        yaw_err, pitch_err = transform.pixel_to_gimbal_error(740.0, 360.0, 0.0, 0.0)

        assert yaw_err > 0  # Target to the right

    def test_above_center_positive_pitch(self):
        """Pixel above center should give positive pitch error."""
        cam = CameraModel(1280, 720, 970.0, 965.0, 640.0, 360.0)
        transform = PixelToGimbalTransform(cam)

        yaw_err, pitch_err = transform.pixel_to_gimbal_error(640.0, 260.0, 0.0, 0.0)

        assert pitch_err > 0  # Target above

    def test_gimbal_offset_compensation(self):
        """Gimbal angle should offset the error."""
        cam = CameraModel(1280, 720, 970.0, 965.0, 640.0, 360.0)
        transform = PixelToGimbalTransform(cam)

        # Target at center, gimbal at 10° yaw
        yaw_err, pitch_err = transform.pixel_to_gimbal_error(640.0, 360.0, 10.0, 0.0)

        # Error should be negative (need to turn left to center)
        assert yaw_err < 0

    def test_symmetry(self):
        """Test symmetry of transform."""
        cam = CameraModel(1280, 720, 970.0, 965.0, 640.0, 360.0)
        transform = PixelToGimbalTransform(cam)

        # Right and left should be symmetric
        yaw_right, _ = transform.pixel_to_gimbal_error(740.0, 360.0, 0.0, 0.0)
        yaw_left, _ = transform.pixel_to_gimbal_error(540.0, 360.0, 0.0, 0.0)

        assert yaw_right == pytest.approx(-yaw_left, abs=0.1)

    def test_known_angles(self):
        """Test with known pixel-to-angle mapping."""
        cam = CameraModel(1280, 720, 970.0, 965.0, 640.0, 360.0)
        transform = PixelToGimbalTransform(cam)

        # 100 pixels right at fx=970 should be ~tan^-1(100/970) ≈ 5.88°
        yaw_err, _ = transform.pixel_to_gimbal_error(740.0, 360.0, 0.0, 0.0)
        expected = np.degrees(np.arctan(100.0 / 970.0))

        assert yaw_err == pytest.approx(expected, abs=0.5)


class TestFullChainTransform:
    """Test full coordinate transform chain."""

    def test_initialization(self):
        """Test full chain initialization."""
        cam = CameraModel(1280, 720, 970.0, 965.0, 640.0, 360.0)
        mount = MountExtrinsics(roll_deg=0.0, pitch_deg=0.0, yaw_deg=0.0)
        transform = FullChainTransform(cam, mount)

        assert transform is not None

    def test_target_lock_error_no_body_motion(self):
        """Test target lock error without body motion."""
        cam = CameraModel(1280, 720, 970.0, 965.0, 640.0, 360.0)
        mount = MountExtrinsics(roll_deg=0.0, pitch_deg=0.0, yaw_deg=0.0)
        transform = FullChainTransform(cam, mount)

        yaw_err, pitch_err = transform.target_lock_error(
            pixel_x=740.0,
            pixel_y=360.0,
            gimbal_yaw_deg=0.0,
            gimbal_pitch_deg=0.0,
            body_state=None
        )

        # Should match simple pixel_to_gimbal_error
        assert yaw_err > 0

    def test_target_lock_error_with_body_motion(self):
        """Test target lock error with body motion."""
        cam = CameraModel(1280, 720, 970.0, 965.0, 640.0, 360.0)
        mount = MountExtrinsics(roll_deg=0.0, pitch_deg=0.0, yaw_deg=0.0)
        transform = FullChainTransform(cam, mount)

        body_state = BodyState(
            timestamp=1.0,
            roll_deg=5.0,
            pitch_deg=10.0,
            yaw_deg=15.0,
            roll_rate_dps=0.0,
            pitch_rate_dps=0.0,
            yaw_rate_dps=0.0,
        )

        yaw_err, pitch_err = transform.target_lock_error(
            pixel_x=640.0,
            pixel_y=360.0,
            gimbal_yaw_deg=0.0,
            gimbal_pitch_deg=0.0,
            body_state=body_state
        )

        # Body motion should affect the error
        assert yaw_err != 0.0 or pitch_err != 0.0

    def test_mount_offset_effect(self):
        """Test effect of mount offset."""
        cam = CameraModel(1280, 720, 970.0, 965.0, 640.0, 360.0)

        # No offset
        mount_zero = MountExtrinsics(roll_deg=0.0, pitch_deg=0.0, yaw_deg=0.0)
        transform_zero = FullChainTransform(cam, mount_zero)

        # With yaw offset
        mount_offset = MountExtrinsics(roll_deg=0.0, pitch_deg=0.0, yaw_deg=10.0)
        transform_offset = FullChainTransform(cam, mount_offset)

        # Same pixel, different errors
        yaw_zero, _ = transform_zero.target_lock_error(740.0, 360.0, 0.0, 0.0, None)
        yaw_offset, _ = transform_offset.target_lock_error(740.0, 360.0, 0.0, 0.0, None)

        assert yaw_zero != yaw_offset


class TestCoordinateConsistency:
    """Test consistency across coordinate transforms."""

    def test_pixel_gimbal_world_consistency(self):
        """Test consistency of pixel -> gimbal -> world chain."""
        cam = CameraModel(1280, 720, 970.0, 965.0, 640.0, 360.0)
        transform = PixelToGimbalTransform(cam)

        # Target at known pixel
        pixel_x, pixel_y = 740.0, 360.0

        # Get gimbal error
        yaw_err, pitch_err = transform.pixel_to_gimbal_error(pixel_x, pixel_y, 0.0, 0.0)

        # If we move gimbal by this error, target should be centered
        yaw_err2, pitch_err2 = transform.pixel_to_gimbal_error(
            pixel_x, pixel_y, yaw_err, pitch_err
        )

        # New error should be near zero
        assert abs(yaw_err2) < 0.1
        assert abs(pitch_err2) < 0.1

    def test_inverse_transform_consistency(self):
        """Test that forward and inverse transforms are consistent."""
        cam = CameraModel(1280, 720, 970.0, 965.0, 640.0, 360.0)

        # Start with normalized coordinates
        xn_orig, yn_orig = 0.1, 0.05

        # To pixel
        u, v = cam.normalized_to_pixel(xn_orig, yn_orig)

        # Back to normalized
        xn_back, yn_back = cam.pixel_to_normalized(u, v)

        assert xn_back == pytest.approx(xn_orig, abs=1e-6)
        assert yn_back == pytest.approx(yn_orig, abs=1e-6)


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_pixel_at_image_boundary(self):
        """Test pixels at image boundaries."""
        cam = CameraModel(1280, 720, 970.0, 965.0, 640.0, 360.0)
        transform = PixelToGimbalTransform(cam)

        # Corner pixels
        corners = [
            (0.0, 0.0),
            (1280.0, 0.0),
            (0.0, 720.0),
            (1280.0, 720.0),
        ]

        for u, v in corners:
            yaw_err, pitch_err = transform.pixel_to_gimbal_error(u, v, 0.0, 0.0)
            # Should not crash, errors should be finite
            assert np.isfinite(yaw_err)
            assert np.isfinite(pitch_err)

    def test_extreme_gimbal_angles(self):
        """Test with extreme gimbal angles."""
        cam = CameraModel(1280, 720, 970.0, 965.0, 640.0, 360.0)
        transform = PixelToGimbalTransform(cam)

        # Extreme angles
        yaw_err, pitch_err = transform.pixel_to_gimbal_error(
            640.0, 360.0, 170.0, 80.0
        )

        assert np.isfinite(yaw_err)
        assert np.isfinite(pitch_err)

    def test_zero_focal_length(self):
        """Test handling of invalid focal length."""
        with pytest.raises((ValueError, ZeroDivisionError)):
            cam = CameraModel(1280, 720, 0.0, 0.0, 640.0, 360.0)

    def test_negative_pixel_coordinates(self):
        """Test with negative pixel coordinates."""
        cam = CameraModel(1280, 720, 970.0, 965.0, 640.0, 360.0)
        transform = PixelToGimbalTransform(cam)

        yaw_err, pitch_err = transform.pixel_to_gimbal_error(-100.0, -50.0, 0.0, 0.0)

        # Should handle gracefully
        assert np.isfinite(yaw_err)
        assert np.isfinite(pitch_err)

    def test_very_large_pixel_coordinates(self):
        """Test with very large pixel coordinates."""
        cam = CameraModel(1280, 720, 970.0, 965.0, 640.0, 360.0)
        transform = PixelToGimbalTransform(cam)

        yaw_err, pitch_err = transform.pixel_to_gimbal_error(10000.0, 10000.0, 0.0, 0.0)

        assert np.isfinite(yaw_err)
        assert np.isfinite(pitch_err)


class TestNumericalStability:
    """Test numerical stability of transforms."""

    def test_small_angle_approximation(self):
        """Test accuracy for small angles."""
        cam = CameraModel(1280, 720, 970.0, 965.0, 640.0, 360.0)
        transform = PixelToGimbalTransform(cam)

        # Very small offset (1 pixel)
        yaw_err, pitch_err = transform.pixel_to_gimbal_error(641.0, 360.0, 0.0, 0.0)

        # Should be very small but non-zero
        assert 0 < abs(yaw_err) < 0.1

    def test_repeated_transforms(self):
        """Test stability of repeated transforms."""
        cam = CameraModel(1280, 720, 970.0, 965.0, 640.0, 360.0)

        pixel_x, pixel_y = 740.0, 360.0

        # Transform multiple times
        results = []
        for _ in range(100):
            xn, yn = cam.pixel_to_normalized(pixel_x, pixel_y)
            u, v = cam.normalized_to_pixel(xn, yn)
            results.append((u, v))

        # All results should be identical
        for u, v in results:
            assert u == pytest.approx(pixel_x, abs=1e-6)
            assert v == pytest.approx(pixel_y, abs=1e-6)
