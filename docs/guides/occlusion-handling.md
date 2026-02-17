# 遮挡处理和目标位姿估计技术报告

## 1. 遮挡问题概述

遮挡（Occlusion）是视觉跟踪中的核心挑战之一，分为：
- **部分遮挡**：目标被部分遮挡，仍有部分可见
- **完全遮挡**：目标完全被遮挡，暂时消失
- **自遮挡**：目标自身姿态变化导致的遮挡

---

## 2. 当前项目的遮挡处理方案

### 2.1 多层次遮挡处理架构

```
检测层 → 跟踪层 → 决策层 → 控制层
  ↓        ↓        ↓        ↓
YOLO    IoU跟踪   状态机   预测补偿
```

### 2.2 跟踪层：容忍短期遮挡

**实现位置**：`src/rws_tracking/perception/tracker.py`

```python
class SimpleIoUTracker:
    def __init__(self, iou_threshold: float = 0.2, max_misses: int = 8):
        self._max_misses = max_misses  # 允许连续丢失 8 帧
```

**机制**：
- 当目标未被检测到时，`misses` 计数器 +1
- 只要 `misses ≤ max_misses`，轨迹保持活跃
- 超过阈值后才删除轨迹

**优点**：
- 容忍短期遮挡（~0.27秒 @ 30fps）
- 避免 ID 切换抖动

### 2.3 决策层：LOST 状态

**实现位置**：`src/rws_tracking/decision/state_machine.py`

```python
class TrackState(Enum):
    SEARCH = "search"
    TRACK = "track"
    LOCK = "lock"
    LOST = "lost"  # 目标丢失但仍在预测范围内
```

**状态转换**：
```
TRACK/LOCK → (目标消失) → LOST → (超时) → SEARCH
```

**配置参数**：
- `lost_timeout_s = 1.5s`：LOST 状态最大持续时间

### 2.4 控制层：运动预测补偿

**实现位置**：`src/rws_tracking/control/controller.py:348`

```python
def _predict_lost_error(self, timestamp: float) -> TargetError | None:
    """使用恒速模型预测目标位置"""
    dt_lost = timestamp - self._last_error.timestamp
    if dt_lost > self._cfg.predict_timeout_s:
        return None  # 预测时间过长，放弃

    # 恒速模型外推
    vx, vy = self._last_target.velocity_px_per_s
    pred_cx = cx + vx * dt_lost
    pred_cy = cy + vy * dt_lost

    return TargetError(...)
```

**机制**：
- 使用最后已知的速度进行线性外推
- 在 LOST 状态下继续 PID 控制
- 超过 `predict_timeout_s` 后停止预测

---

## 3. 相关论文和先进方法

### 3.1 经典方法

#### **SORT (Simple Online and Realtime Tracking, 2016)**
- 使用卡尔曼滤波器预测目标位置
- 匈牙利算法进行数据关联
- **遮挡处理**：允许轨迹在 `max_age` 帧内无匹配

#### **DeepSORT (2017)**
- SORT + 外观特征（ReID）
- **遮挡处理**：结合运动预测和外观相似度
- 更鲁棒的长期遮挡处理

#### **ByteTrack (ECCV 2022)**
- 两阶段关联：高分检测 + 低分检测
- **遮挡处理**：利用低置信度检测恢复被遮挡目标
- 论文：https://arxiv.org/abs/2110.06864

#### **BoT-SORT (2022)**
- ByteTrack + 相机运动补偿 + ReID
- **遮挡处理**：多模态融合（运动 + 外观 + 相机运动）
- 当前项目使用的 YOLO-Seg 集成了 BoT-SORT

### 3.2 深度学习方法

#### **TransTrack (ECCV 2020)**
- Transformer 端到端跟踪
- **遮挡处理**：注意力机制自动学习遮挡模式

#### **MOTR (ICCV 2021)**
- Multi-Object Tracking with Transformers
- **遮挡处理**：Track Query 机制保持长期记忆

#### **OC-SORT (2023)**
- Observation-Centric SORT
- **遮挡处理**：观测中心的虚拟轨迹
- 论文：https://arxiv.org/abs/2203.14360

---

## 4. 改进建议

### 4.1 短期改进（易实现）

#### **方案 1：卡尔曼滤波器替代恒速模型**

**当前**：
```python
# 简单线性外推
pred_cx = cx + vx * dt_lost
pred_cy = cy + vy * dt_lost
```

**改进**：
```python
# 使用卡尔曼滤波器（已有实现）
from ..algebra.kalman2d import ConstantVelocityKalman2D

class TwoAxisGimbalController:
    def __init__(self, ...):
        self._kalman = ConstantVelocityKalman2D(
            process_noise_std=5.0,
            measurement_noise_std=2.0
        )

    def _predict_lost_error(self, timestamp):
        # 使用卡尔曼预测
        predicted_pos = self._kalman.predict(dt_lost)
        return predicted_pos
```

**优点**：
- 更准确的运动预测
- 考虑测量噪声和过程噪声
- 已有实现：`src/rws_tracking/algebra/kalman2d.py`

#### **方案 2：增加 max_misses 参数**

```yaml
# config.yaml
tracker:
  iou_threshold: 0.18
  max_misses: 15  # 从 8 增加到 15（~0.5秒 @ 30fps）
```

**优点**：
- 零代码修改
- 立即提升遮挡容忍度

#### **方案 3：自适应 max_misses**

```python
class AdaptiveIoUTracker:
    def update(self, detections, timestamp):
        for tid, track in self._tracks.items():
            # 根据目标速度自适应调整
            speed = np.linalg.norm(track.velocity_px_per_s)
            adaptive_max_misses = int(8 + speed / 10)  # 快速目标容忍更多丢失
```

### 4.2 中期改进（需要集成）

#### **方案 4：集成 ByteTrack 低分检测恢复**

```python
class ByteTrackIoUTracker:
    def update(self, detections, timestamp):
        # 第一阶段：高置信度检测（conf > 0.5）
        high_conf_dets = [d for d in detections if d.confidence > 0.5]
        matches_high = self._associate(high_conf_dets)

        # 第二阶段：低置信度检测恢复未匹配轨迹（0.1 < conf < 0.5）
        low_conf_dets = [d for d in detections if 0.1 < d.confidence < 0.5]
        unmatched_tracks = [t for t in self._tracks if t not in matches_high]
        matches_low = self._associate(unmatched_tracks, low_conf_dets)
```

**优点**：
- 利用部分遮挡时的低置信度检测
- 显著提升遮挡恢复能力

#### **方案 5：添加 ReID 外观特征**

```python
class DeepSORTTracker:
    def __init__(self, reid_model):
        self._reid_model = reid_model  # 如 OSNet, FastReID
        self._feature_bank = {}  # 存储每个轨迹的外观特征

    def update(self, detections, timestamp):
        # 提取外观特征
        features = self._reid_model.extract(detections)

        # 融合 IoU 和外观相似度
        cost_matrix = 0.7 * iou_cost + 0.3 * cosine_distance(features)
```

**优点**：
- 长期遮挡后仍能重识别
- 处理 ID 切换问题

### 4.3 长期改进（研究级）

#### **方案 6：Transformer 端到端跟踪**

集成 MOTR 或 TrackFormer：
- 端到端学习遮挡模式
- 无需手工设计关联规则

#### **方案 7：3D 跟踪 + 深度估计**

```python
# 使用深度估计预测遮挡
depth_map = depth_estimator(frame)
if depth_map[target_bbox] > depth_map[occluder_bbox]:
    # 目标在遮挡物后面，预测遮挡持续时间
    occlusion_duration = estimate_occlusion_time(...)
```

---

## 5. 目标位姿估计

### 5.1 当前实现

**位置估计**：
- 2D 像素坐标：`bbox.center` 或 `mask_center`
- 速度估计：有限差分 `(new_pos - old_pos) / dt`
- 加速度：二阶差分（在 Track 中有 `acceleration_px_per_s2` 字段）

**角度估计**：
```python
# src/rws_tracking/algebra/coordinate_transform.py
def pixel_to_angle_error(self, u: float, v: float) -> tuple[float, float]:
    """像素 → 云台角度误差"""
    xn, yn = self._undistort_and_normalize(u, v)
    cam_dir = np.array([xn, yn, 1.0])
    gimbal_dir = self._R_cam2gimbal @ cam_dir
    yaw_rad = math.atan2(gimbal_dir[0], gimbal_dir[2])
    pitch_rad = -math.atan2(gimbal_dir[1], gimbal_dir[2])
    return math.degrees(yaw_rad), math.degrees(pitch_rad)
```

### 5.2 缺失的位姿信息

当前**没有**估计：
- ❌ 目标 3D 位置（距离）
- ❌ 目标 3D 姿态（roll, pitch, yaw）
- ❌ 目标尺寸（真实物理尺寸）

### 5.3 位姿估计方法

#### **方法 1：单目深度估计**

```python
# 使用 bbox 大小估计距离（需要已知目标真实尺寸）
def estimate_distance(bbox_height_px, real_height_m, focal_length_px):
    """
    距离 = (真实高度 × 焦距) / 像素高度
    """
    distance_m = (real_height_m * focal_length_px) / bbox_height_px
    return distance_m

# 示例：人体目标（假设身高 1.7m）
distance = estimate_distance(
    bbox_height_px=200,
    real_height_m=1.7,
    focal_length_px=1000
)  # ≈ 8.5 米
```

**优点**：
- 简单，无需额外硬件
- 适用于已知尺寸的目标（人、车辆）

**缺点**：
- 需要先验知识（目标尺寸）
- 精度有限

#### **方法 2：深度学习单目深度估计**

```python
# 使用 MiDaS, DPT, Depth-Anything 等模型
import torch
from transformers import DPTForDepthEstimation

depth_model = DPTForDepthEstimation.from_pretrained("Intel/dpt-large")
depth_map = depth_model(frame)
target_depth = depth_map[bbox.y:bbox.y+bbox.h, bbox.x:bbox.x+bbox.w].mean()
```

**优点**：
- 无需先验知识
- 可以估计任意目标的相对深度

**缺点**：
- 计算开销大
- 绝对尺度不准确（需要尺度恢复）

#### **方法 3：6D 位姿估计（PnP）**

```python
# 使用 YOLO-Pose 或 6D-Pose 网络
# 检测关键点 → PnP 求解 → 得到 6D 位姿

import cv2

# 3D 模型关键点（已知）
object_points_3d = np.array([...])  # 目标的 3D 关键点

# 2D 检测关键点
image_points_2d = keypoint_detector(frame, bbox)

# PnP 求解
success, rvec, tvec = cv2.solvePnP(
    object_points_3d,
    image_points_2d,
    camera_matrix,
    dist_coeffs
)

# 得到 6D 位姿
rotation_matrix, _ = cv2.Rodrigues(rvec)
position_3d = tvec  # 相机坐标系下的 3D 位置
```

**优点**：
- 精确的 6D 位姿（位置 + 姿态）
- 适用于刚体目标

**缺点**：
- 需要目标 3D 模型
- 需要关键点检测

#### **方法 4：立体视觉/深度相机**

```python
# 使用双目相机或 RGB-D 相机
import pyrealsense2 as rs

# RealSense D435 深度相机
pipeline = rs.pipeline()
config = rs.config()
config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 30)
config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 30)

frames = pipeline.wait_for_frames()
depth_frame = frames.get_depth_frame()
color_frame = frames.get_color_frame()

# 直接获取目标深度
target_depth_m = depth_frame.get_distance(bbox.center_x, bbox.center_y)
```

**优点**：
- 直接测量，精度高
- 实时性好

**缺点**：
- 需要额外硬件
- 室外阳光下深度相机性能下降

---

## 6. 推荐实施方案

### 阶段 1：立即实施（1-2 天）
1. ✅ 增加 `max_misses` 到 15
2. ✅ 集成卡尔曼滤波器到控制器预测

### 阶段 2：短期优化（1 周）
3. 🔧 实现 ByteTrack 低分检测恢复
4. 🔧 添加基于 bbox 的距离估计

### 阶段 3：中期增强（2-4 周）
5. 🚀 集成 ReID 外观特征（FastReID）
6. 🚀 集成深度估计模型（Depth-Anything v2）

### 阶段 4：长期研究（1-3 月）
7. 🔬 评估 Transformer 跟踪器（MOTR）
8. 🔬 硬件升级：考虑深度相机

---

## 7. 参考文献

1. **SORT**: Bewley et al., "Simple Online and Realtime Tracking", ICIP 2016
2. **DeepSORT**: Wojke et al., "Simple Online and Realtime Tracking with a Deep Association Metric", ICIP 2017
3. **ByteTrack**: Zhang et al., "ByteTrack: Multi-Object Tracking by Associating Every Detection Box", ECCV 2022
4. **BoT-SORT**: Aharon et al., "BoT-SORT: Robust Associations Multi-Pedestrian Tracking", arXiv 2022
5. **OC-SORT**: Cao et al., "Observation-Centric SORT: Rethinking SORT for Robust Multi-Object Tracking", CVPR 2023
6. **MOTR**: Zeng et al., "MOTR: End-to-End Multiple-Object Tracking with Transformer", ICCV 2021

---

**文档版本**: v1.0
**更新时间**: 2026-02-16
**作者**: Claude Opus 4.6
