"""串口云台驱动单元测试。"""

from unittest.mock import MagicMock

import pytest

from src.rws_tracking.hardware.serial_driver import GimbalProtocol, SerialGimbalDriver


@pytest.fixture
def mock_serial():
    """Mock pyserial module and Serial class."""
    mock_ser = MagicMock()
    mock_ser.is_open = True
    mock_ser.in_waiting = 0
    return mock_ser


def _make_driver(mock_ser, protocol=GimbalProtocol.CUSTOM, **kwargs):
    d = SerialGimbalDriver.__new__(SerialGimbalDriver)
    d.port = "COM_TEST"
    d.baudrate = 115200
    d.protocol = protocol
    d.timeout = 0.1
    d._address = kwargs.get("address", 0x01)
    d._yaw_limit = kwargs.get("yaw_limit_deg", 180.0)
    d._pitch_limit = kwargs.get("pitch_limit_deg", 90.0)
    d._serial = mock_ser
    d._yaw_deg = 0.0
    d._pitch_deg = 0.0
    d._yaw_rate_dps = 0.0
    d._pitch_rate_dps = 0.0
    d._last_feedback_time = 0.0
    d._last_cmd_time = None
    return d


class TestCustomProtocol:
    def test_send_command(self, mock_serial):
        d = _make_driver(mock_serial, GimbalProtocol.CUSTOM)
        d.set_yaw_pitch_rate(10.0, 5.0, 1.0)
        mock_serial.write.assert_called_once()
        packet = mock_serial.write.call_args[0][0]
        assert packet[0] == 0xFF
        assert packet[1] == 0xAA
        assert len(packet) == 7

    def test_read_feedback_valid(self, mock_serial):
        d = _make_driver(mock_serial, GimbalProtocol.CUSTOM)
        # Build valid feedback packet
        yaw_int = 32768 + int(10.0 / 180.0 * 32767)
        pitch_int = 32768 + int(5.0 / 180.0 * 32767)
        rate_yaw_int = 32768
        rate_pitch_int = 32768
        data = [
            (yaw_int >> 8) & 0xFF, yaw_int & 0xFF,
            (pitch_int >> 8) & 0xFF, pitch_int & 0xFF,
            (rate_yaw_int >> 8) & 0xFF, rate_yaw_int & 0xFF,
            (rate_pitch_int >> 8) & 0xFF, rate_pitch_int & 0xFF,
        ]
        checksum = 0
        for b in data:
            checksum ^= b
        packet = bytearray([0xFF, 0xBB] + data + [checksum])
        mock_serial.in_waiting = 11
        mock_serial.read.return_value = packet
        fb = d.get_feedback(1.0)
        assert abs(fb.yaw_deg - 10.0) < 0.1

    def test_read_feedback_bad_header(self, mock_serial):
        d = _make_driver(mock_serial, GimbalProtocol.CUSTOM)
        mock_serial.in_waiting = 11
        mock_serial.read.return_value = bytearray([0x00] * 11)
        fb = d.get_feedback(1.0)
        assert fb.yaw_deg == 0.0  # unchanged

    def test_read_feedback_bad_checksum(self, mock_serial):
        d = _make_driver(mock_serial, GimbalProtocol.CUSTOM)
        mock_serial.in_waiting = 11
        packet = bytearray([0xFF, 0xBB] + [0x80, 0x00] * 4 + [0xFF])
        mock_serial.read.return_value = packet
        fb = d.get_feedback(1.0)
        assert fb.yaw_deg == 0.0

    def test_read_feedback_not_enough_data(self, mock_serial):
        d = _make_driver(mock_serial, GimbalProtocol.CUSTOM)
        mock_serial.in_waiting = 5
        fb = d.get_feedback(1.0)
        assert fb is not None


class TestPelcoDProtocol:
    def test_send_command(self, mock_serial):
        d = _make_driver(mock_serial, GimbalProtocol.PELCO_D)
        d.set_yaw_pitch_rate(50.0, -30.0, 1.0)
        packet = mock_serial.write.call_args[0][0]
        assert packet[0] == 0xFF
        assert len(packet) == 7

    def test_pan_right(self, mock_serial):
        d = _make_driver(mock_serial, GimbalProtocol.PELCO_D)
        d.set_yaw_pitch_rate(10.0, 0.0, 1.0)
        packet = mock_serial.write.call_args[0][0]
        assert packet[3] & 0x02  # Pan right bit

    def test_pan_left(self, mock_serial):
        d = _make_driver(mock_serial, GimbalProtocol.PELCO_D)
        d.set_yaw_pitch_rate(-10.0, 0.0, 1.0)
        packet = mock_serial.write.call_args[0][0]
        assert packet[3] & 0x04  # Pan left bit

    def test_tilt_up(self, mock_serial):
        d = _make_driver(mock_serial, GimbalProtocol.PELCO_D)
        d.set_yaw_pitch_rate(0.0, 10.0, 1.0)
        packet = mock_serial.write.call_args[0][0]
        assert packet[3] & 0x08  # Tilt up bit

    def test_tilt_down(self, mock_serial):
        d = _make_driver(mock_serial, GimbalProtocol.PELCO_D)
        d.set_yaw_pitch_rate(0.0, -10.0, 1.0)
        packet = mock_serial.write.call_args[0][0]
        assert packet[3] & 0x10  # Tilt down bit

    def test_read_feedback_pan(self, mock_serial):
        d = _make_driver(mock_serial, GimbalProtocol.PELCO_D)
        # Pan response: 90.00 degrees = 9000
        pan_resp = bytearray([0xFF, 0x01, 0x00, 0x59, 0x23, 0x28, 0x00])
        tilt_resp = bytearray([0xFF, 0x01, 0x00, 0x5B, 0x00, 0x00, 0x00])
        mock_serial.read.side_effect = [pan_resp, tilt_resp]
        fb = d.get_feedback(1.0)
        assert abs(fb.yaw_deg - 90.0) < 0.5

    def test_read_feedback_query_failure(self, mock_serial):
        d = _make_driver(mock_serial, GimbalProtocol.PELCO_D)
        mock_serial.write.side_effect = Exception("write error")
        fb = d.get_feedback(1.0)
        assert fb is not None  # should not crash


class TestPWMProtocol:
    def test_send_command(self, mock_serial):
        d = _make_driver(mock_serial, GimbalProtocol.PWM)
        d.set_yaw_pitch_rate(10.0, 5.0, 1.0)
        data = mock_serial.write.call_args[0][0]
        assert b"Y" in data
        assert b"P" in data

    def test_position_integration(self, mock_serial):
        d = _make_driver(mock_serial, GimbalProtocol.PWM)
        d.set_yaw_pitch_rate(100.0, 0.0, 0.0)
        d.set_yaw_pitch_rate(100.0, 0.0, 1.0)
        assert abs(d._yaw_deg - 100.0) < 1.0

    def test_feedback_uses_integration(self, mock_serial):
        d = _make_driver(mock_serial, GimbalProtocol.PWM)
        d._yaw_rate_dps = 50.0
        d._last_feedback_time = 0.0
        fb = d.get_feedback(0.0)  # first call sets time
        fb = d.get_feedback(1.0)
        assert abs(fb.yaw_deg - 50.0) < 1.0


class TestPositionLimits:
    def test_yaw_clamped(self, mock_serial):
        d = _make_driver(mock_serial, GimbalProtocol.PWM, yaw_limit_deg=45.0)
        d._yaw_deg = 100.0
        d._clamp_position()
        assert d._yaw_deg == 45.0

    def test_pitch_clamped(self, mock_serial):
        d = _make_driver(mock_serial, GimbalProtocol.PWM, pitch_limit_deg=30.0)
        d._pitch_deg = -50.0
        d._clamp_position()
        assert d._pitch_deg == -30.0


class TestSerialNotOpen:
    def test_command_ignored(self, mock_serial):
        d = _make_driver(mock_serial, GimbalProtocol.CUSTOM)
        mock_serial.is_open = False
        d.set_yaw_pitch_rate(10.0, 5.0, 1.0)
        mock_serial.write.assert_not_called()

    def test_feedback_cached(self, mock_serial):
        d = _make_driver(mock_serial, GimbalProtocol.CUSTOM)
        d._yaw_deg = 42.0
        mock_serial.is_open = False
        fb = d.get_feedback(1.0)
        assert fb.yaw_deg == 42.0


class TestClose:
    def test_close(self, mock_serial):
        d = _make_driver(mock_serial, GimbalProtocol.CUSTOM)
        d.close()
        mock_serial.close.assert_called_once()

    def test_close_already_closed(self, mock_serial):
        d = _make_driver(mock_serial, GimbalProtocol.CUSTOM)
        mock_serial.is_open = False
        d.close()
        mock_serial.close.assert_not_called()
