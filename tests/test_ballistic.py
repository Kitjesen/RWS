"""弹道补偿模块完整单元测试。"""

import math

import pytest

from src.rws_tracking.control.ballistic import (
    PhysicsBallisticModel,
    SimpleBallisticConfig,
    SimpleBallisticModel,
    TableBallisticConfig,
    TableBallisticModel,
    estimate_distance_from_bbox,
)
from src.rws_tracking.types import (
    BallisticSolution,
    BoundingBox,
    EnvironmentParams,
    ProjectileParams,
)


class TestEstimateDistance:
    def test_normal_bbox(self):
        bbox = BoundingBox(x=0, y=0, w=80, h=150)
        d = estimate_distance_from_bbox(bbox, 970.0, 1.8)
        assert d == pytest.approx(1.8 * 970.0 / 150.0, rel=0.01)

    def test_zero_height_returns_zero(self):
        bbox = BoundingBox(x=0, y=0, w=80, h=0)
        assert estimate_distance_from_bbox(bbox, 970.0) == 0.0

    def test_tiny_height_returns_zero(self):
        bbox = BoundingBox(x=0, y=0, w=80, h=0.5)
        assert estimate_distance_from_bbox(bbox, 970.0) == 0.0


class TestSimpleBallisticModel:
    @pytest.fixture
    def model(self):
        return SimpleBallisticModel(SimpleBallisticConfig(
            target_height_m=1.8,
            quadratic_a=0.001,
            quadratic_b=0.01,
            quadratic_c=0.0,
        ))

    def test_positive_compensation(self, model):
        bbox = BoundingBox(x=0, y=0, w=80, h=150)
        comp = model.compute(bbox, 970.0)
        assert comp > 0.0

    def test_zero_height_bbox(self, model):
        bbox = BoundingBox(x=0, y=0, w=80, h=0)
        assert model.compute(bbox, 970.0) == 0.0

    def test_larger_distance_more_compensation(self, model):
        near = BoundingBox(x=0, y=0, w=80, h=300)  # close
        far = BoundingBox(x=0, y=0, w=80, h=50)    # far
        assert model.compute(far, 970.0) > model.compute(near, 970.0)


class TestTableBallisticModel:
    @pytest.fixture
    def model(self):
        return TableBallisticModel(TableBallisticConfig(
            target_height_m=1.8,
            distance_table=(5.0, 10.0, 20.0, 30.0),
            compensation_table=(0.1, 0.4, 1.6, 3.6),
        ))

    def test_interpolation(self, model):
        bbox = BoundingBox(x=0, y=0, w=80, h=int(1.8 * 970.0 / 15.0))
        comp = model.compute(bbox, 970.0)
        assert 0.4 < comp < 1.6

    def test_mismatched_tables_raises(self):
        with pytest.raises(ValueError):
            TableBallisticModel(TableBallisticConfig(
                distance_table=(5.0, 10.0),
                compensation_table=(0.1,),
            ))

    def test_zero_height(self, model):
        bbox = BoundingBox(x=0, y=0, w=80, h=0)
        assert model.compute(bbox, 970.0) == 0.0


class TestPhysicsBallisticModel:
    @pytest.fixture
    def model(self):
        return PhysicsBallisticModel(
            projectile=ProjectileParams(
                muzzle_velocity_mps=900.0,
                ballistic_coefficient=0.4,
                projectile_mass_kg=0.0098,
                projectile_diameter_m=0.00762,
            ),
            target_height_m=1.8,
        )

    def test_solve_positive_flight_time(self, model):
        sol = model.solve(100.0)
        assert sol.flight_time_s > 0.0
        assert sol.flight_time_s < 1.0

    def test_solve_positive_drop(self, model):
        sol = model.solve(100.0)
        assert sol.drop_deg > 0.0

    def test_solve_zero_distance(self, model):
        sol = model.solve(0.0)
        assert sol.flight_time_s == 0.0

    def test_solve_negative_distance(self, model):
        sol = model.solve(-10.0)
        assert sol.flight_time_s == 0.0

    def test_longer_distance_more_drop(self, model):
        sol100 = model.solve(100.0)
        sol200 = model.solve(200.0)
        assert sol200.drop_deg > sol100.drop_deg
        assert sol200.flight_time_s > sol100.flight_time_s

    def test_wind_causes_windage(self, model):
        env = EnvironmentParams(wind_speed_mps=10.0, wind_direction_deg=90.0)
        sol = model.solve(100.0, environment=env)
        assert sol.windage_deg != 0.0

    def test_no_wind_no_windage(self, model):
        env = EnvironmentParams(wind_speed_mps=0.0)
        sol = model.solve(100.0, environment=env)
        assert abs(sol.windage_deg) < 0.01

    def test_compute_flight_time(self, model):
        t = model.compute_flight_time(200.0)
        assert t > 0.0

    def test_compute_flight_time_zero(self, model):
        assert model.compute_flight_time(0.0) == 0.0

    def test_compute_bbox_interface(self, model):
        bbox = BoundingBox(x=0, y=0, w=80, h=150)
        comp = model.compute(bbox, 970.0)
        assert comp > 0.0

    def test_impact_velocity_less_than_muzzle(self, model):
        sol = model.solve(500.0)
        assert sol.impact_velocity_mps < 900.0
        assert sol.impact_velocity_mps > 0.0
