# RWS 坐标变换数学推导

本文档详细推导 RWS 系统中的坐标变换链，包括坐标系定义、旋转矩阵约定和变换公式。

## 坐标系定义

### 1. 像素坐标系 (Pixel Frame)

```
Origin: 图像左上角
u-axis: 向右 (水平)
v-axis: 向下 (垂直)
单位: 像素 (px)

    u →
  v ┌─────────────┐
  ↓ │             │
    │      •      │  (cx, cy) = 主点
    │             │
    └─────────────┘
```

### 2. 相机坐标系 (Camera Frame)

```
Origin: 相机光心
X-axis: 向右
Y-axis: 向下
Z-axis: 向前 (光轴方向)
单位: 米 (m)

遵循 OpenCV 右手坐标系约定
```

```
        Z (forward)
       ↗
      /
     /
    •────→ X (right)
    │
    │
    ↓
    Y (down)
```

### 3. 云台坐标系 (Gimbal Frame)

```
Origin: 云台旋转中心
X-axis: 向右
Y-axis: 向下
Z-axis: 向前 (云台指向)
单位: 米 (m)

与相机坐标系通过安装旋转矩阵 R_cam2gimbal 关联
```

### 4. 机器人本体坐标系 (Body Frame)

```
Origin: 机器人质心
X-axis: 向前
Y-axis: 向左
Z-axis: 向上
单位: 米 (m)

与云台坐标系通过云台角度关联
```

### 5. 世界坐标系 (World Frame)

```
Origin: 固定参考点
X-axis: 向北
Y-axis: 向西
Z-axis: 向上
单位: 米 (m)

惯性坐标系，与机器人本体通过 IMU 姿态关联
```

---

## 变换链

### 完整变换链

```
Pixel (u, v)
    ↓ [1] 去畸变 (可选)
Undistorted Pixel (u', v')
    ↓ [2] 归一化
Normalized Camera Coords (xn, yn)
    ↓ [3] 反投影
Camera Ray Direction (Xc, Yc, Zc)
    ↓ [4] 相机到云台旋转
Gimbal Frame Direction (Xg, Yg, Zg)
    ↓ [5] 提取角度误差
Angular Error (yaw_error, pitch_error)
```

---

## 数学推导

### [1] 去畸变 (Distortion Correction)

**畸变模型** (OpenCV 5-parameter model):

```
径向畸变:
  x_distorted = x_ideal * (1 + k1*r² + k2*r⁴ + k3*r⁶)
  y_distorted = y_ideal * (1 + k1*r² + k2*r⁴ + k3*r⁶)

切向畸变:
  x_distorted += 2*p1*x*y + p2*(r² + 2*x²)
  y_distorted += p1*(r² + 2*y²) + 2*p2*x*y

其中:
  r² = x² + y²
  (x, y) = 归一化坐标
```

**去畸变** (迭代求解):

给定畸变像素 `(u, v)`，求理想像素 `(u', v')`。

OpenCV 提供 `cv2.undistortPoints()` 函数直接求解。

---

### [2] 归一化 (Normalization)

**相机内参矩阵**:

```
K = ┌ fx  0  cx ┐
    │ 0  fy  cy │
    └ 0   0   1 ┘
```

**归一化坐标**:

```
xn = (u - cx) / fx
yn = (v - cy) / fy
```

**物理意义**:
- `(xn, yn)` 是相机坐标系中 Z=1 平面上的点
- 表示从光心出发的射线方向

---

### [3] 反投影 (Back-projection)

**相机射线方向**:

```
┌ Xc ┐   ┌ xn ┐
│ Yc │ = │ yn │
└ Zc ┘   └ 1  ┘
```

**归一化** (可选):

```
norm = √(Xc² + Yc² + Zc²)
Xc /= norm
Yc /= norm
Zc /= norm
```

---

### [4] 相机到云台旋转

**安装旋转矩阵** `R_cam2gimbal`:

由相机相对云台的安装角度 `(roll, pitch, yaw)` 计算：

```
R_cam2gimbal = Rz(yaw) @ Ry(pitch) @ Rx(roll)
```

**旋转矩阵定义** (ZYX 欧拉角):

```
Rx(α) = ┌ 1    0       0    ┐
        │ 0  cos(α) -sin(α) │
        └ 0  sin(α)  cos(α) ┘

Ry(β) = ┌  cos(β)  0  sin(β) ┐
        │    0     1    0    │
        └ -sin(β)  0  cos(β) ┘

Rz(γ) = ┌ cos(γ) -sin(γ)  0 ┐
        │ sin(γ)  cos(γ)  0 │
        └   0       0     1 ┘
```

**组合旋转矩阵**:

```
R = Rz(γ) @ Ry(β) @ Rx(α)

  = ┌ cy*cp                cy*sp*sr - sy*cr    cy*sp*cr + sy*sr ┐
    │ sy*cp                sy*sp*sr + cy*cr    sy*sp*cr - cy*sr │
    └ -sp                  cp*sr               cp*cr            ┘

其中:
  cx = cos(α), sx = sin(α)  (roll)
  cy = cos(β), sy = sin(β)  (pitch)
  cz = cos(γ), sz = sin(γ)  (yaw)
```

**云台坐标系方向**:

```
┌ Xg ┐       ┌ Xc ┐
│ Yg │ = R @ │ Yc │
└ Zg ┘       └ Zc ┘
```

---

### [5] 提取角度误差

**Yaw 误差** (水平角):

```
yaw_error = atan2(Xg, Zg)
```

**物理意义**:
- `Xg > 0`: 目标在云台右侧，需要向右转
- `Xg < 0`: 目标在云台左侧，需要向左转

**Pitch 误差** (俯仰角):

```
pitch_error = -atan2(Yg, Zg)
```

**注意符号**:
- 负号是因为相机 Y 轴向下，而 pitch 正方向是向上
- `Yg > 0`: 目标在云台下方，需要向下转 (pitch_error < 0)
- `Yg < 0`: 目标在云台上方，需要向上转 (pitch_error > 0)

---

## 完整变换公式

### 像素到角度误差

给定像素坐标 `(u, v)`，计算角度误差 `(yaw_error, pitch_error)`:

```python
# 1. 归一化
xn = (u - cx) / fx
yn = (v - cy) / fy

# 2. 相机射线
cam_dir = [xn, yn, 1.0]

# 3. 云台坐标系
gimbal_dir = R_cam2gimbal @ cam_dir

# 4. 提取角度
yaw_error = atan2(gimbal_dir[0], gimbal_dir[2])
pitch_error = -atan2(gimbal_dir[1], gimbal_dir[2])
```

### 小角度近似

当角度误差较小时 (< 10°)，可以使用线性近似：

```
yaw_error ≈ Xg / Zg ≈ xn  (弧度)
pitch_error ≈ -Yg / Zg ≈ -yn  (弧度)
```

**像素误差到角度误差**:

```
Δyaw (rad) ≈ Δu / fx
Δpitch (rad) ≈ -Δv / fy

Δyaw (deg) ≈ Δu / fx * 180/π
Δpitch (deg) ≈ -Δv / fy * 180/π
```

**示例**:
- 相机: 1280x720, fx=970, fy=965
- 目标偏离中心 100 像素 (水平)
- 角度误差: `100/970 * 180/π ≈ 5.9°`

---

## 扩展：完整链路变换

### 云台到本体 (Gimbal to Body)

**云台角度** `(yaw_gimbal, pitch_gimbal)`:

```
R_gimbal2body = Ry(-pitch_gimbal) @ Rz(yaw_gimbal)
```

**注意**:
- Yaw 先旋转（水平转台）
- Pitch 后旋转（俯仰轴）
- Pitch 使用负角度（约定差异）

### 本体到世界 (Body to World)

**IMU 姿态** `(roll_body, pitch_body, yaw_body)`:

```
R_body2world = Rz(yaw_body) @ Ry(pitch_body) @ Rx(roll_body)
```

### 完整链路

```
┌ Xw ┐
│ Yw │ = R_body2world @ R_gimbal2body @ R_cam2gimbal @ ┌ Xc ┐
└ Zw ┘                                                   │ Yc │
                                                         └ Zc ┘
```

---

## 逆变换：角度到像素

### 给定角度误差，计算像素位置

**输入**: `(yaw_error, pitch_error)` (度)

**输出**: `(u, v)` (像素)

```python
# 1. 构造云台方向向量
yaw_rad = radians(yaw_error)
pitch_rad = radians(pitch_error)

Xg = sin(yaw_rad)
Yg = -sin(pitch_rad)  # 注意负号
Zg = cos(yaw_rad) * cos(pitch_rad)

gimbal_dir = [Xg, Yg, Zg]

# 2. 云台到相机
cam_dir = R_cam2gimbal.T @ gimbal_dir

# 3. 归一化
xn = cam_dir[0] / cam_dir[2]
yn = cam_dir[1] / cam_dir[2]

# 4. 投影到像素
u = fx * xn + cx
v = fy * yn + cy
```

---

## 数值示例

### 示例 1: 中心点

**输入**: `(u, v) = (640, 360)` (画面中心)

**相机参数**: `fx=970, fy=965, cx=640, cy=360`

**计算**:
```
xn = (640 - 640) / 970 = 0
yn = (360 - 360) / 965 = 0

cam_dir = [0, 0, 1]
gimbal_dir = R @ [0, 0, 1] = [0, 0, 1]  (假设 R = I)

yaw_error = atan2(0, 1) = 0°
pitch_error = -atan2(0, 1) = 0°
```

**结果**: 中心点误差为 0

### 示例 2: 右上角

**输入**: `(u, v) = (800, 260)`

**计算**:
```
xn = (800 - 640) / 970 = 0.165
yn = (260 - 360) / 965 = -0.104

cam_dir = [0.165, -0.104, 1]
gimbal_dir = [0.165, -0.104, 1]  (假设 R = I)

yaw_error = atan2(0.165, 1) = 9.4°
pitch_error = -atan2(-0.104, 1) = 5.9°
```

**结果**: 目标在右上方，需要向右转 9.4°，向上转 5.9°

---

## 误差分析

### 标定误差

**相机内参误差**:
- fx, fy 误差 1% → 角度误差 1%
- cx, cy 误差 10 px → 角度误差 ~0.6°

**安装角度误差**:
- roll, pitch, yaw 误差 1° → 角度误差 ~1°

### 畸变校正误差

**未校正畸变**:
- 广角镜头 (FOV > 90°): 边缘误差可达 5-10°
- 标准镜头 (FOV ~ 60°): 边缘误差 < 1°

### 数值精度

**浮点精度**:
- `float32`: 角度精度 ~0.001°
- `float64`: 角度精度 ~1e-10°

**建议**: 使用 `float64` 进行坐标变换计算

---

## 实现参考

### Python 实现

```python
import numpy as np
import math

class PixelToGimbalTransform:
    def __init__(self, fx, fy, cx, cy, R_cam2gimbal=None):
        self.fx = fx
        self.fy = fy
        self.cx = cx
        self.cy = cy
        self.R = R_cam2gimbal if R_cam2gimbal is not None else np.eye(3)

    def pixel_to_angle_error(self, u, v):
        # 归一化
        xn = (u - self.cx) / self.fx
        yn = (v - self.cy) / self.fy

        # 相机射线
        cam_dir = np.array([xn, yn, 1.0])

        # 云台坐标系
        gimbal_dir = self.R @ cam_dir

        # 提取角度
        yaw_rad = math.atan2(gimbal_dir[0], gimbal_dir[2])
        pitch_rad = -math.atan2(gimbal_dir[1], gimbal_dir[2])

        return math.degrees(yaw_rad), math.degrees(pitch_rad)
```

### C++ 实现

```cpp
#include <Eigen/Dense>
#include <cmath>

class PixelToGimbalTransform {
public:
    PixelToGimbalTransform(double fx, double fy, double cx, double cy,
                           const Eigen::Matrix3d& R_cam2gimbal = Eigen::Matrix3d::Identity())
        : fx_(fx), fy_(fy), cx_(cx), cy_(cy), R_(R_cam2gimbal) {}

    std::pair<double, double> pixelToAngleError(double u, double v) {
        // 归一化
        double xn = (u - cx_) / fx_;
        double yn = (v - cy_) / fy_;

        // 相机射线
        Eigen::Vector3d cam_dir(xn, yn, 1.0);

        // 云台坐标系
        Eigen::Vector3d gimbal_dir = R_ * cam_dir;

        // 提取角度
        double yaw_rad = std::atan2(gimbal_dir.x(), gimbal_dir.z());
        double pitch_rad = -std::atan2(gimbal_dir.y(), gimbal_dir.z());

        return {yaw_rad * 180.0 / M_PI, pitch_rad * 180.0 / M_PI};
    }

private:
    double fx_, fy_, cx_, cy_;
    Eigen::Matrix3d R_;
};
```

---

## 参考文献

1. **相机标定**:
   - Zhang, Z. (2000). "A flexible new technique for camera calibration"
   - OpenCV Camera Calibration Tutorial

2. **坐标变换**:
   - Hartley, R., & Zisserman, A. (2004). "Multiple View Geometry in Computer Vision"

3. **旋转表示**:
   - Diebel, J. (2006). "Representing Attitude: Euler Angles, Unit Quaternions, and Rotation Vectors"

4. **云台控制**:
   - Siciliano, B., et al. (2009). "Robotics: Modelling, Planning and Control"

---

## 附录：常用公式

### 角度单位转换

```
弧度 = 度 * π / 180
度 = 弧度 * 180 / π
```

### 三角函数

```
tan(θ) = sin(θ) / cos(θ)
atan2(y, x) = angle of vector (x, y)
```

### 旋转矩阵性质

```
R^T = R^(-1)  (正交矩阵)
det(R) = 1    (行列式为 1)
R @ R^T = I   (单位矩阵)
```

### 小角度近似

```
sin(θ) ≈ θ
cos(θ) ≈ 1
tan(θ) ≈ θ
atan(θ) ≈ θ

(θ in radians, |θ| < 0.1)
```
