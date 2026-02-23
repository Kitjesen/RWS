"""配置热更新模块单元测试。"""

import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from src.rws_tracking.tools.config_reload import ConfigReloader


class TestConfigReloader:
    def test_init(self, tmp_path):
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.dump({"camera": {"width": 640}}))
        cb = MagicMock()
        r = ConfigReloader(p, cb, check_interval=0.1)
        assert r.config_path == p
        assert r.check_interval == 0.1

    def test_start_stop(self, tmp_path):
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.dump({}))
        cb = MagicMock()
        r = ConfigReloader(p, cb, check_interval=0.05)
        r.start()
        assert r._running
        r.stop()
        assert not r._running

    def test_double_start(self, tmp_path):
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.dump({}))
        cb = MagicMock()
        r = ConfigReloader(p, cb, check_interval=0.05)
        r.start()
        r.start()  # should not crash
        r.stop()

    def test_stop_when_not_running(self, tmp_path):
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.dump({}))
        cb = MagicMock()
        r = ConfigReloader(p, cb)
        r.stop()  # should not crash

    def test_detects_change(self, tmp_path):
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.dump({"camera": {"width": 640}}))
        cb = MagicMock()
        r = ConfigReloader(p, cb, check_interval=0.05)
        r.start()
        time.sleep(0.15)  # let first check record mtime
        # Modify file
        time.sleep(0.05)
        p.write_text(yaml.dump({"camera": {"width": 320}}))
        time.sleep(0.3)  # wait for detection
        r.stop()
        assert cb.called

    def test_missing_file(self, tmp_path):
        p = tmp_path / "nonexistent.yaml"
        cb = MagicMock()
        r = ConfigReloader(p, cb, check_interval=0.05)
        r._check_and_reload()  # should not crash
        assert not cb.called

    def test_first_check_records_mtime(self, tmp_path):
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.dump({}))
        cb = MagicMock()
        r = ConfigReloader(p, cb)
        r._check_and_reload()
        assert r._last_mtime is not None
        assert not cb.called  # first check just records

    def test_no_change_no_callback(self, tmp_path):
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.dump({}))
        cb = MagicMock()
        r = ConfigReloader(p, cb)
        r._check_and_reload()  # first: record mtime
        r._check_and_reload()  # second: no change
        assert not cb.called

    def test_invalid_yaml_no_crash(self, tmp_path):
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.dump({}))
        cb = MagicMock()
        r = ConfigReloader(p, cb)
        r._check_and_reload()  # record mtime
        time.sleep(0.05)
        p.write_text("{{invalid yaml: [")
        r._check_and_reload()  # should not crash
        assert not cb.called
