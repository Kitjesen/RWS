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
        """
        self.port = port
        self.baudrate = baudrate
        self.protocol = protocol
        self.timeout = timeout

        self._serial = None
        self._yaw_deg = 0.0
        self._pitch_deg = 0.0
        self._yaw_rate_dps = 0.0
        self._pitch_rate_dps = 0.0
        self._last_feedback_time = 0.0

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

        # Store commanded rates
        self._yaw_rate_dps = yaw_rate_dps
        self._pitch_rate_dps = pitch_rate_dps

        # Send command based on protocol
        if self.protocol == GimbalProtocol.CUSTOM:
            self._send_custom_command(yaw_rate_dps, pitch_rate_dps)
        elif self.protocol == GimbalProtocol.PELCO_D:
            self._send_pelco_d_command(yaw_rate_dps, pitch_rate_dps)
        elif self.protocol == GimbalProtocol.PWM:
            self._send_pwm_command(yaw_rate_dps, pitch_rate_dps)
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

    def _send_pwm_command(self, yaw_rate: float, pitch_rate: float) -> None:
        """Send PWM servo command.

        Note: This requires a PWM controller (e.g., Arduino, PCA9685).
        The serial protocol here is application-specific.
        """
        # Example: Send ASCII command "Y<angle>,P<angle>\n"
        # This assumes an Arduino sketch that parses this format

        # Integrate rates to get target angles (simplified)
        dt = 0.033  # Assume 30Hz
        target_yaw = self._yaw_deg + yaw_rate * dt
        target_pitch = self._pitch_deg + pitch_rate * dt

        command = f"Y{target_yaw:.2f},P{target_pitch:.2f}\n"
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

        Note: PELCO-D typically doesn't provide continuous feedback.
        This is a placeholder for query-response implementations.
        """
        # PELCO-D query commands exist but are not standardized
        # Most implementations don't provide real-time feedback
        # Fall back to integration
        pass

    def _integrate_position(self, timestamp: float) -> None:
        """Integrate commanded rates to estimate position (when no feedback)."""
        if self._last_feedback_time == 0.0:
            self._last_feedback_time = timestamp
            return

        dt = timestamp - self._last_feedback_time
        if dt <= 0:
            return

        self._yaw_deg += self._yaw_rate_dps * dt
        self._pitch_deg += self._pitch_rate_dps * dt

        # Clamp to reasonable limits
        self._yaw_deg = max(-180, min(180, self._yaw_deg))
        self._pitch_deg = max(-90, min(90, self._pitch_deg))

    def close(self) -> None:
        """Close serial connection."""
        if self._serial is not None and self._serial.is_open:
            self._serial.close()
            logger.info("Serial connection closed: %s", self.port)

    def __del__(self):
        """Cleanup on deletion."""
        self.close()
