"""Real robot IMU integration for body motion compensation."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from ..types import BodyState

logger = logging.getLogger(__name__)


class RobotSDKAdapter(ABC):
    """Abstract adapter for different robot SDKs."""

    @abstractmethod
    def get_orientation(self) -> tuple[float, float, float]:
        """Get robot orientation (roll, pitch, yaw) in degrees."""
        pass

    @abstractmethod
    def get_angular_velocity(self) -> tuple[float, float, float]:
        """Get angular velocity (roll_rate, pitch_rate, yaw_rate) in deg/s."""
        pass

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if connection to robot is active."""
        pass


class UnitreeAdapter(RobotSDKAdapter):
    """Adapter for Unitree robot dogs (Go1, Go2, etc.).

    Example usage:
    ```python
    from unitree_legged_sdk import Robot  # Hypothetical SDK

    robot = Robot()
    adapter = UnitreeAdapter(robot)
    imu = RobotIMUProvider(adapter)

    body_state = imu.get_body_state(time.time())
    ```
    """

    def __init__(self, robot_sdk):
        """Initialize Unitree adapter.

        Parameters
        ----------
        robot_sdk : object
            Unitree robot SDK instance
        """
        self.robot = robot_sdk
        logger.info("UnitreeAdapter initialized")

    def get_orientation(self) -> tuple[float, float, float]:
        """Get orientation from Unitree IMU."""
        try:
            # Example API (adjust based on actual SDK)
            imu_data = self.robot.get_imu_data()
            roll = imu_data.rpy[0]  # radians
            pitch = imu_data.rpy[1]  # radians
            yaw = imu_data.rpy[2]  # radians

            # Convert to degrees
            import math

            return (math.degrees(roll), math.degrees(pitch), math.degrees(yaw))
        except Exception as e:
            logger.error("Failed to get orientation from Unitree: %s", e)
            return (0.0, 0.0, 0.0)

    def get_angular_velocity(self) -> tuple[float, float, float]:
        """Get angular velocity from Unitree IMU."""
        try:
            imu_data = self.robot.get_imu_data()
            gyro = imu_data.gyroscope  # rad/s

            # Convert to deg/s
            import math

            return (math.degrees(gyro[0]), math.degrees(gyro[1]), math.degrees(gyro[2]))
        except Exception as e:
            logger.error("Failed to get angular velocity from Unitree: %s", e)
            return (0.0, 0.0, 0.0)

    def is_connected(self) -> bool:
        """Check Unitree connection."""
        try:
            return self.robot.is_connected()
        except Exception:
            return False


class SpotAdapter(RobotSDKAdapter):
    """Adapter for Boston Dynamics Spot.

    Example usage:
    ```python
    import bosdyn.client
    from bosdyn.client.robot_state import RobotStateClient

    sdk = bosdyn.client.create_standard_sdk('rws-tracking')
    robot = sdk.create_robot('192.168.80.3')
    robot.authenticate('user', 'password')

    state_client = robot.ensure_client(RobotStateClient.default_service_name)
    adapter = SpotAdapter(state_client)
    imu = RobotIMUProvider(adapter)
    ```
    """

    def __init__(self, state_client):
        """Initialize Spot adapter.

        Parameters
        ----------
        state_client : RobotStateClient
            Boston Dynamics robot state client
        """
        self.state_client = state_client
        logger.info("SpotAdapter initialized")

    def get_orientation(self) -> tuple[float, float, float]:
        """Get orientation from Spot."""
        try:
            robot_state = self.state_client.get_robot_state()
            orientation = robot_state.kinematic_state.transforms_snapshot.child_to_parent_edge_map[
                "body"
            ].parent_tform_child.rotation

            # Convert quaternion to Euler angles
            import math

            from bosdyn.client.math_helpers import quat_to_eulerZYX

            yaw, pitch, roll = quat_to_eulerZYX(orientation)

            return (math.degrees(roll), math.degrees(pitch), math.degrees(yaw))
        except Exception as e:
            logger.error("Failed to get orientation from Spot: %s", e)
            return (0.0, 0.0, 0.0)

    def get_angular_velocity(self) -> tuple[float, float, float]:
        """Get angular velocity from Spot."""
        try:
            robot_state = self.state_client.get_robot_state()
            angular_vel = robot_state.kinematic_state.velocity_of_body_in_odom.angular

            import math

            return (
                math.degrees(angular_vel.x),
                math.degrees(angular_vel.y),
                math.degrees(angular_vel.z),
            )
        except Exception as e:
            logger.error("Failed to get angular velocity from Spot: %s", e)
            return (0.0, 0.0, 0.0)

    def is_connected(self) -> bool:
        """Check Spot connection."""
        try:
            self.state_client.get_robot_state()
            return True
        except Exception:
            return False


class GenericSerialIMU(RobotSDKAdapter):
    """Generic serial IMU adapter for custom hardware.

    Supports common IMU modules (MPU6050, BNO055, etc.) via serial.

    Expected serial format (ASCII):
    "R:<roll>,P:<pitch>,Y:<yaw>,GX:<gx>,GY:<gy>,GZ:<gz>\\n"

    Example:
    "R:1.23,P:-0.45,Y:90.12,GX:0.5,GY:-0.2,GZ:1.8\\n"
    """

    def __init__(self, port: str, baudrate: int = 115200):
        """Initialize generic serial IMU.

        Parameters
        ----------
        port : str
            Serial port (e.g., "COM4", "/dev/ttyUSB1")
        baudrate : int
            Baud rate (default: 115200)
        """
        self.port = port
        self.baudrate = baudrate
        self._serial = None
        self._last_orientation = (0.0, 0.0, 0.0)
        self._last_angular_vel = (0.0, 0.0, 0.0)

        self._connect()
        logger.info("GenericSerialIMU initialized: %s @ %d", port, baudrate)

    def _connect(self) -> None:
        """Establish serial connection."""
        try:
            import serial
        except ImportError as e:
            raise ImportError("pyserial is required. Install with: pip install pyserial") from e

        try:
            self._serial = serial.Serial(port=self.port, baudrate=self.baudrate, timeout=0.1)
            logger.info("Serial IMU connected: %s", self.port)
        except serial.SerialException as e:
            logger.error("Failed to connect to IMU: %s", e)
            raise

    def get_orientation(self) -> tuple[float, float, float]:
        """Read orientation from serial IMU."""
        self._read_data()
        return self._last_orientation

    def get_angular_velocity(self) -> tuple[float, float, float]:
        """Read angular velocity from serial IMU."""
        self._read_data()
        return self._last_angular_vel

    def _read_data(self) -> None:
        """Read and parse IMU data from serial."""
        if self._serial is None or not self._serial.is_open:
            return

        try:
            if self._serial.in_waiting > 0:
                line = self._serial.readline().decode("ascii").strip()
                self._parse_line(line)
        except Exception as e:
            logger.warning("Failed to read IMU data: %s", e)

    def _parse_line(self, line: str) -> None:
        """Parse IMU data line.

        Expected format: "R:<roll>,P:<pitch>,Y:<yaw>,GX:<gx>,GY:<gy>,GZ:<gz>"
        """
        try:
            parts = line.split(",")
            data = {}
            for part in parts:
                key, value = part.split(":")
                data[key] = float(value)

            self._last_orientation = (data.get("R", 0.0), data.get("P", 0.0), data.get("Y", 0.0))
            self._last_angular_vel = (data.get("GX", 0.0), data.get("GY", 0.0), data.get("GZ", 0.0))
        except Exception as e:
            logger.warning("Failed to parse IMU line '%s': %s", line, e)

    def is_connected(self) -> bool:
        """Check serial connection."""
        return self._serial is not None and self._serial.is_open

    def close(self) -> None:
        """Close serial connection."""
        if self._serial is not None and self._serial.is_open:
            self._serial.close()
            logger.info("Serial IMU closed: %s", self.port)

    def __del__(self):
        """Cleanup."""
        self.close()


class RobotIMUProvider:
    """Real robot IMU provider for body motion compensation.

    Wraps different robot SDK adapters and provides a unified interface
    compatible with the BodyMotionProvider protocol.

    Example usage:
    ```python
    # Option 1: Unitree robot
    from unitree_legged_sdk import Robot
    robot = Robot()
    adapter = UnitreeAdapter(robot)
    imu = RobotIMUProvider(adapter)

    # Option 2: Generic serial IMU
    adapter = GenericSerialIMU(port="COM4", baudrate=115200)
    imu = RobotIMUProvider(adapter)

    # Use in pipeline
    pipeline = VisionGimbalPipeline(
        # ...
        body_motion_provider=imu,
        # ...
    )
    ```
    """

    def __init__(
        self, adapter: RobotSDKAdapter, enable_filtering: bool = True, filter_alpha: float = 0.3
    ):
        """Initialize robot IMU provider.

        Parameters
        ----------
        adapter : RobotSDKAdapter
            Robot SDK adapter (Unitree, Spot, or GenericSerial)
        enable_filtering : bool
            Enable low-pass filtering on IMU data (default: True)
        filter_alpha : float
            Filter coefficient (0-1, higher = less filtering)
        """
        self.adapter = adapter
        self.enable_filtering = enable_filtering
        self.filter_alpha = filter_alpha

        self._filtered_orientation = (0.0, 0.0, 0.0)
        self._filtered_angular_vel = (0.0, 0.0, 0.0)
        self._initialized = False

        logger.info(
            "RobotIMUProvider initialized (filtering=%s, alpha=%.2f)",
            enable_filtering,
            filter_alpha,
        )

    def get_body_state(self, timestamp: float) -> BodyState | None:
        """Get current body state from robot IMU.

        Parameters
        ----------
        timestamp : float
            Current timestamp

        Returns
        -------
        Optional[BodyState]
            Body state (orientation + angular velocity), or None if unavailable
        """
        if not self.adapter.is_connected():
            logger.warning("Robot not connected, returning None")
            return None

        try:
            # Read raw data
            roll, pitch, yaw = self.adapter.get_orientation()
            roll_rate, pitch_rate, yaw_rate = self.adapter.get_angular_velocity()

            # Apply filtering
            if self.enable_filtering:
                if not self._initialized:
                    self._filtered_orientation = (roll, pitch, yaw)
                    self._filtered_angular_vel = (roll_rate, pitch_rate, yaw_rate)
                    self._initialized = True
                else:
                    alpha = self.filter_alpha
                    self._filtered_orientation = (
                        alpha * roll + (1 - alpha) * self._filtered_orientation[0],
                        alpha * pitch + (1 - alpha) * self._filtered_orientation[1],
                        alpha * yaw + (1 - alpha) * self._filtered_orientation[2],
                    )
                    self._filtered_angular_vel = (
                        alpha * roll_rate + (1 - alpha) * self._filtered_angular_vel[0],
                        alpha * pitch_rate + (1 - alpha) * self._filtered_angular_vel[1],
                        alpha * yaw_rate + (1 - alpha) * self._filtered_angular_vel[2],
                    )

                roll, pitch, yaw = self._filtered_orientation
                roll_rate, pitch_rate, yaw_rate = self._filtered_angular_vel

            return BodyState(
                timestamp=timestamp,
                roll_deg=roll,
                pitch_deg=pitch,
                yaw_deg=yaw,
                roll_rate_dps=roll_rate,
                pitch_rate_dps=pitch_rate,
                yaw_rate_dps=yaw_rate,
            )

        except Exception as e:
            logger.error("Failed to get body state: %s", e)
            return None
