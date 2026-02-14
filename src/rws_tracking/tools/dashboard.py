"""实时可视化仪表盘 — 基于 cv2 的轻量级遥测可视化"""
from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional

import cv2
import numpy as np


class RealtimeDashboard:
    """实时仪表盘

    显示内容：
    - 误差曲线（yaw/pitch）
    - 状态机可视化
    - 实时指标（lock_rate, avg_error, switches）
    - 命令速率曲线
    """

    def __init__(
        self,
        telemetry_logger: object,
        window_size_s: float = 10.0,
        width: int = 800,
        height: int = 600,
    ) -> None:
        """
        参数：
        - telemetry_logger: InMemoryTelemetryLogger 实例
        - window_size_s: 时间窗口大小（秒）
        - width, height: 画布尺寸
        """
        self._logger = telemetry_logger
        self._window_size_s = window_size_s
        self._width = width
        self._height = height

        # 历史数据缓冲区（最近 N 个控制事件）
        max_events = int(window_size_s * 30)  # 假设 30Hz
        self._history: deque = deque(maxlen=max_events)

        # 上次更新的事件索引
        self._last_event_idx = 0

    def update(self, timestamp: float) -> None:
        """从 logger 拉取最新事件"""
        events = self._logger.events

        # 只处理新事件
        for i in range(self._last_event_idx, len(events)):
            event = events[i]
            if event.event_type == "control":
                self._history.append(event)

        self._last_event_idx = len(events)

    def render(self) -> np.ndarray:
        """生成仪表盘图像"""
        canvas = np.zeros((self._height, self._width, 3), dtype=np.uint8)

        # 布局：
        # +-------------------+-------------------+
        # |   误差曲线 (上)    |   命令曲线 (上)    |
        # +-------------------+-------------------+
        # | 状态机 (左下)      | 实时指标 (右下)    |
        # +-------------------+-------------------+

        w2 = self._width // 2
        h2 = self._height // 2

        self._draw_error_plot(canvas, 0, 0, w2, h2)
        self._draw_command_plot(canvas, w2, 0, w2, h2)
        self._draw_state_machine(canvas, 0, h2, w2, h2)
        self._draw_metrics(canvas, w2, h2, w2, h2)

        return canvas

    def show(self, window_name: str = "Dashboard") -> None:
        """显示仪表盘窗口"""
        img = self.render()
        cv2.imshow(window_name, img)

    # ------------------------------------------------------------------
    # 绘图子模块
    # ------------------------------------------------------------------

    def _draw_error_plot(
        self, canvas: np.ndarray, x: int, y: int, w: int, h: int
    ) -> None:
        """绘制误差曲线"""
        if len(self._history) < 2:
            cv2.putText(
                canvas, "Waiting for data...", (x + 10, y + h // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 100, 100), 1,
            )
            return

        times = [e.timestamp for e in self._history]
        yaw_errors = [e.payload.get("yaw_error_deg", 0.0) for e in self._history]
        pitch_errors = [e.payload.get("pitch_error_deg", 0.0) for e in self._history]

        t_min, t_max = times[0], times[-1]
        if t_max - t_min < 0.1:
            return

        # 背景 + 零线
        cv2.rectangle(canvas, (x, y), (x + w, y + h), (30, 30, 30), -1)
        cv2.line(canvas, (x, y + h // 2), (x + w, y + h // 2), (50, 50, 50), 1)

        y_range = 15.0  # ±15度
        for i in range(len(times) - 1):
            x1 = int(x + (times[i] - t_min) / (t_max - t_min) * w)
            x2 = int(x + (times[i + 1] - t_min) / (t_max - t_min) * w)

            # Yaw 误差（红色）
            y1 = int(y + h // 2 - yaw_errors[i] / y_range * (h // 2 - 10))
            y2 = int(y + h // 2 - yaw_errors[i + 1] / y_range * (h // 2 - 10))
            y1 = max(y + 5, min(y + h - 5, y1))
            y2 = max(y + 5, min(y + h - 5, y2))
            cv2.line(canvas, (x1, y1), (x2, y2), (0, 0, 255), 2)

            # Pitch 误差（绿色）
            y1 = int(y + h // 2 - pitch_errors[i] / y_range * (h // 2 - 10))
            y2 = int(y + h // 2 - pitch_errors[i + 1] / y_range * (h // 2 - 10))
            y1 = max(y + 5, min(y + h - 5, y1))
            y2 = max(y + 5, min(y + h - 5, y2))
            cv2.line(canvas, (x1, y1), (x2, y2), (0, 255, 0), 2)

        # 标签
        cv2.putText(
            canvas, "Error (deg)", (x + 10, y + 20),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1,
        )
        cv2.putText(
            canvas, "Yaw", (x + 10, y + 40),
            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1,
        )
        cv2.putText(
            canvas, "Pitch", (x + 60, y + 40),
            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1,
        )
        cv2.putText(
            canvas, f"+{y_range:.0f}", (x + w - 30, y + 15),
            cv2.FONT_HERSHEY_SIMPLEX, 0.3, (150, 150, 150), 1,
        )
        cv2.putText(
            canvas, f"-{y_range:.0f}", (x + w - 30, y + h - 5),
            cv2.FONT_HERSHEY_SIMPLEX, 0.3, (150, 150, 150), 1,
        )

    def _draw_command_plot(
        self, canvas: np.ndarray, x: int, y: int, w: int, h: int
    ) -> None:
        """绘制命令速率曲线"""
        if len(self._history) < 2:
            return

        times = [e.timestamp for e in self._history]
        yaw_cmds = [e.payload.get("yaw_cmd_dps", 0.0) for e in self._history]
        pitch_cmds = [e.payload.get("pitch_cmd_dps", 0.0) for e in self._history]

        t_min, t_max = times[0], times[-1]
        if t_max - t_min < 0.1:
            return

        cv2.rectangle(canvas, (x, y), (x + w, y + h), (30, 30, 30), -1)
        cv2.line(canvas, (x, y + h // 2), (x + w, y + h // 2), (50, 50, 50), 1)

        cmd_range = 180.0  # ±180 dps
        for i in range(len(times) - 1):
            x1 = int(x + (times[i] - t_min) / (t_max - t_min) * w)
            x2 = int(x + (times[i + 1] - t_min) / (t_max - t_min) * w)

            # Yaw 命令（黄色）
            y1 = int(y + h // 2 - yaw_cmds[i] / cmd_range * (h // 2 - 10))
            y2 = int(y + h // 2 - yaw_cmds[i + 1] / cmd_range * (h // 2 - 10))
            y1 = max(y + 5, min(y + h - 5, y1))
            y2 = max(y + 5, min(y + h - 5, y2))
            cv2.line(canvas, (x1, y1), (x2, y2), (0, 255, 255), 2)

            # Pitch 命令（青色）
            y1 = int(y + h // 2 - pitch_cmds[i] / cmd_range * (h // 2 - 10))
            y2 = int(y + h // 2 - pitch_cmds[i + 1] / cmd_range * (h // 2 - 10))
            y1 = max(y + 5, min(y + h - 5, y1))
            y2 = max(y + 5, min(y + h - 5, y2))
            cv2.line(canvas, (x1, y1), (x2, y2), (255, 255, 0), 2)

        cv2.putText(
            canvas, "Command (dps)", (x + 10, y + 20),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1,
        )
        cv2.putText(
            canvas, "Yaw", (x + 10, y + 40),
            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1,
        )
        cv2.putText(
            canvas, "Pitch", (x + 60, y + 40),
            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 0), 1,
        )

    def _draw_state_machine(
        self, canvas: np.ndarray, x: int, y: int, w: int, h: int
    ) -> None:
        """绘制状态机可视化"""
        if len(self._history) == 0:
            return

        cv2.rectangle(canvas, (x, y), (x + w, y + h), (20, 20, 20), -1)

        # 当前状态
        current_state = self._history[-1].payload.get("state", 0.0)
        state_names = ["SEARCH", "TRACK", "LOCK", "LOST"]
        state_colors = [
            (100, 100, 100), (0, 255, 255), (0, 255, 0), (0, 0, 255),
        ]

        state_idx = int(current_state)
        if 0 <= state_idx < len(state_names):
            state_name = state_names[state_idx]
            state_color = state_colors[state_idx]
        else:
            state_name = "UNKNOWN"
            state_color = (255, 255, 255)

        # 大字显示当前状态
        cv2.putText(
            canvas, "STATE", (x + 10, y + 30),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1,
        )
        cv2.putText(
            canvas, state_name, (x + 10, y + 70),
            cv2.FONT_HERSHEY_SIMPLEX, 1.2, state_color, 2,
        )

        # 状态历史（窗口内的状态分布）
        states = [e.payload.get("state", 0.0) for e in self._history]
        state_counts = [0, 0, 0, 0]
        for s in states:
            idx = int(s)
            if 0 <= idx < 4:
                state_counts[idx] += 1

        total = sum(state_counts)
        if total > 0:
            y_offset = y + 120
            for i, (name, count, color) in enumerate(
                zip(state_names, state_counts, state_colors)
            ):
                pct = count / total * 100
                cv2.putText(
                    canvas, f"{name}: {pct:.1f}%", (x + 10, y_offset + i * 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1,
                )

    def _draw_metrics(
        self, canvas: np.ndarray, x: int, y: int, w: int, h: int
    ) -> None:
        """绘制实时指标"""
        cv2.rectangle(canvas, (x, y), (x + w, y + h), (20, 20, 20), -1)

        metrics = self._logger.snapshot_metrics()

        cv2.putText(
            canvas, "METRICS", (x + 10, y + 30),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1,
        )

        y_offset = y + 60
        line_height = 30

        # Lock Rate
        lock_rate = metrics.get("lock_rate", 0.0) * 100
        color = (
            (0, 255, 0) if lock_rate > 50
            else (0, 255, 255) if lock_rate > 20
            else (0, 0, 255)
        )
        cv2.putText(
            canvas, f"Lock Rate: {lock_rate:.1f}%", (x + 10, y_offset),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1,
        )

        # Avg Error
        avg_error = metrics.get("avg_abs_error_deg", 0.0)
        color = (
            (0, 255, 0) if avg_error < 2.0
            else (0, 255, 255) if avg_error < 5.0
            else (0, 0, 255)
        )
        cv2.putText(
            canvas, f"Avg Error: {avg_error:.2f} deg",
            (x + 10, y_offset + line_height),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1,
        )

        # Switches
        switches = metrics.get("switches_per_min", 0.0)
        color = (
            (0, 255, 0) if switches < 5
            else (0, 255, 255) if switches < 10
            else (0, 0, 255)
        )
        cv2.putText(
            canvas, f"Switches: {switches:.1f} /min",
            (x + 10, y_offset + line_height * 2),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1,
        )

        # 事件计数
        total_events = len(self._logger.events)
        cv2.putText(
            canvas, f"Events: {total_events}",
            (x + 10, y_offset + line_height * 3),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1,
        )

        # 当前误差（最新值）
        if len(self._history) > 0:
            latest = self._history[-1].payload
            yaw_err = latest.get("yaw_error_deg", 0.0)
            pitch_err = latest.get("pitch_error_deg", 0.0)
            cv2.putText(
                canvas, f"Yaw Err: {yaw_err:+.2f} deg",
                (x + 10, y_offset + line_height * 4),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1,
            )
            cv2.putText(
                canvas, f"Pitch Err: {pitch_err:+.2f} deg",
                (x + 10, y_offset + line_height * 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1,
            )
