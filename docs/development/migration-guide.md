# 文件迁移指南

## 文件位置变更

如果你之前使用过本项目，以下是文件位置的变更说明：

### 运行脚本
| 旧位置 | 新位置 |
|--------|--------|
| `run_demo.py` | `scripts/run_demo.py` |
| `run_yolo_cam.py` | `scripts/run_yolo_cam.py` |
| `run_tests.sh` | `scripts/run_tests.sh` |
| `run_tests.bat` | `scripts/run_tests.bat` |

**更新命令：**
```bash
# 旧命令
python run_demo.py

# 新命令
python scripts/run_demo.py
```

### 测试文件
| 旧位置 | 新位置 |
|--------|--------|
| `test_*.py` | `tests/test_*.py` |

**更新命令：**
```bash
# 旧命令
pytest test_demo.py

# 新命令
pytest tests/test_demo.py
# 或运行所有测试
pytest tests/
```

### 模型文件
| 旧位置 | 新位置 |
|--------|--------|
| `yolo11n.pt` | `models/yolo11n.pt` |
| `yolo11n-seg.pt` | `models/yolo11n-seg.pt` |

**更新配置：**
如果你的代码中硬编码了模型路径，需要更新：
```python
# 旧路径
model_path = "yolo11n.pt"

# 新路径
model_path = "models/yolo11n.pt"
```

### 文档文件
| 旧位置 | 新位置 |
|--------|--------|
| `QUICK_REFERENCE.md` | `docs/QUICK_REFERENCE.md` |
| `RFlow.md` | `docs/RFlow.md` |
| 各种报告文件 | `docs/reports/*.md` |

### Git 操作建议

如果你有未提交的更改，建议：

1. **查看状态**
```bash
git status
```

2. **暂存所有更改**
```bash
git add -A
```

3. **提交整理**
```bash
git commit -m "refactor: 重组项目目录结构

- 移动测试文件到 tests/
- 移动脚本到 scripts/
- 移动模型到 models/
- 移动文档到 docs/
- 创建目录结构说明文档"
```

### 常见问题

**Q: 我的脚本找不到模型文件了？**
A: 更新模型路径为 `models/yolo11n.pt`

**Q: pytest 找不到测试文件？**
A: 使用 `pytest tests/` 运行测试

**Q: 我的自定义脚本该放哪里？**
A: 
- 运行脚本 → `scripts/`
- 测试脚本 → `tests/`
- 工具脚本 → `scripts/utils/`（可自行创建）

**Q: 虚拟环境 rws/ 还能用吗？**
A: 可以继续使用，已在 .gitignore 中忽略

### 兼容性说明

- ✅ 所有功能保持不变
- ✅ 配置文件位置不变
- ✅ 源代码位置不变（src/rws_tracking/）
- ⚠️ 需要更新脚本中的相对路径
- ⚠️ 需要更新 CI/CD 配置中的路径（如有）

### 回滚方法

如果需要回滚到整理前的状态：
```bash
git log --oneline  # 查找整理前的 commit
git reset --hard <commit-hash>  # 回滚到指定 commit
```
