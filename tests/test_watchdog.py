"""Tests for OperatorWatchdog (deadman switch)."""

from __future__ import annotations

import time

import pytest

from src.rws_tracking.safety.shooting_chain import FireChainState, ShootingChain
from src.rws_tracking.safety.watchdog import OperatorWatchdog


@pytest.fixture()
def armed_chain():
    chain = ShootingChain(cooldown_s=3.0)
    chain.arm("op1")
    return chain


class TestWatchdogHeartbeat:
    def test_not_timed_out_initially(self, armed_chain):
        wd = OperatorWatchdog(armed_chain, timeout_s=5.0)
        assert not wd.timed_out

    def test_seconds_since_heartbeat_near_zero(self, armed_chain):
        wd = OperatorWatchdog(armed_chain, timeout_s=5.0)
        assert wd.seconds_since_heartbeat < 0.5

    def test_heartbeat_resets_timer(self, armed_chain):
        wd = OperatorWatchdog(armed_chain, timeout_s=5.0)
        time.sleep(0.05)
        wd.heartbeat("op1")
        assert wd.seconds_since_heartbeat < 0.1


class TestWatchdogTimeout:
    def test_auto_safe_on_timeout(self, armed_chain):
        wd = OperatorWatchdog(armed_chain, timeout_s=0.1, check_interval_s=0.05)
        wd.start()
        time.sleep(0.4)
        wd.stop()
        assert armed_chain.state == FireChainState.SAFE

    def test_timed_out_flag_set(self, armed_chain):
        wd = OperatorWatchdog(armed_chain, timeout_s=0.1, check_interval_s=0.05)
        wd.start()
        time.sleep(0.4)
        wd.stop()
        assert wd.timed_out

    def test_reconnect_clears_timeout_flag(self, armed_chain):
        wd = OperatorWatchdog(armed_chain, timeout_s=0.1, check_interval_s=0.05)
        wd.start()
        time.sleep(0.4)
        wd.heartbeat("op1")
        assert not wd.timed_out
        wd.stop()

    def test_chain_stays_safe_no_double_log(self, armed_chain):
        """Watchdog should not repeatedly call safe() after first timeout."""
        safe_calls = []
        original_safe = armed_chain.safe

        def counting_safe(reason=""):
            safe_calls.append(reason)
            original_safe(reason)

        armed_chain.safe = counting_safe

        wd = OperatorWatchdog(armed_chain, timeout_s=0.1, check_interval_s=0.05)
        wd.start()
        time.sleep(0.5)
        wd.stop()
        assert len(safe_calls) == 1  # Called exactly once


class TestWatchdogStartStop:
    def test_stop_without_start(self, armed_chain):
        wd = OperatorWatchdog(armed_chain, timeout_s=5.0)
        wd.stop()  # Should not raise

    def test_double_start_safe(self, armed_chain):
        wd = OperatorWatchdog(armed_chain, timeout_s=5.0, check_interval_s=0.1)
        wd.start()
        wd.start()  # Second start is a no-op
        wd.stop()
