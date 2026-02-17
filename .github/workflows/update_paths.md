# CI/CD 路径更新说明

如果你的 GitHub Actions 工作流中引用了以下文件，需要更新路径：

## 需要更新的路径

### 测试文件
```yaml
# 旧路径
- run: pytest test_demo.py

# 新路径
- run: pytest tests/test_demo.py
# 或
- run: pytest tests/
```

### 运行脚本
```yaml
# 旧路径
- run: python run_demo.py

# 新路径
- run: python scripts/run_demo.py
```

### 模型文件
```yaml
# 旧路径
- name: Download model
  run: wget -O yolo11n.pt ...

# 新路径
- name: Download model
  run: wget -O models/yolo11n.pt ...
```

## 检查清单

- [ ] 更新测试命令路径
- [ ] 更新脚本执行路径
- [ ] 更新模型文件路径
- [ ] 更新文档生成路径（如有）
- [ ] 测试 CI/CD 流程
