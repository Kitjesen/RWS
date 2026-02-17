# RWS 项目结构 - 最终版本

## 📁 根目录（已整理）

```
RWS/
├── README.md                   # 项目主文档
├── CHANGELOG.md                # 变更日志
├── CONTRIBUTING.md             # 贡献指南
├── LICENSE                     # MIT 许可证
├── config.yaml                 # 系统配置
├── requirements.txt            # Python 依赖
├── pyproject.toml              # 项目配置
├── .gitignore                  # Git 忽略规则
├── .gitattributes              # Git 属性
└── .pre-commit-config.yaml     # 预提交钩子
```

## 📚 文档目录（docs/）

```
docs/
├── README.md                   # 文档索引
├── TODO.md                     # 待办事项
│
├── getting-started/            # 🚀 新手入门
│   ├── quick-start.md
│   └── configuration.md
│
├── guides/                     # 📖 使用指南
│   ├── hardware-setup.md
│   ├── coordinate-math.md
│   ├── testing.md
│   ├── occlusion-handling.md
│   └── crosshair-design.md
│
├── api/                        # 🔌 API 文档
│   ├── README.md
│   ├── rest-api.md
│   ├── grpc-api.md
│   ├── quick-reference.md
│   └── examples/
│
├── architecture/               # 🏗️ 架构文档
│   ├── overview.md
│   └── quick-reference.md
│
├── development/                # 🛠️ 开发文档
│   ├── ci-status.md
│   ├── ci-fixes.md
│   └── migration-guide.md
│
└── reports/                    # 📊 项目报告
    ├── 2024-02-15-*.md
    ├── 2024-02-16-*.md
    ├── 2024-02-17-*.md
    └── PROJECT_STRUCTURE_ANALYSIS.md
```

## 🔧 脚本目录（scripts/）

```
scripts/
├── migrate_structure.py        # 结构迁移工具
│
├── api/                        # API 服务器和客户端
│   ├── run_rest_server.py
│   ├── run_grpc_server.py
│   ├── rest_client_example.py
│   └── grpc_client_example.py
│
├── demo/                       # 演示脚本
│   ├── run_simple_demo.py
│   └── run_camera_demo.py
│
├── tools/                      # 开发工具
│   ├── generate_proto.bat
│   └── generate_proto.sh
│
└── tests/                      # 测试脚本
    ├── run_tests.sh
    ├── run_tests.bat
    └── test_api.py
```

## 💻 源代码目录（src/rws_tracking/）

```
src/rws_tracking/
├── __init__.py
├── types.py                    # 数据类型定义
├── interfaces.py               # 接口协议
├── config.py                   # 配置管理
│
├── algebra/                    # 数学/几何模块
│   ├── coordinate_transform.py
│   └── kalman2d.py
│
├── perception/                 # 感知层
│   ├── yolo_detector.py
│   ├── yolo_seg_tracker.py
│   ├── tracker.py
│   └── selector.py
│
├── decision/                   # 决策层
│   └── state_machine.py
│
├── control/                    # 控制层
│   ├── controller.py
│   ├── adaptive.py
│   └── ballistic.py
│
├── hardware/                   # 硬件接口
│   ├── driver.py
│   ├── serial_driver.py
│   └── imu_interface.py
│
├── pipeline/                   # 主流程
│   ├── pipeline.py
│   ├── app.py
│   └── multi_gimbal_pipeline.py
│
├── telemetry/                  # 遥测日志
│   └── logger.py
│
├── api/                        # REST & gRPC API
│   ├── __init__.py
│   ├── server.py               # REST 服务器
│   ├── client.py               # REST 客户端
│   ├── grpc_server.py          # gRPC 服务器
│   ├── grpc_client.py          # gRPC 客户端
│   ├── tracking.proto          # Protobuf 定义
│   ├── tracking_pb2.py         # 生成的消息
│   └── tracking_pb2_grpc.py    # 生成的服务
│
└── tools/                      # 工具模块
    ├── simulation/
    └── training/
```

## 🧪 测试目录（tests/）

```
tests/
├── benchmarks/                 # 性能基准测试
├── test_algebra.py
├── test_control.py
├── test_perception.py
├── test_pipeline.py
└── ... (17 个测试文件)
```

## 📦 其他目录

```
models/                         # 模型文件
dataset/                        # 数据集
    ├── images/
    └── labels/
output/                         # 输出目录
test_videos/                    # 测试视频
```

## 📊 项目统计

- **文档**: 44 个 Markdown 文件，8 个分类目录
- **脚本**: 12 个脚本文件，4 个功能分组
- **源码**: 61 个 Python 文件，9 个核心模块
- **测试**: 17 个测试文件 + 基准测试
- **API**: REST (8 端点) + gRPC (9 方法)

## 🎯 目录设计原则

1. **根目录简洁** - 只保留核心配置文件
2. **文档分类** - 按用途分为 6 个子目录
3. **脚本分组** - 按功能分为 4 个子目录
4. **源码模块化** - 清晰的模块划分
5. **命名规范** - 统一的命名约定

## 🚀 快速导航

### 新用户
1. 阅读 `README.md`
2. 查看 `docs/getting-started/quick-start.md`
3. 运行 `python scripts/demo/run_simple_demo.py`

### API 用户
1. 阅读 `docs/api/README.md`
2. 启动服务器 `python scripts/api/run_rest_server.py`
3. 查看示例 `scripts/api/rest_client_example.py`

### 开发者
1. 阅读 `CONTRIBUTING.md`
2. 查看 `docs/architecture/overview.md`
3. 运行测试 `python scripts/tests/run_tests.sh`

## ✨ 重构成果

- ✅ 根目录整洁（10 个核心文件）
- ✅ 文档结构清晰（6 个分类）
- ✅ 脚本组织合理（4 个分组）
- ✅ 符合开源最佳实践
- ✅ 易于导航和维护

---

**最后更新**: 2024-02-17
**版本**: v1.2.0
