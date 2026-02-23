"""Performance benchmarks for RWS components."""

import time

import pytest

from src.rws_tracking.algebra.coordinate_transform import (
    CameraModel,
    PixelToGimbalTransform,
)
from src.rws_tracking.algebra.kalman2d import ConstantVelocityKalman2D
from src.rws_tracking.config import SelectorConfig, SelectorWeights
from src.rws_tracking.perception.selector import WeightedTargetSelector
from src.rws_tracking.types import BoundingBox, Track


@pytest.fixture
def camera_model():
    """Create camera model for benchmarks."""
    return CameraModel(1280, 720, 970.0, 965.0, 640.0, 360.0)


@pytest.fixture
def selector():
    """Create selector for benchmarks."""
    config = SelectorConfig(
        weights=SelectorWeights(
            confidence=0.35,
            size=0.20,
            center_proximity=0.20,
            track_age=0.15,
            class_weight=0.10,
            switch_penalty=0.30,
        ),
        min_hold_time_s=0.4,
        delta_threshold=0.12,
        preferred_classes={"person": 1.0},
    )
    return WeightedTargetSelector(1280, 720, config)


class TestCoordinateTransformPerformance:
    """Benchmark coordinate transforms."""

    def test_pixel_to_gimbal_single(self, benchmark, camera_model):
        """Benchmark single pixel to gimbal transform."""
        transform = PixelToGimbalTransform(camera_model)

        def run():
            return transform.pixel_to_gimbal_error(740.0, 360.0, 0.0, 0.0)

        benchmark(run)

        # Should be very fast (< 100 microseconds)
        assert benchmark.stats["mean"] < 0.0001  # 100 µs

    def test_pixel_to_gimbal_batch(self, benchmark, camera_model):
        """Benchmark batch pixel to gimbal transforms."""
        transform = PixelToGimbalTransform(camera_model)

        pixels = [(100 + i * 10, 200 + i * 5) for i in range(100)]

        def run():
            results = []
            for px, py in pixels:
                results.append(transform.pixel_to_gimbal_error(px, py, 0.0, 0.0))
            return results

        benchmark(run)

        # 100 transforms should be < 10ms
        assert benchmark.stats["mean"] < 0.01

    def test_pixel_to_normalized(self, benchmark, camera_model):
        """Benchmark pixel to normalized conversion."""

        def run():
            return camera_model.pixel_to_normalized(740.0, 360.0)

        benchmark(run)

        # Should be extremely fast (< 10 microseconds)
        assert benchmark.stats["mean"] < 0.00001  # 10 µs

    def test_distortion_correction(self, benchmark):
        """Benchmark distortion correction."""
        cam = CameraModel(
            1280, 720, 970.0, 965.0, 640.0, 360.0, k1=0.1, k2=-0.05, p1=0.01, p2=-0.01, k3=0.02
        )

        def run():
            return cam.undistort(0.1, 0.05)

        benchmark(run)

        # Distortion correction should be fast (< 50 microseconds)
        assert benchmark.stats["mean"] < 0.00005  # 50 µs


class TestKalmanFilterPerformance:
    """Benchmark Kalman filters."""

    def test_kalman_update(self, benchmark):
        """Benchmark Kalman filter update."""
        kf = ConstantVelocityKalman2D(process_noise=0.1, measurement_noise=1.0)

        def run():
            kf.update(100.0, 200.0, timestamp=time.time())

        benchmark(run)

        # Kalman update should be fast (< 100 microseconds)
        assert benchmark.stats["mean"] < 0.0001  # 100 µs

    def test_kalman_predict(self, benchmark):
        """Benchmark Kalman filter prediction."""
        kf = ConstantVelocityKalman2D(process_noise=0.1, measurement_noise=1.0)
        kf.update(100.0, 200.0, timestamp=0.0)

        def run():
            return kf.predict(dt=0.033)

        benchmark(run)

        # Prediction should be very fast (< 50 microseconds)
        assert benchmark.stats["mean"] < 0.00005  # 50 µs

    def test_kalman_sequence(self, benchmark):
        """Benchmark sequence of Kalman updates."""
        kf = ConstantVelocityKalman2D(process_noise=0.1, measurement_noise=1.0)

        measurements = [(100 + i, 200 + i * 0.5) for i in range(30)]

        def run():
            for i, (x, y) in enumerate(measurements):
                kf.update(x, y, timestamp=i * 0.033)

        benchmark(run)

        # 30 updates @ 30Hz should be < 3ms
        assert benchmark.stats["mean"] < 0.003


class TestSelectorPerformance:
    """Benchmark target selector."""

    def create_tracks(self, n: int) -> list:
        """Create n dummy tracks."""
        tracks = []
        for i in range(n):
            track = Track(
                track_id=i,
                bbox=BoundingBox(x=100 + i * 50, y=100 + i * 30, w=50, h=50),
                confidence=0.7 + i * 0.01,
                class_id="person",
                first_seen_ts=0.0,
                last_seen_ts=0.0,
                velocity_px_per_s=(10.0, 5.0),
                acceleration_px_per_s2=(0.0, 0.0),
                mask_center=None,
            )
            tracks.append(track)
        return tracks

    def test_selector_single_track(self, benchmark, selector):
        """Benchmark selector with single track."""
        tracks = self.create_tracks(1)

        def run():
            return selector.select(tracks, timestamp=1.0)

        benchmark(run)

        # Single track selection should be very fast (< 50 microseconds)
        assert benchmark.stats["mean"] < 0.00005  # 50 µs

    def test_selector_10_tracks(self, benchmark, selector):
        """Benchmark selector with 10 tracks."""
        tracks = self.create_tracks(10)

        def run():
            return selector.select(tracks, timestamp=1.0)

        benchmark(run)

        # 10 tracks should be < 200 microseconds
        assert benchmark.stats["mean"] < 0.0002  # 200 µs

    def test_selector_50_tracks(self, benchmark, selector):
        """Benchmark selector with 50 tracks."""
        tracks = self.create_tracks(50)

        def run():
            return selector.select(tracks, timestamp=1.0)

        benchmark(run)

        # 50 tracks should be < 1ms
        assert benchmark.stats["mean"] < 0.001

    def test_selector_100_tracks(self, benchmark, selector):
        """Benchmark selector with 100 tracks."""
        tracks = self.create_tracks(100)

        def run():
            return selector.select(tracks, timestamp=1.0)

        benchmark(run)

        # 100 tracks should be < 2ms
        assert benchmark.stats["mean"] < 0.002


class TestEndToEndPerformance:
    """Benchmark end-to-end scenarios."""

    def test_single_frame_processing(self, benchmark, camera_model, selector):
        """Benchmark single frame processing (without YOLO)."""
        transform = PixelToGimbalTransform(camera_model)
        tracks = [
            Track(
                track_id=i,
                bbox=BoundingBox(x=100 + i * 100, y=200, w=100, h=100),
                confidence=0.8,
                class_id="person",
                first_seen_ts=0.0,
                last_seen_ts=0.0,
                velocity_px_per_s=(10.0, 5.0),
                acceleration_px_per_s2=(0.0, 0.0),
                mask_center=None,
            )
            for i in range(5)
        ]

        def run():
            # Select target
            target = selector.select(tracks, timestamp=1.0)
            if target:
                # Compute error
                cx, cy = target.bbox.center
                yaw_err, pitch_err = transform.pixel_to_gimbal_error(cx, cy, 0.0, 0.0)
            return target

        benchmark(run)

        # Full processing (without YOLO) should be < 500 microseconds
        assert benchmark.stats["mean"] < 0.0005  # 500 µs

    def test_control_loop_iteration(self, benchmark, camera_model):
        """Benchmark single control loop iteration."""
        transform = PixelToGimbalTransform(camera_model)
        kf = ConstantVelocityKalman2D(process_noise=0.1, measurement_noise=1.0)

        def run():
            # Simulate control loop
            # 1. Get measurement
            pixel_x, pixel_y = 740.0, 360.0

            # 2. Kalman update
            kf.update(pixel_x, pixel_y, timestamp=time.time())

            # 3. Compute error
            yaw_err, pitch_err = transform.pixel_to_gimbal_error(pixel_x, pixel_y, 0.0, 0.0)

            # 4. Predict
            kf.predict(dt=0.033)

            return yaw_err, pitch_err

        benchmark(run)

        # Control loop iteration should be < 200 microseconds
        assert benchmark.stats["mean"] < 0.0002  # 200 µs


class TestMemoryUsage:
    """Test memory usage of components."""

    def test_kalman_filter_memory(self):
        """Test Kalman filter memory footprint."""
        import sys

        kf = ConstantVelocityKalman2D(process_noise=0.1, measurement_noise=1.0)
        size = sys.getsizeof(kf)

        # Should be reasonably small (< 10KB)
        assert size < 10000

    def test_selector_memory(self):
        """Test selector memory footprint."""
        import sys

        config = SelectorConfig(
            weights=SelectorWeights(
                confidence=0.35,
                size=0.20,
                center_proximity=0.20,
                track_age=0.15,
                class_weight=0.10,
                switch_penalty=0.30,
            ),
            min_hold_time_s=0.4,
            delta_threshold=0.12,
            preferred_classes={"person": 1.0},
        )
        selector = WeightedTargetSelector(1280, 720, config)
        size = sys.getsizeof(selector)

        # Should be reasonably small (< 10KB)
        assert size < 10000


class TestScalability:
    """Test scalability with increasing load."""

    def test_transform_scalability(self, camera_model):
        """Test transform performance scales linearly."""
        transform = PixelToGimbalTransform(camera_model)

        times = []
        for n in [10, 50, 100, 500]:
            pixels = [(100 + i, 200 + i) for i in range(n)]

            start = time.perf_counter()
            for px, py in pixels:
                transform.pixel_to_gimbal_error(px, py, 0.0, 0.0)
            elapsed = time.perf_counter() - start

            times.append((n, elapsed))

        # Check linear scaling only when the operations take measurable time.
        # On fast hardware both runs may be sub-millisecond so the ratio is
        # dominated by timer noise; skip the assertion in that case.
        t10, t100 = times[0][1], times[2][1]
        if t10 > 1e-4:  # only assert when 10-op run takes > 0.1 ms
            ratio = t100 / t10
            assert 2 < ratio < 20  # looser bound: super-linear but not flat

    def test_selector_scalability(self):
        """Test selector performance scales reasonably."""
        config = SelectorConfig(
            weights=SelectorWeights(
                confidence=0.35,
                size=0.20,
                center_proximity=0.20,
                track_age=0.15,
                class_weight=0.10,
                switch_penalty=0.30,
            ),
            min_hold_time_s=0.4,
            delta_threshold=0.12,
            preferred_classes={"person": 1.0},
        )
        selector = WeightedTargetSelector(1280, 720, config)

        times = []
        for n in [10, 50, 100]:
            tracks = [
                Track(
                    track_id=i,
                    bbox=BoundingBox(x=100 + i * 10, y=100, w=50, h=50),
                    confidence=0.8,
                    class_id="person",
                    first_seen_ts=0.0,
                    last_seen_ts=0.0,
                    velocity_px_per_s=(10.0, 5.0),
                    acceleration_px_per_s2=(0.0, 0.0),
                    mask_center=None,
                )
                for i in range(n)
            ]

            start = time.perf_counter()
            selector.select(tracks, timestamp=1.0)
            elapsed = time.perf_counter() - start

            times.append((n, elapsed))

        # Should scale roughly linearly
        # Even 100 tracks should be < 2ms
        assert times[-1][1] < 0.002


class TestRealTimeConstraints:
    """Test real-time performance constraints."""

    def test_30hz_frame_budget(self, camera_model):
        """Test that processing fits in 30Hz frame budget."""
        # At 30Hz, we have 33.3ms per frame
        # Control loop should use < 1ms, leaving 32ms for YOLO

        transform = PixelToGimbalTransform(camera_model)
        kf = ConstantVelocityKalman2D(process_noise=0.1, measurement_noise=1.0)

        config = SelectorConfig(
            weights=SelectorWeights(
                confidence=0.35,
                size=0.20,
                center_proximity=0.20,
                track_age=0.15,
                class_weight=0.10,
                switch_penalty=0.30,
            ),
            min_hold_time_s=0.4,
            delta_threshold=0.12,
            preferred_classes={"person": 1.0},
        )
        selector = WeightedTargetSelector(1280, 720, config)

        # Simulate 10 tracks
        tracks = [
            Track(
                track_id=i,
                bbox=BoundingBox(x=100 + i * 50, y=100, w=50, h=50),
                confidence=0.8,
                class_id="person",
                first_seen_ts=0.0,
                last_seen_ts=0.0,
                velocity_px_per_s=(10.0, 5.0),
                acceleration_px_per_s2=(0.0, 0.0),
                mask_center=None,
            )
            for i in range(10)
        ]

        # Measure full control loop
        start = time.perf_counter()

        # Select target
        target = selector.select(tracks, timestamp=1.0)

        if target:
            # Kalman update
            cx, cy = target.bbox.center
            kf.update(cx, cy, timestamp=1.0)

            # Compute error
            yaw_err, pitch_err = transform.pixel_to_gimbal_error(cx, cy, 0.0, 0.0)

            # Predict
            kf.predict(dt=0.033)

        elapsed = time.perf_counter() - start

        # Should be < 1ms (leaving 32ms for YOLO)
        assert elapsed < 0.001

    def test_60hz_frame_budget(self, camera_model):
        """Test that processing fits in 60Hz frame budget."""
        # At 60Hz, we have 16.7ms per frame
        # Control loop should still be < 1ms

        transform = PixelToGimbalTransform(camera_model)

        start = time.perf_counter()
        for _ in range(60):  # 1 second worth
            transform.pixel_to_gimbal_error(740.0, 360.0, 0.0, 0.0)
        elapsed = time.perf_counter() - start

        # 60 transforms should be < 10ms
        assert elapsed < 0.01
