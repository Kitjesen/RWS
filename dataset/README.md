# RWS 数据集目录

## 目录结构

```
dataset/
├── images/
│   ├── train/          ← 训练图片放这里（jpg / png）
│   └── val/            ← 验证图片放这里（建议 ~20% 的量）
├── labels/
│   ├── train/          ← 训练标注放这里（每张图对应一个同名 .txt）
│   └── val/            ← 验证标注放这里
├── data.yaml           ← 数据集描述（类别名称、路径）
└── README.md           ← 本文件
```

## 怎么放图片

1. 把你的目标图片（`.jpg` 或 `.png`）放进 `images/train/`
2. 抽 ~20% 放进 `images/val/`（验证集）
3. 图片命名随意，但要保证 **图片和标注文件同名**

示例：
```
images/train/001.jpg   →   labels/train/001.txt
images/train/002.jpg   →   labels/train/002.txt
images/val/003.jpg     →   labels/val/003.txt
```

## 标注格式（YOLO 格式）

每个 `.txt` 文件，每行一个目标框：

```
class_id  cx  cy  w  h
```

- `class_id` — 类别编号（从 0 开始，对应 data.yaml 里的 names 顺序）
- `cx, cy` — 框中心点的 **归一化** 坐标（0~1，相对于图片宽高）
- `w, h` — 框宽高的 **归一化** 值（0~1）

示例（一张图里有 2 个目标）：
```
0  0.512  0.340  0.120  0.250
0  0.780  0.610  0.090  0.180
```

## 标注工具推荐

| 工具 | 说明 |
|------|------|
| [LabelImg](https://github.com/HumanSignal/labelImg) | 本地桌面工具，轻量，直接导出 YOLO 格式 |
| [Roboflow](https://roboflow.com) | 网页端标注，支持拖拽，可导出 YOLO 格式 |
| [CVAT](https://github.com/opencv/cvat) | 开源网页标注平台，功能强大 |

## 标注完后

运行训练脚本：
```bash
python -m src.rws_tracking.tools.training.train
```
