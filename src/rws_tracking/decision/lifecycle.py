"""
TargetLifecycleManager — 目标全生命周期管理 (Task E)
=====================================================

职责（单一）:
    跨帧追踪每个目标从出现到归档的完整状态，
    防止对同一目标重复交战，支持 EngagementQueue 的"已处置"过滤。

生命周期状态:
    DETECTED      初次出现（tentative track）
    TRACKED       稳定跟踪（confirmed track，age ≥ confirm_frames）
    ASSESSED      已完成威胁评估
    DESIGNATED    操作员或自动逻辑指定为交战目标
    ENGAGED       正在交战（已进入 EngagementQueue 当前位置）
    NEUTRALIZED   交战完成（advance() 被调用后标记）
    ARCHIVED      N 秒后不再重现，归档冷冻（不再参与评估）

核心保证:
    一旦目标进入 NEUTRALIZED 或 ARCHIVED，不会再出现在
    ThreatAssessor 或 EngagementQueue 的活跃列表中。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class TargetState(str, Enum):
    DETECTED = "detected"
    TRACKED = "tracked"
    ASSESSED = "assessed"
    DESIGNATED = "designated"
    ENGAGED = "engaged"
    NEUTRALIZED = "neutralized"
    ARCHIVED = "archived"


@dataclass
class TargetRecord:
    """单目标的生命周期记录。"""

    track_id: int
    state: TargetState = TargetState.DETECTED
    first_seen_ts: float = 0.0
    last_seen_ts: float = 0.0
    engaged_at_ts: float | None = None
    neutralized_at_ts: float | None = None
    threat_score: float = 0.0
    class_id: str = "unknown"


class TargetLifecycleManager:
    """跨帧目标生命周期管理器。

    Usage::

        mgr = TargetLifecycleManager(archive_after_s=10.0)

        # 每帧调用，传入当前 tracks 和 threat assessments
        mgr.update(tracks, threat_assessments, timestamp)

        # 过滤掉已处置目标（传给 ThreatAssessor 前调用）
        active_tracks = mgr.filter_active(tracks)

        # 标记目标为已交战（EngagementQueue.advance() 后调用）
        mgr.mark_neutralized(track_id, timestamp)

        # 获取统计信息
        summary = mgr.summary()
    """

    def __init__(
        self,
        confirm_age_frames: int = 3,
        archive_after_s: float = 10.0,
    ) -> None:
        """
        Parameters
        ----------
        confirm_age_frames : int
            Track 需要存在多少帧才从 DETECTED 升为 TRACKED。
        archive_after_s : float
            目标消失后多少秒归档（不再参与评估）。
        """
        self._confirm_age = confirm_age_frames
        self._archive_after = archive_after_s
        self._records: dict[int, TargetRecord] = {}

    # ------------------------------------------------------------------
    # 主更新接口
    # ------------------------------------------------------------------

    def update(
        self,
        tracks: list,
        threat_assessments: list,
        timestamp: float,
    ) -> None:
        """每帧调用，更新所有目标状态。

        Parameters
        ----------
        tracks : list[Track]
            当前帧活跃 tracks。
        threat_assessments : list[ThreatAssessment]
            当前帧威胁评估结果（可为空）。
        timestamp : float
        """
        live_ids = {t.track_id for t in tracks}
        threat_map = {ta.track_id: ta for ta in threat_assessments}

        # 更新或创建记录
        for track in tracks:
            tid = track.track_id
            if tid not in self._records:
                self._records[tid] = TargetRecord(
                    track_id=tid,
                    first_seen_ts=timestamp,
                    class_id=getattr(track, "class_id", "unknown"),
                )
                logger.debug("lifecycle: new target %d", tid)

            rec = self._records[tid]
            rec.last_seen_ts = timestamp
            rec.class_id = getattr(track, "class_id", rec.class_id)

            # 状态升级
            age = getattr(track, "age_frames", 1)
            if rec.state == TargetState.DETECTED and age >= self._confirm_age:
                rec.state = TargetState.TRACKED
                logger.debug("lifecycle: %d DETECTED→TRACKED", tid)

            if rec.state == TargetState.TRACKED and tid in threat_map:
                rec.threat_score = threat_map[tid].threat_score
                rec.state = TargetState.ASSESSED

        # 归档失踪目标（NEUTRALIZED/ARCHIVED 不受此影响）
        for tid, rec in self._records.items():
            if tid not in live_ids:
                if rec.state not in (TargetState.NEUTRALIZED, TargetState.ARCHIVED):
                    gone_for = timestamp - rec.last_seen_ts
                    if gone_for >= self._archive_after:
                        rec.state = TargetState.ARCHIVED
                        logger.info("lifecycle: %d ARCHIVED (gone %.1fs)", tid, gone_for)

    # ------------------------------------------------------------------
    # 状态转换接口
    # ------------------------------------------------------------------

    def mark_designated(self, track_id: int, timestamp: float) -> None:
        """标记目标为 DESIGNATED（操作员或系统指定）。"""
        rec = self._records.get(track_id)
        if rec and rec.state in (TargetState.TRACKED, TargetState.ASSESSED):
            rec.state = TargetState.DESIGNATED
            logger.info("lifecycle: %d → DESIGNATED", track_id)

    def mark_engaged(self, track_id: int, timestamp: float) -> None:
        """标记目标为 ENGAGED（已进入交战）。"""
        rec = self._records.get(track_id)
        if rec and rec.state not in (TargetState.NEUTRALIZED, TargetState.ARCHIVED):
            rec.state = TargetState.ENGAGED
            rec.engaged_at_ts = timestamp
            logger.info("lifecycle: %d → ENGAGED", track_id)

    def mark_neutralized(self, track_id: int, timestamp: float) -> None:
        """标记目标为 NEUTRALIZED（交战完成，不再重复交战）。"""
        rec = self._records.get(track_id)
        if rec is not None:
            rec.state = TargetState.NEUTRALIZED
            rec.neutralized_at_ts = timestamp
            logger.info("lifecycle: %d → NEUTRALIZED (dwell %.1fs)",
                        track_id,
                        (timestamp - rec.engaged_at_ts) if rec.engaged_at_ts else 0.0)

    # ------------------------------------------------------------------
    # 过滤接口
    # ------------------------------------------------------------------

    def filter_active(self, tracks: list) -> list:
        """过滤掉已 NEUTRALIZED / ARCHIVED 的目标，返回活跃目标列表。

        在传给 ThreatAssessor.assess() 之前调用：
            active = mgr.filter_active(tracks)
            assessments = assessor.assess(active, distance_map)
        """
        excluded = {TargetState.NEUTRALIZED, TargetState.ARCHIVED}
        filtered = [
            t for t in tracks
            if self._records.get(t.track_id, TargetRecord(t.track_id)).state not in excluded
        ]
        dropped = len(tracks) - len(filtered)
        if dropped > 0:
            logger.debug("lifecycle: filtered %d neutralized/archived targets", dropped)
        return filtered

    def is_active(self, track_id: int) -> bool:
        """目标是否处于活跃（非 NEUTRALIZED/ARCHIVED）状态。"""
        rec = self._records.get(track_id)
        if rec is None:
            return True  # 未见过的目标视为活跃
        return rec.state not in (TargetState.NEUTRALIZED, TargetState.ARCHIVED)

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    def get_record(self, track_id: int) -> TargetRecord | None:
        return self._records.get(track_id)

    def summary(self) -> dict:
        """返回生命周期统计快照。"""
        counts: dict[str, int] = {}
        for rec in self._records.values():
            counts[rec.state.value] = counts.get(rec.state.value, 0) + 1
        return {
            "total_seen": len(self._records),
            "by_state": counts,
            "neutralized_ids": [
                tid for tid, r in self._records.items()
                if r.state == TargetState.NEUTRALIZED
            ],
        }

    def reset(self) -> None:
        """清空所有记录（任务重置时调用）。"""
        self._records.clear()
        logger.info("lifecycle: reset")
