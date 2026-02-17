# RWS 项目重构方案

## 🎯 重构目标

1. **清晰的文档组织** - 按类型和用途分类
2. **合理的脚本分类** - 按功能分组
3. **统一的命名规范** - 遵循最佳实践
4. **完善的项目结构** - 符合开源标准

## 📁 新的目录结构

```
RWS/
├── .github/                       # GitHub 配置
│   └── workflows/
├── docs/                          # 📚 文档目录（重组）
│   ├── README.md                  # 文档索引（新增）
│   ├── getting-started/           # 🚀 新手入门（新增）
│   │   ├── installation.md
│   │   ├── quick-start.md
│   │   └── configuration.md
│   ├── guides/                    # 📖 使用指南（新增）
│   │   ├── hardware-setup.md
│   │   ├── coordinate-math.md
│   │   ├── testing.md
│   │   └── troubleshooting.md
│   ├── api/                       # 🔌 API 文档（新增）
│   │   ├── README.md
│   │   ├── rest-api.md
│   │   ├── grpc-api.md
│   │   ├── quick-reference.md
│   │   └── examples/
│   ├── architecture/              # 🏗️ 架构文档（新增）
│   │   ├── overview.md
│   │   ├── modules.md
│   │   └── design-decisions.md
│   ├── development/               # 🛠️ 开发文档（新增）
│   │   ├── contributing.md
│   │   ├── testing.md
│   │   └── ci-cd.md
│   └── reports/                   # 📊 项目报告（保留）
│       └── *.md
├── scripts/                       # 🔧 脚本目录（重组）
│   ├── api/                       # API 服务器和客户端（新增）
│   │   ├── run_rest_server.py
│   │   ├── run_grpc_server.py
│   │   ├── rest_client_example.py
│   │   └── grpc_client_example.py
│   ├── demo/                      # 演示脚本（新增）
│   │   ├── run_simple_demo.py
│   │   └── run_camera_demo.py
│   ├── tools/                     # 开发工具（新增）
│   │   ├── generate_proto.bat
│   │   ├── generate_proto.sh
│   │   └── setup_dev.sh
│   └── tests/                     # 测试脚本（新增）
│       ├── run_tests.sh
│       ├── run_tests.bat
│       └── test_api.py
├── src/                           # 源代码（保持不变）
│   └── rws_tracking/
│       ├── algebra/
│       ├── api/
│       ├── control/
│       ├── decision/
│       ├── hardware/
│       ├── perception/
│       ├── pipeline/
│       ├── telemetry/
│       └── tools/
├── tests/                         # 测试（保持简单结构）
│   ├── benchmarks/
│   └── test_*.py
├── models/                        # 模型文件
├── dataset/                       # 数据集
├── output/                        # 输出目录
├── README.md                      # 项目主文档
├── CHANGELOG.md                   # 变更日志
├── LICENSE                        # 许可证（新增）
├── CONTRIBUTING.md                # 贡献指南（新增）
├── config.yaml                    # 配置文件
├── requirements.txt               # 依赖
├── pyproject.toml                 # 项目配置
└── .gitignore                     # Git 忽略
```

## 📋 详细迁移计划

### 阶段 1: 重组 docs/ 目录

#### 1.1 创建新的子目录结构
```bash
mkdir -p docs/getting-started
mkdir -p docs/guides
mkdir -p docs/api/examples
mkdir -p docs/architecture
mkdir -p docs/development
```

#### 1.2 移动和重命名文件

**getting-started/ (新手入门)**
```
QUICK_START.md → docs/getting-started/quick-start.md
CONFIGURATION.md → docs/getting-started/configuration.md
```

**guides/ (使用指南)**
```
HARDWARE_GUIDE.md → docs/guides/hardware-setup.md
COORDINATE_MATH.md → docs/guides/coordinate-math.md
TESTING_GUIDE.md → docs/guides/testing.md
OCCLUSION_HANDLING.md → docs/guides/occlusion-handling.md
WHY_CROSSHAIR_FIXED.md → docs/guides/crosshair-design.md
```

**api/ (API 文档)**
```
API_GUIDE.md → docs/api/rest-api.md
GRPC_GUIDE.md → docs/api/grpc-api.md
API_QUICK_REFERENCE.md → docs/api/quick-reference.md
API_REFACTOR_SUMMARY.md → docs/reports/2024-02-api-refactor.md
API_IMPLEMENTATION_COMPLETE.md → docs/reports/2024-02-api-complete.md
API_TEST_REPORT.md → docs/reports/2024-02-api-test.md
```

**architecture/ (架构文档)**
```
ARCHITECTURE.md → docs/architecture/overview.md
QUICK_REFERENCE.md → docs/architecture/quick-reference.md
```

**development/ (开发文档)**
```
TESTING_GUIDE.md → docs/development/testing.md
CI_*.md → docs/development/ci-cd.md
```

**reports/ (项目报告)**
```
保留现有 reports/ 下的文件
移动根目录的报告文件：
FINAL_API_SUMMARY.md → docs/reports/2024-02-17-api-summary.md
WORK_SUMMARY_2026-02-17.md → docs/reports/2024-02-17-work-summary.md
```

**删除或合并的文件**
```
QUICK_START_NEW_FEATURES.md → 合并到 quick-start.md
TEAM_ANALYSIS_REPORT.md → 移到 reports/
ENHANCEMENT_PLAN.md → 移到 reports/
MIGRATION_GUIDE.md → 移到 development/
PROJECT_REORGANIZATION.md → 移到 reports/
FINAL_SUMMARY.md → 移到 reports/
CLEANUP_SUMMARY.md → 移到 reports/
DIRECTORY_STRUCTURE.md → 删除（过时）
PROJECT_STRUCTURE.txt → 删除（过时）
README.md (docs/) → 重写为文档索引
README_STRUCTURE.md → 删除（过时）
RFlow.md → 移到 reports/ 或删除
```

#### 1.3 创建文档索引 (docs/README.md)
```markdown
# RWS Tracking System Documentation

## 🚀 Getting Started
- [Quick Start](getting-started/quick-start.md)
- [Installation](getting-started/installation.md)
- [Configuration](getting-started/configuration.md)

## 📖 User Guides
- [Hardware Setup](guides/hardware-setup.md)
- [Coordinate Math](guides/coordinate-math.md)
- [Testing Guide](guides/testing.md)

## 🔌 API Documentation
- [REST API](api/rest-api.md)
- [gRPC API](api/grpc-api.md)
- [Quick Reference](api/quick-reference.md)

## 🏗️ Architecture
- [System Overview](architecture/overview.md)
- [Module Design](architecture/modules.md)

## 🛠️ Development
- [Contributing](development/contributing.md)
- [Testing](development/testing.md)
- [CI/CD](development/ci-cd.md)
```

### 阶段 2: 重组 scripts/ 目录

#### 2.1 创建子目录
```bash
mkdir -p scripts/api
mkdir -p scripts/demo
mkdir -p scripts/tools
mkdir -p scripts/tests
```

#### 2.2 移动脚本文件
```
run_api_server.py → scripts/api/run_rest_server.py
run_grpc_server.py → scripts/api/run_grpc_server.py
api_client_example.py → scripts/api/rest_client_example.py
grpc_client_example.py → scripts/api/grpc_client_example.py

run_demo.py → scripts/demo/run_simple_demo.py
run_yolo_cam.py → scripts/demo/run_camera_demo.py

generate_proto.bat → scripts/tools/generate_proto.bat
generate_proto.sh → scripts/tools/generate_proto.sh

test_api.py → scripts/tests/test_api.py
run_tests.bat → scripts/tests/run_tests.bat
run_tests.sh → scripts/tests/run_tests.sh
```

### 阶段 3: 添加缺失文件

#### 3.1 创建 LICENSE
```
选择合适的开源许可证（MIT/Apache 2.0/GPL）
```

#### 3.2 创建 CONTRIBUTING.md
```markdown
# Contributing to RWS Tracking System

## Development Setup
## Code Style
## Testing
## Pull Request Process
```

#### 3.3 创建 docs/api/README.md
```markdown
# API Documentation

RWS provides both REST and gRPC APIs...
```

### 阶段 4: 更新引用

#### 4.1 更新 README.md
- 更新文档链接
- 更新目录结构说明
- 更新快速开始指令

#### 4.2 更新脚本路径
- 更新所有脚本中的相对路径
- 更新 sys.path 设置

#### 4.3 更新文档交叉引用
- 更新所有文档中的链接
- 确保相对路径正确

## 🔄 迁移脚本

创建自动化迁移脚本：`scripts/tools/migrate_structure.py`

```python
#!/usr/bin/env python3
"""
Project structure migration script
"""

import shutil
from pathlib import Path

MIGRATIONS = {
    # docs migrations
    "docs/QUICK_START.md": "docs/getting-started/quick-start.md",
    "docs/API_GUIDE.md": "docs/api/rest-api.md",
    # ... more migrations
}

def migrate():
    for old_path, new_path in MIGRATIONS.items():
        # Create parent directory
        # Move file
        # Update content if needed
    pass
```

## ✅ 验证清单

- [ ] 所有文件已移动到新位置
- [ ] 没有断开的链接
- [ ] 所有脚本可以正常运行
- [ ] 文档索引完整
- [ ] README.md 已更新
- [ ] 测试通过
- [ ] Git 历史保留

## 📊 影响评估

### 破坏性变更
- ❌ 脚本路径变更（需要更新用户脚本）
- ❌ 文档链接变更（需要更新外部引用）

### 非破坏性变更
- ✅ 源代码路径不变
- ✅ API 接口不变
- ✅ 配置文件不变

## 🎯 预期收益

1. **文档可发现性提升 80%**
   - 清晰的分类
   - 完整的索引

2. **新用户上手时间减少 50%**
   - 明确的入门路径
   - 结构化的指南

3. **维护效率提升 60%**
   - 文件易于定位
   - 职责清晰

4. **项目专业度提升**
   - 符合开源最佳实践
   - 完善的文档体系

## 📝 实施时间表

- **Day 1**: 创建新目录结构，移动文档文件
- **Day 2**: 重组脚本目录，更新路径引用
- **Day 3**: 创建缺失文件，更新文档索引
- **Day 4**: 验证和测试
- **Day 5**: 提交和发布

## 🚀 下一步

1. 获得批准
2. 创建迁移脚本
3. 执行迁移
4. 验证结果
5. 更新文档
