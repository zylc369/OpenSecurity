# detect_env.py 测试用例

为 `.opencode/binary-analysis/scripts/detect_env.py`（环境自动检测脚本）提供代码化测试，覆盖核心可测单元：诊断日志、配置解析、缓存、依赖声明、工具检测、预装检查编排。

## 目录结构

```
test/detect_env/
├── conftest.py          # 共享 fixture：用 importlib 加载 detect_env.py 为模块
├── test_logging.py      # _warn（统一诊断日志）+ _stderr_tail（stderr 截断）
├── test_config.py       # _get_opencode_root + _load_ai_env + _ensure_ai_env_template + 缓存读写
├── test_tools.py        # Dependency dataclass + _build_install_cmd + _resolve_tool
├── test_detection.py    # _detect_package + _get_tool_version + playwright 系列 + _install_package
├── test_preinstall.py   # _check_preinstall（预装检查编排）
└── README.md            # 本文件
```

## 环境准备

测试使用工程根目录下的 `.venv_test` 虚拟环境（已加入 `.gitignore`），与运行环境隔离。

```bash
# 1. 创建虚拟环境
python -m venv .venv_test

# 2. 安装 pytest（唯一依赖，detect_env.py 本身只用标准库）
.venv_test/bin/pip install pytest
```

## 运行测试

```bash
# 运行全部测试
.venv_test/bin/python -m pytest test/detect_env/

# 运行单个文件
.venv_test/bin/python -m pytest test/detect_env/test_logging.py

# 运行单个测试类
.venv_test/bin/python -m pytest test/detect_env/test_detection.py::TestDetectPackage

# 显示详细输出
.venv_test/bin/python -m pytest test/detect_env/ -v
```

## 测试覆盖范围

| 文件 | 被测函数 | 测试数 | 关注点 |
|------|---------|--------|--------|
| test_logging.py | `_warn`, `_stderr_tail` | 13 | stderr 输出不污染 stdout（`--check-preinstall` 依赖纯 JSON stdout）；异常/详情拼接格式；stderr 截断边界 |
| test_config.py | `_get_opencode_root`, `_load_ai_env`, `_ensure_ai_env_template`, `_load_cache`, `_save_cache` | 17 | 环境变量优先级；`.ai_env` 解析（注释/空行/setdefault 优先级）；缓存 TTL/损坏/force |
| test_tools.py | `Dependency`, `_build_install_cmd`, `_resolve_tool` | 14 | dataclass 默认值；pip/conda 命令生成；env_var（IDA）+ PATH which 双模式解析 |
| test_detection.py | `_detect_package`, `_get_tool_version`, `_detect_playwright_browser`, `_post_install_playwright`, `_install_package`, `_check_playwright_post_install` | 25 | returncode 0/非0/timeout/OSError 各路径；诊断日志（`_warn`）触发；playwright 编排（skip/装/失败） |
| test_preinstall.py | `_check_preinstall` | 9 | agent 过滤；required/optional 分级；python/tool 分发；install_hint 生成；find_spec 异常上抛 |

**合计 78 个测试。**

## 测试策略

### 模块加载（conftest.py）

detect_env.py 位于 `.opencode/binary-analysis/scripts/`，非包结构，无法直接 `import`。`conftest.py` 用 `importlib.util.spec_from_file_location` 按文件路径加载为模块，提供 session 级 `env` fixture：

```python
@pytest.fixture(scope="session")
def env():
    """所有测试通过 env._warn / env._detect_package 等访问被测函数。"""
    ...
```

模块级代码仅计算路径常量（`AI_ENV_FILE` 等），无文件创建副作用，安全。

### mock 策略

| 依赖类型 | mock 方式 | 说明 |
|---------|----------|------|
| `subprocess.run` | `monkeypatch.setattr(env.subprocess, "run", mock)` | 返回 `SimpleNamespace` 模拟 `CompletedProcess`，覆盖 returncode 0/非0/timeout/OSError |
| `shutil.which` | `monkeypatch.setattr(env.shutil, "which", mock)` | 模拟 PATH 工具查找 |
| `importlib.util.find_spec` | `monkeypatch.setattr(importlib.util, "find_spec", mock)` | 模拟 Python 包检测（已装/缺失/异常） |
| 文件系统（`.ai_env`/缓存） | `tmp_path` + `monkeypatch.setattr(env, "AI_ENV_FILE", ...)` | 重定向到临时目录，测试后自动清理 |
| 模块级常量 | `monkeypatch.setattr(env, "PYTHON_PACKAGES", [...])` | 注入测试专用依赖列表 |

### 输出捕获

`_warn` 走 stderr，用 pytest 的 `capsys` fixture 捕获：

```python
def test_warn_stdout_clean(env, capsys):
    env._warn("diagnostic")
    captured = capsys.readouterr()
    assert captured.out == ""   # stdout 必须纯净
    assert "diagnostic" in captured.err
```

## 扩展测试

添加新测试时：

1. **纯函数**：直接调用 `env.<func>()`，用 `capsys` 捕获输出
2. **subprocess 函数**：用 `monkeypatch.setattr(env.subprocess, "run", _mock_run(...))`（`_mock_run` 见 test_detection.py）
3. **文件系统函数**：用 `tmp_path` 创建临时文件 + `monkeypatch.setattr(env, "<常量>", str(tmp_path / ...))`
4. **访问模块级常量**：通过 `env.PYTHON_PACKAGES` / `env.EXTERNAL_TOOLS` / `env.CACHE_TTL` 等
