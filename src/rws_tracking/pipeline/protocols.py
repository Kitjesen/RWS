"""Pipeline 消费的外部组件协议。

仅包含 pipeline 需要但不宜放在各层 interfaces.py 中的 Protocol
（例如 FrameBuffer/FrameAnnotator 的实现在 api/ 中，但 api/ 有 Flask
等重依赖，pipeline 不应触发 api 包的顶层 import）。
"""

from __future__ import annotations

from typing import Protocol

from ..types import Track


class FrameBufferProtocol(Protocol):
    """帧缓冲区：接收标注后的帧，供视频流读取。"""

    def push(self, frame: object, timestamp: float) -> None: ...


class FrameAnnotatorProtocol(Protocol):
    """帧标注器：在原始帧上绘制检测框、准心、状态信息。"""

    def annotate(
        self,
        frame: object,
        tracks: list[Track],
        selected_id: int | None = None,
        status_text: str = "",
    ) -> object: ...
