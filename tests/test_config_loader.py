"""配置加载器单元测试。"""

import tempfile
from pathlib import Path

import pytest
import yaml

from src.rws_tracking.config.loader import (
    SystemConfig,
    _nested_dict_to_config,
    _tuples_to_lists,
    default_controller_config,
    load_config,
    save_config,
)


class TestDefaultControllerConfig:
    def test_returns_config(self):
        cfg = default_controller_config()
        assert cfg.yaw_pid.kp > 0
        assert cfg.pitch_pid.kp > 0

    def test_has_feedforward(self):
        cfg = default_controller_config()
        assert cfg.yaw_pid.feedforward_kv > 0


class TestSystemConfig:
    def test_default_init(self):
        cfg = SystemConfig()
        assert cfg.camera is not None
        assert cfg.controller is not None

    def test_controller_auto_created(self):
        cfg = SystemConfig(controller=None)
        assert cfg.controller is not None


class TestLoadConfig:
    def test_load_valid_yaml(self, tmp_path):
        p = tmp_path / "test.yaml"
        p.write_text(yaml.dump({
            "camera": {"width": 640, "height": 480},
            "detector": {"confidence_threshold": 0.5},
        }))
        cfg = load_config(str(p))
        assert cfg.camera.width == 640
        assert cfg.camera.height == 480
        assert cfg.detector.confidence_threshold == 0.5

    def test_load_empty_yaml(self, tmp_path):
        p = tmp_path / "empty.yaml"
        p.write_text("")
        cfg = load_config(str(p))
        assert cfg.camera is not None

    def test_load_with_controller(self, tmp_path):
        p = tmp_path / "ctrl.yaml"
        p.write_text(yaml.dump({
            "controller": {
                "yaw_pid": {"kp": 8.0, "ki": 0.5, "kd": 0.3},
                "pitch_pid": {"kp": 7.0},
            }
        }))
        cfg = load_config(str(p))
        assert cfg.controller.yaw_pid.kp == 8.0

    def test_load_with_safety(self, tmp_path):
        p = tmp_path / "safety.yaml"
        p.write_text(yaml.dump({
            "safety": {
                "enabled": True,
                "interlock": {"require_operator_auth": False},
                "zones": [
                    {"zone_id": "z1", "center_yaw_deg": 90.0,
                     "center_pitch_deg": 0.0, "radius_deg": 10.0}
                ],
            }
        }))
        cfg = load_config(str(p))
        assert cfg.safety.enabled
        assert len(cfg.safety.zones) == 1

    def test_load_with_engagement(self, tmp_path):
        p = tmp_path / "eng.yaml"
        p.write_text(yaml.dump({
            "engagement": {
                "enabled": True,
                "strategy": "nearest_first",
                "weights": {"distance": 0.5, "velocity": 0.3},
            }
        }))
        cfg = load_config(str(p))
        assert cfg.engagement.enabled
        assert cfg.engagement.strategy == "nearest_first"

    def test_unknown_keys_ignored(self, tmp_path):
        p = tmp_path / "unk.yaml"
        p.write_text(yaml.dump({
            "camera": {"width": 640, "unknown_key": 42},
        }))
        cfg = load_config(str(p))
        assert cfg.camera.width == 640


class TestSaveConfig:
    def test_roundtrip(self, tmp_path):
        p = tmp_path / "out.yaml"
        cfg = SystemConfig()
        save_config(cfg, str(p))
        loaded = load_config(str(p))
        assert loaded.camera.width == cfg.camera.width
        assert loaded.controller.yaw_pid.kp == cfg.controller.yaw_pid.kp

    def test_file_created(self, tmp_path):
        p = tmp_path / "out.yaml"
        save_config(SystemConfig(), str(p))
        assert p.exists()


class TestTuplesToLists:
    def test_tuple_converted(self):
        assert _tuples_to_lists((1, 2, 3)) == [1, 2, 3]

    def test_nested_dict(self):
        r = _tuples_to_lists({"a": (1, 2), "b": {"c": (3,)}})
        assert r == {"a": [1, 2], "b": {"c": [3]}}

    def test_scalar_unchanged(self):
        assert _tuples_to_lists(42) == 42
        assert _tuples_to_lists("hello") == "hello"


class TestNestedDictToConfig:
    def test_empty_dict(self):
        cfg = _nested_dict_to_config({})
        assert cfg.camera is not None

    def test_partial_dict(self):
        cfg = _nested_dict_to_config({"camera": {"width": 320}})
        assert cfg.camera.width == 320

    def test_ballistic_tables(self):
        cfg = _nested_dict_to_config({
            "controller": {
                "ballistic": {
                    "distance_table": [5, 10, 15],
                    "compensation_table": [0.1, 0.4, 0.9],
                }
            }
        })
        assert len(cfg.controller.ballistic.distance_table) == 3

    def test_scan_pattern_list(self):
        cfg = _nested_dict_to_config({
            "controller": {"scan_pattern": [30.0, 15.0]}
        })
        assert cfg.controller.scan_pattern == (30.0, 15.0)
