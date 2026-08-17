# 依赖体系测试（唯一清单 + 检测 + 安装）

被测对象（2026-08-16 收口后架构，安装器已并入清单文件）：
- `.opencode/control/backend/services/detect_py_deps.py` —— Python 依赖唯一清单 + scan 检测（import/CLI 双入口）+ install 安装子命令（venv 自举 + 全部必需依赖）
- `.opencode/control/backend/services/detect_tools.py` —— 外部工具 + 编译器检测

```
test/deps/
├── conftest.py            # 文件路径加载 fixture（py_deps）
├── test_logging.py        # _warn/_log stderr 收口
├── test_py_deps.py        # install=全部 required 对齐/agent 过滤/pip 白名单/CLI-import 一致性/dry-run
└── test_detect_tools.py   # 编译器检测 + 工具清单完整性 + 兼容层指向唯一清单
```

运行：
```bash
python -m pytest test/deps/ -v
```

环境检测的 HTTP 链路由 `test/control/`（控制台 API）与 plugin TS 测试覆盖。
