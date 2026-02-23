"""Serial gimbal driver for real hardware integration."""

from __future__ import annotations

import logging
from enum import Enum

from ..types import GimbalFeedback

logger = logging.getLogger(__name__)


class GimbalProtocol(Enum):
    """Supported gimbal communication protocols."""

    PWM = "pwm"  # PWM servo control
    PELCO_D = "pelco-d"  # PELCO-D protocol
    PELCO_P = "pelco-p"  # PELCO-P protocol
    CUSTOM = "custom"  # Custom binary protocol


class SerialGimbalDriver:
    """Serial port gimbal driver for real hardware.

    Supports multiple protocols:
    - PWM: Standard servo control (50Hz PWM)
    - PELCO-D/P: Industry standard PTZ protocols
    - Custom: User-defined binary protocol

    Example usage:
    ```python
    driver = SerialGimbalDriver(
        port="COM3",
        baudrate=115200,
        protocol=GimbalProtocol.CUSTOM
    )
    driver.set_yaw_pitch_rate(10.0, 5.0, time.time())
    feedback = driver.get_feedback(time.time())
    ```
    """

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        protocol: GimbalProtocol = GimbalProtocol.CUSTOM,
        timeout: float = 0.1,
        address: int = 0x01,
        yaw_limit_deg: float = 180.0,
        pitch_limit_deg: float = 90.0,
    ):
        """Initialize serial gimbal driver.

        Parameters
        ----------
        port : str
            Serial port path (e.g., "COM3" on Windows, "/dev/ttyUSB0" on Linux)
        baudrate : int
            Baud rate (default: 115200)
        protocol : GimbalProtocol
            Communication protocol
        timeout : float
            Serial read timeout in seconds
        address : int
            Device address for PELCO-D protocol (default: 0x01)
        yaw_limit_deg : float
            Yaw position limit in degrees (default: ±180)
        pitch_limit_deg : float
            Pitch position limit in degrees (default: ±90)
        """
        self.port = port
        self.baudrate = baudrate
        self.protocol = protocol
        self.timeout = timeout
        self._address = address
        self._yaw_limit = abs(yaw_limit_deg)
        self._pitch_limit = abs(pitch_limit_deg)

        self._serial = None
        self._yaw_deg = 0.0
        self._pitch_deg = 0.0
        self._yaw_rate_dps = 0.0
        self._pitch_rate_dps = 0.0
        self._last_feedback_time: float | None = None
        self._last_cmd_time: float | None = None

        self._connect()

        logger.info(
            "SerialGimbalDriver initialized: port=%s, baudrate=%d, protocol=%s",
            port,
            baudrate,
            protocol.value,
        )

    def _connect(self) -> None:
        """Establish serial connection."""
        try:
            import serial
        except ImportError as e:
            raise ImportError(
                "pyserial is required for SerialGimbalDriver. Install it with: pip install pyserial"
            ) from e

        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                write_timeout=self.timeout,
            )
            logger.info("Serial connection established: %s", self.port)
        except serial.SerialException as e:
            logger.error("Failed to open serial port %s: %s", self.port, e)
            raise

    def set_yaw_pitch_rate(
        self, yaw_rate_dps: float, pitch_rate_dps: float, timestamp: float
    ) -> None:
        """Send rate command to gimbal.

        Parameters
        ----------
        yaw_rate_dps : float
            Yaw rate command in degrees per second
        pitch_rate_dps : float
            Pitch rate command in degrees per second
        timestamp : float
            Command timestamp
        """
        if self._serial is None or not self._serial.is_open:
            logger.warning("Serial port not open, command ignored")
            return

        # Integrate position from last command time
        if self._last_cmd_time is not None:
            dt = max(timestamp - self._last_cmd_time, 0.0)
            self._yaw_deg += self._yaw_rate_dps * dt
            self._pitch_deg += self._pitch_rate_dps * dt
            self._clamp_position()
        self._last_cmd_time = timestamp

        # Store commanded rates
        self._yaw_rate_dps = yaw_rate_dps
        self._pitch_rate_dps = pitch_rate_dps

        # Send command based on protocol
        if self.protocol == GimbalProtocol.CUSTOM:
            self._send_custom_command(yaw_rate_dps, pitch_rate_dps)
        elif self.protocol == GimbalProtocol.PELCO_D:
            self._send_pelco_d_command(yaw_rate_dps, pitch_rate_dps)
        elif self.protocol == GimbalProtocol.PWM:
            self._send_pwm_command(yaw_rate_dps, pitch_rate_dps, timestamp)
        else:
            logger.warning("Unsupported protocol: %s", self.protocol)

        logger.debug(
            "Sent command: yaw=%.2f dps, pitch=%.2f dps, t=%.3f",
            yaw_rate_dps,
            pitch_rate_dps,
            timestamp,
        )

    def get_feedback(self, timestamp: float) -> GimbalFeedback:
        """Read gimbal feedback (position and rate).

        Parameters
        ----------
        timestamp : float
            Current timestamp

        Returns
        -------
        GimbalFeedback
            Current gimbal state
        """
        if self._serial is None or not self._serial.is_open:
            logger.warning("Serial port not open, returning cached feedback")
            return GimbalFeedback(
                timestamp=timestamp,
                yaw_deg=self._yaw_deg,
                pitch_deg=self._pitch_deg,
                yaw_rate_dps=self._yaw_rate_dps,
                pitch_rate_dps=self._pitch_rate_dps,
            )

        # Read feedback based on protocol
        if self.protocol == GimbalProtocol.CUSTOM:
            self._read_custom_feedback()
        elif self.protocol == GimbalProtocol.PELCO_D:
            self._read_pelco_d_feedback()
        elif self.protocol == GimbalProtocol.PWM:
            # PWM typically doesn't provide feedback, use integration
            self._integrate_position(timestamp)

        self._last_feedback_time = timestamp

        logger.debug(
            "Feedback: yaw=%.2f°, pitch=%.2f°, rates=(%.2f, %.2f) dps, t=%.3f",
            self._yaw_deg,
            self._pitch_deg,
            self._yaw_rate_dps,
            self._pitch_rate_dps,
            timestamp,
        )

        return GimbalFeedback(
            timestamp=timestamp,
            yaw_deg=self._yaw_deg,
            pitch_deg=self._pitch_deg,
            yaw_rate_dps=self._yaw_rate_dps,
            pitch_rate_dps=self._pitch_rate_dps,
        )

    def _send_custom_command(self, yaw_rate: float, pitch_rate: float) -> None:
        """Send command using custom binary protocol.

        Custom protocol format (example):
        [0xFF, 0xAA, yaw_high, yaw_low, pitch_high, pitch_low, checksum]

        Rates are encoded as int16 (±32767 = ±180 dps)
        """
        # Convert rates to int16
        yaw_int = int(max(-32767, min(32767, yaw_rate / 180.0 * 32767)))
        pitch_int = int(max(-32767, min(32767, pitch_rate / 180.0 * 32767)))

        # Build packet
        packet = bytearray(
            [
                0xFF,  # Header byte 1
                0xAA,  # Header byte 2
                (yaw_int >> 8) & 0xFF,  # Yaw high byte
                yaw_int & 0xFF,  # Yaw low byte
                (pitch_int >> 8) & 0xFF,  # Pitch high byte
                pitch_int & 0xFF,  # Pitch low byte
            ]
        )

        # Add checksum (simple XOR)
        checksum = 0
        for byte in packet[2:]:
            checksum ^= byte
        packet.append(checksum)

        # Send
        self._serial.write(packet)

    def _send_pelco_d_command(self, yaw_rate: float, pitch_rate: float) -> None:
        """Send command using PELCO-D protocol.

        PELCO-D format:
        [Sync, Address, Command1, Command2, Data1, Data2, Checksum]
        """
        address = 0x01  # Default camera address

        # Determine command bytes
        cmd1 = 0x00
        cmd2 = 0x00

        # Pan (yaw) control
        if abs(yaw_rate) > 0.5:
            if yaw_rate > 0:
                cmd2 |= 0x02  # Pan right
            else:
                cmd2 |= 0x04  # Pan left

        # Tilt (pitch) control
        if abs(pitch_rate) > 0.5:
            if pitch_rate > 0:
                cmd2 |= 0x08  # Tilt up
            else:
                cmd2 |= 0x10  # Tilt down

        # Speed (0-63)
        pan_speed = int(min(63, abs(yaw_rate) / 180.0 * 63))
        tilt_speed = int(min(63, abs(pitch_rate) / 180.0 * 63))

        # Build packet
        packet = bytearray(
            [
                0xFF,  # Sync
                address,  # Address
                cmd1,  # Command 1
                cmd2,  # Command 2
                pan_speed,  # Pan speed
                tilt_speed,  # Tilt speed
            ]
        )

        # Checksum (sum of bytes 1-5, modulo 256)
        checksum = sum(packet[1:]) % 256
        packet.append(checksum)

        self._serial.write(packet)

    def _send_pwm_command(
        self, yaw_rate: float, pitch_rate: float, timestamp: float = 0.0
    ) -> None:
        """Send PWM servo command.

        Note: This requires a PWM controller (e.g., Arduino, PCA9685).
        The serial protocol here is application-specific.

        Parameters
        ----------
        yaw_rate : float
            Yaw rate in degrees per second.
        pitch_rate : float
            Pitch rate in degrees per second.
        timestamp : float
            Current timestamp, used to compute dt for position integration.
        """
        # Current integrated position is already updated in set_yaw_pitch_rate
        command = f"Y{self._yaw_deg:.2f},P{self._pitch_deg:.2f}\n"
        self._serial.write(command.encode("ascii"))

    def _read_custom_feedback(self) -> None:
        """Read feedback using custom protocol.

        Expected format:
        [0xFF, 0xBB, yaw_h, yaw_l, pitch_h, pitch_l, rate_yaw_h, rate_yaw_l,
         rate_pitch_h, rate_pitch_l, checksum]
        """
        if self._serial.in_waiting < 11:
            return  # Not enough data

        # Read packet
        packet = self._serial.read(11)

        if len(packet) != 11 or packet[0] != 0xFF or packet[1] != 0xBB:
            logger.warning("Invalid feedback packet header")
            return

        # Verify checksum
        checksum = 0
        for byte in packet[2:10]:
            checksum ^= byte

        if checksum != packet[10]:
            logger.warning("Feedback checksum mismatch")
            return

        # Parse data
        yaw_int = (packet[2] << 8) | packet[3]
        pitch_int = (packet[4] << 8) | packet[5]
        rate_yaw_int = (packet[6] << 8) | packet[7]
        rate_pitch_int = (packet[8] << 8) | packet[9]

        # Convert from int16 to float
        self._yaw_deg = (yaw_int - 32768) / 32767.0 * 180.0
        self._pitch_deg = (pitch_int - 32768) / 32767.0 * 180.0
        self._yaw_rate_dps = (rate_yaw_int - 32768) / 32767.0 * 180.0
        self._pitch_rate_dps = (rate_pitch_int - 32768) / 32767.0 * 180.0

    def _read_pelco_d_feedback(self) -> None:
        """Read feedback using PELCO-D protocol.

        Sends PELCO-D Query Pan/Tilt Position commands and parses responses.

        Query Pan Position:  [0xFF, addr, 0x00, 0x51, 0x00, 0x00, checksum]
        Query Tilt Position: [0xFF, addr, 0x00, 0x53, 0x00, 0x00, checksum]

        Response format (7 bytes):
        [0xFF, addr, 0x00, 0x59/0x5B, pos_high, pos_low, checksum]

        Position is encoded as uint16: 0-35999 representing 0.00-359.99 degrees.
        """
        addr = self._address

        # --- Query Pan Position ---
        pan_query = bytearray([0xFF, addr, 0x00, 0x51, 0x00, 0x00])
        pan_query.append(sum(pan_query[1:]) % 256)
        try:
            self._serial.write(pan_query)
            pan_resp = self._serial.read(7)
            if len(pan_resp) == 7 and pan_resp[0] == 0xFF and pan_resp[3] == 0x59:
                pan_pos = (pan_resp[4] << 8) | pan_resp[5]
                # Convert 0-35999 to -180..+180 degrees
                pan_deg = pan_pos / 100.0
                if pan_deg > 180.0:
                    pan_deg -= 360.0
                self._yaw_deg = pan_deg
        except Exception as e:
            logger.debug("PELCO-D pan query failed: %s", e)

        # --- Query Tilt Position ---
        tilt_query = bytearray([0xFF, addr, 0x00, 0x53, 0x00, 0x00])
        tilt_query.append(sum(tilt_query[1:]) % 256)
        try:
            self._serial.write(tilt_query)
            tilt_resp = self._serial.read(7)
            if len(tilt_resp) == 7 and tilt_resp[0] == 0xFF and tilt_resp[3] == 0x5B:
                tilt_pos = (tilt_resp[4] << 8) | tilt_resp[5]
                # Convert 0-35999 to -90..+90 degrees
                tilt_deg = tilt_pos / 100.0
                if tilt_deg > 180.0:
                    tilt_deg -= 360.0
                self._pitch_deg = tilt_deg
        except Exception as e:
            logger.debug("PELCO-D tilt query failed: %s", e)

    def _integrate_position(self, timestamp: float) -> None:
        """Integrate commanded rates to estimate position (when no feedback)."""
        if self._last_feedback_time is None:
            return

        dt = timestamp - self._last_feedback_time
        if dt <= 0:
            return

        self._yaw_deg += self._yaw_rate_dps * dt
        self._pitch_deg += self._pitch_rate_dps * dt
        self._clamp_position()

    def _clamp_position(self) -> None:
        """Clamp position to configured limits."""
        self._yaw_deg = max(-self._yaw_limit, min(self._yaw_limit, self._yaw_deg))
        self._pitch_deg = max(-self._pitch_limit, min(self._pitch_limit, self._pitch_deg))

    def close(self) -> None:
        """Close serial connection."""
        if self._serial is not None and self._serial.is_open:
            self._serial.close()
            logger.info("Serial connection closed: %s", self.port)

    def __del__(self):
        """Cleanup on deletion."""
        self.close()
