"""威胁评估与交战排序模块。

职责（单一）：
    对所有被跟踪目标进行威胁评估打分，按优先级排序，
    输出交战队列指导多目标瞄准和射击顺序。

威胁评估模型：
    threat_score = Σ wᵢ · fᵢ(target)
    其中各分量：
    - distance_score:  距离越近威胁越高 (指数衰减)
    - velocity_score:  接近速度越高威胁越高
    - class_score:     不同类别固有威胁等级
    - heading_score:   目标朝向我方程度 (余弦相似度)
    - size_score:      目标越大威胁越高

交战排序策略：
    1. "threat_first"  — 按威胁评分降序
    2. "nearest_first" — 按距离升序
    3. "sector_sweep"  — 按角度扇区顺序扫清
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

from ..types import ThreatAssessment, Track

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ThreatWeights:
    """威胁评估各分量权重, 总和建议为 1.0。"""

    distance: float = 0.30
    velocity: float = 0.25
    class_threat: float = 0.20
    heading: float = 0.15
    size: float = 0.10


@dataclass(frozen=True)
class EngagementConfig:
    """交战排序配置。

    Attributes
    ----------
    weights : ThreatWeights
        各威胁分量权重。
    strategy : str
        排序策略: "threat_first" | "nearest_first" | "sector_sweep"。
    class_threat_levels : dict[str, float]
        目标类别 → 威胁等级 (0–1), 例如 {"person": 0.8, "vehicle": 1.0}。
    max_engagement_range_m : float
        最大交战距离 (m)，超过此距离的目标不参与评估。
    min_threat_threshold : float
        最低威胁阈值，低于此值的目标不纳入交战队列。
    distance_decay_m : float
        距离评分衰减常数 (m)，score = exp(-d / decay)。
    velocity_norm_px_s : float
        速度归一化参数 (px/s)。
    target_height_m : float
        假设目标高度 (m), 用于 bbox 测距。
    sector_size_deg : float
        扇区扫清模式的扇区大小 (°)。
    """

    weights: ThreatWeights = ThreatWeights()
    strategy: str = "threat_first"
    class_threat_levels: dict[str, float] = field(
        default_factory=lambda: {
            "person": 0.8,
            "car": 0.6,
            "truck": 0.7,
            "bus": 0.5,
        }
    )
    max_engagement_range_m: float = 500.0
    min_threat_threshold: float = 0.1
    distance_decay_m: float = 50.0
    velocity_norm_px_s: float = 200.0
    target_height_m: float = 1.8
    sector_size_deg: float = 30.0
    # Camera horizontal focal length (px). When > 0, sector_sweep uses the
    # correct atan2 angular formula instead of a linear pixel mapping.
    camera_fx: float = 0.0


# ---------------------------------------------------------------------------
# 威胁评估器
# ---------------------------------------------------------------------------


class ThreatAssessor:
    """多目标威胁评估器。

    对每个跟踪目标计算综合威胁评分, 考虑:
    - 距离 (bbox 估距)
    - 接近速度 (像素速度径向分量)
    - 目标类别 (可配置等级)
    - 运动朝向 (是否朝向画面中心 = 朝向我方)
    - 目标大小 (bbox 面积)
    """

    def __init__(
        self,
        frame_width: int,
        frame_height: int,
        camera_fy: float,
        config: EngagementConfig = EngagementConfig(),
    ) -> None:
        self._fw = frame_width
        self._fh = frame_height
        self._fy = camera_fy
        self._cfg = config

    def assess(
        self,
        tracks: list[Track],
        distance_map: dict[int, float] | None = None,
    ) -> list[ThreatAssessment]:
        """对所有目标执行威胁评估并返回排序后的结果。

        Parameters
        ----------
        tracks : list[Track]
            当前帧所有活跃 Track。
        distance_map : dict[track_id -> distance_m], optional
            来自 DistanceFusion 的已知距离（激光优先）。提供时优先使用，
            缺失条目回退到 bbox 估距。

        Returns
        -------
        list[ThreatAssessment]
            按优先级排序 (priority_rank=1 最高)。
        """
        if not tracks:
            return []

        assessments: list[ThreatAssessment] = []

        for track in tracks:
            dist_m = self._estimate_distance(track, distance_map)

            # 超出最大交战距离则跳过
            if dist_m > self._cfg.max_engagement_range_m:
                continue

            d_score = self._distance_score(dist_m)
            v_score = self._velocity_score(track)
            c_score = self._class_score(track)
            h_score = self._heading_score(track)
            s_score = self._size_score(track)

            w = self._cfg.weights
            threat = (
                w.distance * d_score
                + w.velocity * v_score
                + w.class_threat * c_score
                + w.heading * h_score
                + w.size * s_score
            )
            threat = max(min(threat, 1.0), 0.0)

            if threat < self._cfg.min_threat_threshold:
                continue

            assessments.append(
                ThreatAssessment(
                    track_id=track.track_id,
                    threat_score=threat,
                    distance_score=d_score,
                    velocity_score=v_score,
                    class_score=c_score,
                    heading_score=h_score,
                    priority_rank=0,
                )
            )

        # 排序
        assessments = self._sort_by_strategy(assessments, tracks, distance_map)

        # 赋予排名
        ranked: list[ThreatAssessment] = []
        for i, a in enumerate(assessments):
            ranked.append(
                ThreatAssessment(
                    track_id=a.track_id,
                    threat_score=a.threat_score,
                    distance_score=a.distance_score,
                    velocity_score=a.velocity_score,
                    class_score=a.class_score,
                    heading_score=a.heading_score,
                    priority_rank=i + 1,
                )
            )

        if ranked:
            logger.debug(
                "threat assessment: top=%d score=%.3f, total=%d targets",
                ranked[0].track_id,
                ranked[0].threat_score,
                len(ranked),
            )

        return ranked

    def _estimate_distance(
        self,
        track: Track,
        distance_map: dict[int, float] | None = None,
    ) -> float:
        """返回目标距离 (m)。

        优先使用 distance_map（来自 DistanceFusion 的激光/融合距离）；
        缺失时回退到 bbox 单目估距。
        """
        if distance_map and track.track_id in distance_map:
            return distance_map[track.track_id]
        if track.bbox.h <= 1.0:
            return self._cfg.max_engagement_range_m
        return (self._cfg.target_height_m * self._fy) / track.bbox.h

    def _distance_score(self, distance_m: float) -> float:
        """距离越近得分越高, 指数衰减。"""
        return math.exp(-distance_m / max(self._cfg.distance_decay_m, 1.0))

    def _velocity_score(self, track: Track) -> float:
        """接近速度得分。

        接近速度 = 朝画面中心运动的速度分量（正值 = 靠近我方）。
        """
        vx, vy = track.velocity_px_per_s
        cx, cy = track.bbox.center
        # 从目标到画面中心的方向向量
        dx = self._fw * 0.5 - cx
        dy = self._fh * 0.5 - cy
        dist_to_center = math.sqrt(dx**2 + dy**2)
        if dist_to_center < 1.0:
            return 1.0  # 已在中心

        # 速度在接近方向上的投影
        approach_speed = (vx * dx + vy * dy) / dist_to_center
        # 正值 = 靠近, 归一化到 [0, 1]
        norm = max(self._cfg.velocity_norm_px_s, 1.0)
        return max(min(approach_speed / norm, 1.0), 0.0)

    def _class_score(self, track: Track) -> float:
        """目标类别威胁等级。"""
        return self._cfg.class_threat_levels.get(track.class_id, 0.3)

    def _heading_score(self, track: Track) -> float:
        """目标朝向评分。

        运动方向与画面中心方向的余弦相似度。
        """
        vx, vy = track.velocity_px_per_s
        speed = math.sqrt(vx**2 + vy**2)
        if speed < 1.0:
            return 0.5  # 静止目标中性

        cx, cy = track.bbox.center
        dx = self._fw * 0.5 - cx
        dy = self._fh * 0.5 - cy
        dist = math.sqrt(dx**2 + dy**2)
        if dist < 1.0:
            return 1.0

        cos_sim = (vx * dx + vy * dy) / (speed * dist)
        return max(min((cos_sim + 1.0) * 0.5, 1.0), 0.0)

    def _size_score(self, track: Track) -> float:
        """目标大小评分（归一化）。"""
        max_area = self._fw * self._fh * 0.25  # 最大占比 25%
        return min(track.bbox.area / max(max_area, 1.0), 1.0)

    def _sort_by_strategy(
        self,
        assessments: list[ThreatAssessment],
        tracks: list[Track],
        distance_map: dict[int, float] | None = None,
    ) -> list[ThreatAssessment]:
        """按策略排序。"""
        if self._cfg.strategy == "nearest_first":
            track_map = {t.track_id: t for t in tracks}
            return sorted(
                assessments,
                key=lambda a: (
                    self._estimate_distance(track_map[a.track_id], distance_map)
                    if a.track_id in track_map
                    else float("inf")
                ),
            )

        if self._cfg.strategy == "sector_sweep":
            track_map = {t.track_id: t for t in tracks}
            sector = self._cfg.sector_size_deg
            fx = self._cfg.camera_fx

            def _target_yaw_deg(t: Track) -> float:
                cx, _ = t.bbox.center
                if fx > 0.0:
                    # Correct angular position using camera horizontal FOV
                    return math.degrees(math.atan2(cx - self._fw * 0.5, fx))
                # Fallback: linear pixel mapping (inaccurate for wide-angle lenses)
                return (cx / max(self._fw, 1)) * 360 - 180

            def sector_key(a: ThreatAssessment) -> tuple[int, float]:
                if a.track_id not in track_map:
                    return (999, 0.0)
                angle = _target_yaw_deg(track_map[a.track_id])
                sector_idx = int(angle / sector)
                return (sector_idx, -a.threat_score)

            return sorted(assessments, key=sector_key)

        # 默认: threat_first
        return sorted(assessments, key=lambda a: a.threat_score, reverse=True)


# ---------------------------------------------------------------------------
# 交战队列
# ---------------------------------------------------------------------------


class EngagementQueue:
    """交战队列管理器。

    维护一个按优先级排序的目标队列，跟踪当前交战目标，
    支持:
    - 目标消灭后自动切换下一个
    - 手动跳过
    - 队列实时更新（随 ThreatAssessor 输出更新）
    """

    def __init__(self, config: EngagementConfig = EngagementConfig()) -> None:
        self._cfg = config
        self._queue: list[ThreatAssessment] = []
        self._current_idx: int = 0
        self._engaged_ids: set[int] = set()

    @property
    def queue(self) -> list[ThreatAssessment]:
        """当前交战队列（只读副本）。"""
        return list(self._queue)

    @property
    def current_target_id(self) -> int | None:
        """当前交战目标 ID, None 表示无目标。"""
        if 0 <= self._current_idx < len(self._queue):
            return self._queue[self._current_idx].track_id
        return None

    @property
    def remaining(self) -> int:
        """剩余目标数。"""
        return max(len(self._queue) - self._current_idx, 0)

    def update(self, assessments: list[ThreatAssessment]) -> None:
        """用最新威胁评估更新交战队列。

        保持当前交战目标的连续性：如果当前目标仍在新列表中,
        保留其位置; 否则自动切换到新队列的首位。
        """
        current_id = self.current_target_id
        self._queue = assessments

        if current_id is not None:
            # 尝试找到当前目标在新列表中的位置
            for i, a in enumerate(self._queue):
                if a.track_id == current_id:
                    self._current_idx = i
                    return

        # 当前目标不在新列表中，切换到首位
        self._current_idx = 0

    def advance(self) -> int | None:
        """切换到下一个目标, 返回新目标 ID 或 None。"""
        if self.current_target_id is not None:
            self._engaged_ids.add(self.current_target_id)

        self._current_idx += 1
        target_id = self.current_target_id

        if target_id is not None:
            logger.info(
                "engagement advance: -> target %d (rank %d/%d)",
                target_id,
                self._current_idx + 1,
                len(self._queue),
            )
        else:
            logger.info("engagement advance: queue exhausted")

        return target_id

    def skip(self) -> int | None:
        """跳过当前目标（不标记为已交战）。"""
        self._current_idx += 1
        return self.current_target_id

    def reset(self) -> None:
        """重置交战队列。"""
        self._queue.clear()
        self._current_idx = 0
        self._engaged_ids.clear()
