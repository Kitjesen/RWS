# RWS Tracking — 开发日志与技术备忘

> 本文档记录追踪算法迭代过程中的核心发现、设计决策与 benchmark 数据，  
> 供后续开发作为上下文记忆使用。

---

## 目录

1. [系统架构概览](#1-系统架构概览)
2. [Changelog](#2-changelog)
3. [Benchmark 数据汇总](#3-benchmark-数据汇总)
4. [关键设计决策与背后原因](#4-关键设计决策与背后原因)
5. [已知问题与待解决项](#5-已知问题与待解决项)
6. [参数调优速查表](#6-参数调优速查表)
7. [文件地图](#7-文件地图)

---

## 1. 系统架构概览

```
输入帧
  │
  ▼
FusionSegTracker.detect_and_track(frame, timestamp)
  │
  ├─► YOLO 推理 (yolo11n-seg.pt 或 yolo11n-pose.pt)
  │     └─ bboxes (N,4)  confs (N,)  [keypoints (N,17,3)]
  │
  ├─► OSNet Re-ID 特征提取
  │     └─ features (N, 512)
  │
  └─► FusionMOT.update(bboxes, confs, features, timestamp, keypoints)
        │
        ├─ Kalman CA predict (全轨迹抛物线外推)
        │
        ├─ Stage 1: 高置信检测 × 全部轨迹
        │   cost = w_iou·(1-IoU) + w_app·(1-cosine)/2
        │         + w_motion·mahal_norm + w_height·h_diff
        │         + w_skeleton·skel_dist   ← 骨骼线索（可选）
        │   门控: Mahalanobis(σ=6) + 最小像素兜底(80px)
        │
        ├─ Stage 2: 低置信检测 × 未匹配轨迹 (IoU-only, ByteTrack)
        │
        ├─ Stage 3: 未匹配高置信检测 × 丢失轨迹 (Re-ID 恢复)
        │
        └─ 输出: List[(track_id, bbox_xywh, confidence)]
```

**每条 `_Tracklet` 内嵌状态：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `kf` | `CentroidKalmanCA` | 6-state CA Kalman [cx,cy,vx,vy,ax,ay] |
| `feature_ema` | `(512,)` | OSNet 特征指数平滑 |
| `feature_bank` | `list[(feat, conf, ts)]` | 最近 15 帧特征库 |
| `keypoints_ema` | `(17,2)` or None | COCO-17 关键点 EMA (α=0.7) |
| `height_ema` | float | 目标高度平滑 (Hybrid-SORT) |
| `state` | str | tentative / confirmed / lost |

---

## 2. Changelog

### v3 — Pose-Guided Tracking（2026-02-22）`commit f15daaa → c8ee45f`

**动机：** FusionMOT 在人群场景中 bbox 质心受手臂摆动影响大；地铁竖屏中轨迹碎片多。

**核心变更：**

**`src/rws_tracking/perception/fusion_mot.py`**

- 新增 COCO-17 骨骼常量 `_KP_HIP_L/R`, `_KP_SHOULDER_L/R` 等
- `FusionMOTConfig` 新增字段：
  - `w_skeleton: float = 0.0` — 骨骼线索权重（0 = 关闭，推荐 0.06）
  - `use_hip_center: bool = True` — 用 hip 中点替代 bbox 质心作 Kalman 锚点
  - `skeleton_gate: float = 0.8` — 骨骼描述子最大匹配距离（推荐 1.2）
  - `kp_visibility_thresh: float = 0.2` — YOLO 关键点可见度阈值
- `_Tracklet.__slots__` 新增 `keypoints_ema`
- `FusionMOT.update()` 新增 `keypoints: ndarray | None = None` 参数
- `_build_cost_matrix()` 新增第 5 路线索：骨骼比例描述子
- `_build_recovery_cost()` Stage 3 骨骼权重 ×1.5（体型稳定性在恢复阶段更关键）
- `_init_tracklet()` / `_update_tracklet()` 支持 hip center + keypoints EMA 更新
- 新增静态方法 `_hip_center(kpts, vis, thresh)` — 提取髋部中点，含零坐标防护
- 新增静态方法 `_skeleton_descriptor(kpts, vis, thresh)` — 8-D 骨骼比例描述子，
  以躯干对角线归一化，不可见骨骼编码为 0（中性，不惩罚）

**`src/rws_tracking/perception/fusion_seg_tracker.py`**

- `detect_and_track()` 自动从 `result.keypoints.data` 提取 `(N,17,3)` 关键点
- 仅当所有检测均有 pose 数据时才组装 `keypoints_arr`（避免对齐错误）
- 关键点传给 `FusionMOT.update(keypoints=keypoints_arr)`

**使用方式：**
```python
tracker = FusionSegTracker(
    model_path="yolo11n-pose.pt",   # pose 模型替换 seg
    mot_config=FusionMOTConfig(
        w_skeleton=0.06,
        use_hip_center=True,
        skeleton_gate=1.2,
        kp_visibility_thresh=0.2,
    ),
)
```

**向后兼容：** `keypoints=None` 或 `w_skeleton=0.0` 时行为与 v2 完全一致。

---

### v2 — Kalman CA 整合（2026-02-21）`commit dd29091`

**动机：** BoT-SORT 内置 Kalman 与外部手动 EMA 速度存在双层滤波；遮挡期线性外推误差大。

**核心变更：**

**`src/rws_tracking/perception/fusion_mot.py`**

- 每条 `_Tracklet` 内嵌 `CentroidKalmanCA`（6-state，取代手动 `position += velocity * dt`）
- `predict(dt)` — 抛物线外推（替代直线）
- `update(cx, cy)` — 最优卡尔曼增益（替代手动 `velocity = 0.7*old + 0.3*new`）
- **Mahalanobis 距离门控**：匹配半径根据协方差自适应
- **最小像素兜底**（80px）：防止高分辨率视频中门控过紧
- `FusionMOTConfig.mahalanobis_sigma = 6.0`，`min_motion_gate_px = 80.0`

**`src/rws_tracking/perception/fusion_seg_tracker.py`**

- 移除冗余的外部 Kalman 层（265 行 → 180 行）
- `detect_and_track()` 直接读取 `tracklet.kf.velocity` / `.acceleration`
- `run_camera_demo.py` 轨迹预测改为读取内置 Kalman 状态

---

### v1 — FusionMOT 基础（2026-02-20）`初始提交`

**替换 BoT-SORT，自研多线索融合追踪器：**

- 统一 cost matrix：IoU + 外观 + 运动 + 高度（Deep OC-SORT Eq.6 风格）
- 三段式匹配：高置信 → 低置信（ByteTrack）→ 丢失轨迹 Re-ID 恢复
- OSNet x1.0 外观特征 + 动态 EMA 更新 + 特征库（最近 15 帧）
- 摄像机运动补偿（CMC）可选开关

---

## 3. Benchmark 数据汇总

测试环境：CPU-only，300 帧/视频，YOLO Nano 系列模型。  
基准：A = YOLO-seg + BoT-SORT（无 Re-ID）。  
差值百分比均相对 Baseline（A）计算，`↓` 越小越好，`↑` 越大越好。

### 街道场景（test_people.mp4，1920×1080，室外稀疏人群）

| 指标 | A Baseline | B BoT+OSNet | C FusionMOT | D Pose+Skel |
|------|:----------:|:-----------:|:-----------:|:-----------:|
| Unique IDs ↓ | 69 | 28 (-59%) | 34 (-51%) | **6 (-91%)** |
| Avg 轨迹长度 ↑ | 87.6 | 215.9 (+146%) | **260.2 (+197%)** | 138.2 (+58%) |
| 碎片断裂次数 ↓ | 213 | 117 (-45%) | 241 (+13%) | **35 (-84%)** |
| Avg 断裂间隔 ↓ | 5.4 | 8.7 (+62%) | **2.6 (-52%)** | 11.1 (+106%) |
| Avg 延迟 ↓ | 172ms | 250ms (+45%) | 183ms (+6%) | **142ms (-17%)** |
| P95 延迟 ↓ | 216ms | 401ms (+86%) | 286ms (+32%) | 302ms (+40%) |

### 地铁场景（test_subway.mp4，2160×3840，室内密集人群）

| 指标 | A Baseline | B BoT+OSNet | C FusionMOT | D Pose+Skel |
|------|:----------:|:-----------:|:-----------:|:-----------:|
| Unique IDs ↓ | 18 | **9 (-50%)** | 15 (-17%) | **9 (-50%)** |
| Avg 轨迹长度 ↑ | 124.7 | **249.4 (+100%)** | 209.5 (+68%) | 206.8 (+66%) |
| 碎片断裂次数 ↓ | 39 | 31 (-21%) | 36 (-8%) | **32 (-18%)** |
| Avg 断裂间隔 ↓ | 7.0 | 10.1 (+44%) | 12.9 (+84%) | **2.0 (-71%)** |
| Avg 延迟 ↓ | 186ms | 189ms (+2%) | 141ms (-24%) | **140ms (-24%)** |
| P95 延迟 ↓ | 215ms | 243ms (+13%) | **195ms (-9%)** | 342ms (+59%) |

### 结论摘要

| 方案 | 最优场景 | 短板 |
|------|----------|------|
| **B BoT+OSNet** | 地铁 ID 稳定（-50%） | 延迟最高（+45%），需 Re-ID 算力 |
| **C FusionMOT** | 街道轨迹最长（+197%），断裂间隔最小 | 地铁 ID 仍偏多 |
| **D Pose+Skel** | 街道 ID -91%，碎片 -84%，速度最快 | 地铁 P95 延迟偏高；轨迹长度略低于 C |

**推荐部署策略：**
- 室外稀疏人群 → **D（Pose+Skel）**：ID 最少，速度最快
- 室内密集人群 → **B 或 D**：地铁场景 B 与 D 并列最优，但 D 更快

---

## 4. 关键设计决策与背后原因

### 4.1 为什么用 Hip Center 而非 Bbox 质心？

人体 bbox 质心会随手臂摆动上下移动（手臂占 bbox 高度约 30-40%）。  
髋部中点（COCO kp 11+12 均值）是人体重心的稳定代理，遮挡时抖动更小。

**实测结果：** 街道场景碎片断裂从 241 降到 35（-84%）。

### 4.2 骨骼描述子为什么用比例而非绝对位置？

绝对关键点坐标随距离、视角变化剧烈，无法跨帧稳定比较。  
归一化骨骼长度（以躯干对角线为分母）是尺度无关、视角鲁棒的体型特征，  
适合区分不同体型的人（胖/瘦，高/矮），不适合区分同一人的不同姿态。

**因此骨骼线索的作用是：** 拒绝体型差异大的错误匹配，而非精确定位。

### 4.3 为什么 `skeleton_gate` 从 0.8 调到 1.2？

0.8 过严：同一人从正面走到侧面，肩宽骨骼投影变小，描述子 L2 距离可达 0.9-1.0，  
导致被误判为体型不同的人，引发断裂。1.2 允许视角变化的容差。

### 4.4 为什么 `kp_visibility_thresh` 用 0.2 而非 0.3？

地铁场景竖屏（2160×3840），人物在画面中相对较小，YOLO-pose 的关键点  
置信度普遍偏低（0.2-0.4 区间多）。阈值 0.3 会过滤掉大量有效关键点，  
导致 hip center 频繁退化为 (0,0) 坐标（YOLO 不可见关键点的默认输出），  
污染 Kalman 状态。降到 0.2 后恢复正常。

**补充防护：** `_hip_center()` 和 `_skeleton_descriptor()` 中都加入了  
`px > 1.0 and py > 1.0` 的零坐标检查，双重保障。

### 4.5 Mahalanobis 门控的最小像素兜底（80px）是什么？

高分辨率视频（4K）中，刚初始化的轨迹协方差很小，Mahalanobis 门控半径  
可能只有 10-20px，导致相邻帧的正确匹配被拒绝。80px 兜底确保在协方差  
收紧之前，真正靠近的检测依然能匹配上。

### 4.6 Stage 3 骨骼权重为什么 ×1.5？

遮挡恢复时，运动预测（Kalman CA）已经积累了协方差，位置不确定。  
外观特征（OSNet）也可能因时间间隔而 EMA 衰减。  
骨骼比例是人体固有特征，不随时间改变，在这个阶段相对更可信。

---

## 5. 已知问题与待解决项

### 高优先级

| 问题 | 场景 | 现象 | 排查方向 |
|------|------|------|----------|
| 地铁 P95 延迟偏高 | test_subway.mp4 | Pose+Skel P95=342ms（+59% vs baseline） | 4K 视频 YOLO 推理本身耗时，需分析 profiling；考虑降采样输入 |
| 街道 Avg 轨迹长度 D < C | test_people.mp4 | 138 vs 260（D 比 C 短 47%） | hip center 偏移导致同一人轨迹被拆分为多段；需可视化验证 |

### 中优先级

| 问题 | 说明 |
|------|------|
| 自适应 Process Noise | 高速目标与慢速目标混合时，固定 `process_noise_acc=30` 不理想。方向：`q_acc = α·‖v‖ + q₀` |
| Bbox w/h Kalman | 目前只跟踪质心，`predicted_bbox()` 的 w/h 来自上一帧测量值。快速靠近/远离时 IoU 预测偏差增大 |
| `yolo11s-pose.pt` 评估 | Nano 模型漏检是 ID 切换的根本原因之一；Small 模型（参数 ×4）是否能换取更低漏检率有待测试 |

### 低优先级

| 问题 | 说明 |
|------|------|
| 骨骼跨视角鲁棒性 | 当前 8-D 描述子在正/侧/背面切换时仍有跳变，可考虑引入视角估计权重 |
| 特征库衰减策略 | 长时间遮挡后特征库中的样本质量下降，当前无 confidence-weighted 清理 |

---

## 6. 参数调优速查表

### `FusionMOTConfig` 关键参数

| 参数 | 默认值 | 含义 | 调大影响 | 调小影响 |
|------|--------|------|----------|----------|
| `high_conf` | 0.35 | Stage 1 检测置信度门槛 | 更少检测参与匹配 | 更多噪声检测 |
| `mahalanobis_sigma` | 6.0 | Mahalanobis 门控半径（σ倍数） | 更宽匹配 | 更严格，漏匹配 ↑ |
| `min_motion_gate_px` | 80.0 | 最小像素门控兜底 | 高分辨率下更宽松 | 低分辨率下更精准 |
| `lost_patience` | 3 | 轨迹转为 lost 前的容忍帧数 | 短暂遮挡容忍度 ↑ | 响应速度 ↑ |
| `max_lost_seconds` | 8.0 | 丢失轨迹最长保留时间 | 长遮挡恢复能力 ↑ | 内存占用 ↓ |
| `w_skeleton` | 0.0 | 骨骼线索权重（0=关闭） | 骨骼约束更强 | 骨骼只作参考 |
| `skeleton_gate` | 0.8 | 骨骼描述子硬门控距离 | 视角容忍度 ↑ | 体型辨别力 ↑ |
| `kp_visibility_thresh` | 0.2 | 关键点可见度门槛 | 更少关键点被采用 | 更多但噪声更大 |

### 场景推荐配置

```python
# 室外稀疏人群（人物较大，骨骼可见度高）
FusionMOTConfig(
    w_skeleton=0.06,
    skeleton_gate=1.2,
    kp_visibility_thresh=0.2,
    use_hip_center=True,
)

# 室内密集人群 / 高分辨率竖屏（小目标，关键点质量偏低）
FusionMOTConfig(
    w_skeleton=0.04,        # 适当降低骨骼权重
    skeleton_gate=1.4,      # 更宽容的门控
    kp_visibility_thresh=0.15,  # 接受低置信关键点
    use_hip_center=True,
    min_motion_gate_px=120.0,   # 4K 视频中的像素兜底值更大
)
```

---

## 7. 文件地图

```
src/rws_tracking/
├── perception/
│   ├── fusion_mot.py          ← 核心追踪器（v1-v3 主战场）
│   ├── fusion_seg_tracker.py  ← YOLO + FusionMOT 组合入口
│   ├── yolo_seg_tracker.py    ← 旧版 BoT-SORT 路线（保留对比用）
│   ├── reid_extractor.py      ← OSNet 特征提取
│   ├── appearance_gallery.py  ← Re-ID 特征库（Stage 3 用）
│   └── cmc.py                 ← 相机运动补偿
├── algebra/
│   └── kalman2d.py            ← CentroidKalman2D (CV) + CentroidKalmanCA (CA)
└── types/
    └── perception.py          ← Track, BoundingBox 数据类型

tests/tracking_benchmark/
├── benchmark_fusion.py        ← 四路对比 benchmark（A/B/C/D）
├── test_people.mp4            ← 街道场景测试视频
└── test_subway.mp4            ← 地铁场景测试视频
```

---

*最后更新：2026-02-22*  
*对应 commits：`dd29091`（v2 Kalman CA）→ `f15daaa`（v3 Pose）→ `c8ee45f`（benchmark）*
