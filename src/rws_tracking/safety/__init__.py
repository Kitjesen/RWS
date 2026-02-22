"""安全系统模块 — 禁射区、安全联锁、操作员覆盖、IFF识别。

子模块：
    no_fire_zone : 禁射区管理
    interlock    : 安全联锁（硬件/软件）
    manager      : 安全管理器（统一入口）
    iff          : 敌我识别过滤器
"""

from .iff import IFFChecker, IFFResult
from .interlock import SafetyInterlock, SafetyInterlockConfig
from .manager import SafetyManager, SafetyManagerConfig
from .no_fire_zone import NoFireZoneManager

__all__ = [
    "IFFChecker",
    "IFFResult",
    "NoFireZoneManager",
    "SafetyInterlock",
    "SafetyInterlockConfig",
    "SafetyManager",
    "SafetyManagerConfig",
]
