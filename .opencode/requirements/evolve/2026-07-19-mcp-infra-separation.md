# MCP 基础设施职责分离与 pyproject.toml 单一事实源

## §1 背景与目标

### 来源痛点

实测发现三个相互关联的问题：

| # | 痛点 | 根因 |
|---|------|------|
| 1 | **ETIMEDOUT**：用户启动 OpenCode 时 detect_env 经常超时 | `env-check.ts:107` plugin 给 detect_env 8s timeout，但 detect_env.py 的 `_detect_mcp_deps` 调 `_ensure_docker_running`（最多 90s）尝试启动 Docker |
| 2 | **Docker 启动了但容器没启动** | daemon 启动后才能 `docker start neo4j-events`，但 detect_env 被 8s timeout 杀，第二步没机会执行 |
| 3 | **依赖声明 3 处重复** | detect_env.py 的 `mcp_config` 字典 + `pyproject.toml` 的 `dependencies` + `mcp-manager.ts` 的 `requiredPackages` —— 三处可能不同步 |

### 根因总结

**职责混乱**：detect_env.py `check-preinstall` 子命令既检测又启动，违反单一职责原则。

- 检测：应该快速返回（<8s），不产生副作用
- 启动：耗时（90s+），应该在异步路径做

### 实测证据

```
plugin spawn detect_env check-preinstall（8s timeout）
  → 检测 Python 包/编译器/IDA（~5s）
  → 进入 _detect_mcp_deps → _ensure_docker_running
  → open -a Docker（异步启动 Docker Desktop）
  → 轮询 docker info 每 3s（最多 90s）
  → plugin 8s timeout 触发 → 强制杀进程
  → 用户看到最后一行日志"正在启动 Docker Desktop"
  → Docker Desktop 继续启动（30-60s 后就绪）
  → 但 detect_env 已死，永远不会执行 docker start neo4j-events
```

### 改造目标

1. **职责分离**：check-preinstall 只检测不启动；启动放 events/server.py lifespan（异步）
2. **单一事实源**：pyproject.toml 是 MCP server 元数据的唯一声明位置
3. **消除重复检测**：mcp-manager.ts 删除 requiredPackages 预检测（直接 spawn server，依赖错误从 stderr 捕获）

### 预期收益

| 维度 | 改造前 | 改造后 |
|------|--------|--------|
| **用户启动体验** | ETIMEDOUT（8s 后失败） | check-preinstall <5s 完成（无副作用） |
| **Docker 容器可靠性** | 容器经常没启动（进程被杀） | lifespan 子线程完整执行（不被外部 timeout 杀） |
| **代码维护性** | 依赖声明 3 处重复 | pyproject.toml 单一事实源 |
| **启动时间** | mcp-manager.ts checkPackages 2-4s | 删除预检测，直接注册（节省 2-4s） |

---

## §2 技术方案

### 2.1 pyproject.toml 作为单一事实源

每个 MCP server 的 pyproject.toml 增加 `[tool.opensecurity]` section 声明运行时元数据：

```toml
# events/pyproject.toml
[project]
name = "opensec-events-mcp"
version = "0.2.0"
dependencies = ["mcp>=1.0", "graphiti-core>=0.29"]

[tool.opensecurity]
import_names = ["mcp", "graphiti_core"]
requires_docker = "neo4j-events"  # 期望的容器名；不写 = 不需要 Docker
```

```toml
# knowledge/pyproject.toml
[project]
name = "opensec-knowledge-mcp"
version = "0.1.0"
dependencies = ["mcp>=1.0", "sentence-transformers>=2.7", "sqlite-vec>=0.1"]

[tool.opensecurity]
import_names = ["mcp", "sentence_transformers", "sqlite_vec"]
# 无 requires_docker = 不需要 Docker
```

**字段说明**：
- `import_names`：检测时用 `__import__(name)` 的包名列表（已转换为 import 形式，如 `sentence_transformers` 而非 `sentence-transformers`）
- `requires_docker`：可选，声明期望的 Docker 容器名。若设置，detect_env.py check-preinstall 检测该容器状态（但不启动）；events/server.py lifespan 启动该容器

### 2.2 detect_env.py 改造

#### 改动 1：加 `_load_mcp_metadata()` 从 pyproject.toml 读

```python
def _load_mcp_metadata():
    """从 mcp-servers/<name>/pyproject.toml 读 MCP server 元数据。
    
    返回 {server_name: {script, packages, requires_docker}} 字典。
    解析失败时打印 stderr 日志（不降级到硬编码）。
    """
    import tomllib  # Python 3.11+ 内置
    
    opencode_root = _get_opencode_root()
    result = {}
    for server_name in ["knowledge", "events"]:
        toml_path = os.path.join(opencode_root, "mcp-servers", server_name, "pyproject.toml")
        if not os.path.exists(toml_path):
            _warn(f"_load_mcp_metadata: {toml_path} 不存在")
            continue
        try:
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
            tool_cfg = data.get("tool", {}).get("opensecurity", {})
            result[server_name] = {
                "script": os.path.join(opencode_root, "mcp-servers", server_name, "server.py"),
                "packages": tool_cfg.get("import_names", []),
                "requires_docker": tool_cfg.get("requires_docker"),  # None 或容器名
            }
        except Exception as e:
            _warn(f"_load_mcp_metadata: 解析 {toml_path} 失败: {e}", exc=e)
    return result
```

#### 改动 2：拆分 `_detect_mcp_deps` 为检测和启动两部分

```python
def _check_mcp_deps_fast():
    """快速检测 MCP 依赖状态（check-preinstall 用，不启动任何东西）。
    
    检测项：
    - Python 包：__import__(name)
    - Docker 二进制：docker --version（仅检查存在，不连 daemon）
    - Docker daemon：docker info（仅检查状态，不启动）
    - 容器状态：docker ps（仅检查运行状态，不启动）
    
    返回 {server_name: {available, missing, docker_status, container_status}} 字典。
    """
    metadata = _load_mcp_metadata()
    result = {}
    for name, cfg in metadata.items():
        # 1. Python 包检测
        missing = []
        for pkg in cfg["packages"]:
            try:
                __import__(pkg)
            except ImportError:
                missing.append(pkg)
        
        # 2. Docker 检测（如果声明了 requires_docker）
        docker_status = None
        container_status = None
        if cfg.get("requires_docker"):
            docker_status = _check_docker_binary_and_daemon()  # 不启动
            if docker_status["daemon_running"]:
                container_status = _check_container_status(cfg["requires_docker"])  # 不启动
        
        result[name] = {
            "available": len(missing) == 0,
            "missing": missing,
            "script": cfg["script"],
            "docker_status": docker_status,
            "container_status": container_status,
        }
    return result


def _ensure_mcp_infra():
    """启动 MCP 基础设施（install 子命令用）。
    
    职责：
    - 启动 Docker daemon（如果未运行）
    - 启动声明的容器（如果停止）
    - 创建容器（如果不存在，仅 install 模式）
    
    check-preinstall 不调用此函数。
    """
    metadata = _load_mcp_metadata()
    for name, cfg in metadata.items():
        if not cfg.get("requires_docker"):
            continue
        # 启动 Docker daemon
        _ensure_docker_running()
        # 启动容器
        _ensure_container_running(cfg["requires_docker"])
```

#### 改动 3：`_check_preinstall` 改为调 `_check_mcp_deps_fast`

```python
def _check_preinstall(agent):
    # ... 前面的检测不变 ...
    
    # --- 5. MCP 依赖检测（快速，不启动）---
    mcp_servers = _check_mcp_deps_fast()  # ← 改为 fast 版本
    
    # ... 后续逻辑不变 ...
```

#### 新增辅助函数（不启动，仅检测）

```python
def _check_docker_binary_and_daemon():
    """检测 Docker 二进制存在 + daemon 运行状态（不启动）。"""
    import subprocess as sp
    # 1. docker --version（检查二进制）
    try:
        sp.run(["docker", "--version"], capture_output=True, timeout=3, check=True)
    except (FileNotFoundError, sp.TimeoutExpired, sp.CalledProcessError):
        return {"installed": False, "daemon_running": False}
    # 2. docker info（检查 daemon）
    try:
        sp.run(["docker", "info"], capture_output=True, timeout=3, check=True)
        return {"installed": True, "daemon_running": True}
    except (sp.TimeoutExpired, sp.CalledProcessError):
        return {"installed": True, "daemon_running": False}


def _check_container_status(container_name):
    """检测容器状态（不启动）。返回 'running' / 'stopped' / 'not_exists'。"""
    import subprocess as sp
    # 1. docker ps（运行中的容器）
    r = sp.run(["docker", "ps", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
               capture_output=True, timeout=5, text=True)
    if r.stdout.strip() == container_name:
        return "running"
    # 2. docker ps -a（所有容器，含停止的）
    r = sp.run(["docker", "ps", "-a", "--filter", f"name={container_name}", "--format", "{{.Names}}"],
               capture_output=True, timeout=5, text=True)
    if r.stdout.strip() == container_name:
        return "stopped"
    return "not_exists"
```

### 2.3 events/server.py 改造 — lifespan 子线程启动 Docker + 容器 + 模型

```python
def _ensure_docker_daemon_blocking(timeout=90):
    """子线程：确保 Docker daemon 运行（首次启动可能耗时 30-90s）。
    
    步骤：
    1. docker --version（检查二进制存在）
    2. docker info（检查 daemon 状态）
    3. 若未运行 → 启动 daemon（open -a Docker / systemctl start docker）
    4. 轮询 docker info（最多 timeout 秒）
    """
    import subprocess as sp
    import platform
    
    # 1. 检查二进制
    try:
        sp.run(["docker", "--version"], capture_output=True, timeout=3, check=True)
    except (FileNotFoundError, sp.TimeoutExpired):
        raise RuntimeError("Docker 未安装（events MCP 需要 Docker 运行 Neo4j）")
    
    # 2. 已运行？
    try:
        sp.run(["docker", "info"], capture_output=True, timeout=3, check=True)
        return
    except (sp.TimeoutExpired, sp.CalledProcessError):
        pass
    
    # 3. 启动 daemon
    system = platform.system()
    if system == "Darwin":
        sp.run(["open", "-a", "Docker"], check=True)
    elif system == "Linux":
        if shutil.which("systemctl"):
            sp.run(["systemctl", "start", "docker"], check=False)
        elif shutil.which("service"):
            sp.run(["service", "docker", "start"], check=False)
    else:
        raise RuntimeError(f"不支持的系统: {system}")
    
    # 4. 轮询
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(3)
        try:
            sp.run(["docker", "info"], capture_output=True, timeout=3, check=True)
            return
        except (sp.TimeoutExpired, sp.CalledProcessError):
            continue
    raise RuntimeError(f"Docker daemon 启动超时（{timeout}s）")


def _ensure_neo4j_container_blocking():
    """子线程：确保 neo4j-events 容器运行（不存在则创建）。"""
    import subprocess as sp
    CONTAINER = "neo4j-events"
    IMAGE = "neo4j:5"
    
    # 1. 容器已运行？
    r = sp.run(["docker", "ps", "--filter", f"name={CONTAINER}", "--format", "{{.Names}}"],
               capture_output=True, timeout=10, text=True)
    if r.stdout.strip() == CONTAINER:
        return
    
    # 2. 容器存在但停止？
    r = sp.run(["docker", "ps", "-a", "--filter", f"name={CONTAINER}", "--format", "{{.Names}}"],
               capture_output=True, timeout=10, text=True)
    if r.stdout.strip() == CONTAINER:
        sp.run(["docker", "start", CONTAINER], capture_output=True, timeout=30, check=True)
        return
    
    # 3. 容器不存在 → 创建
    data_dir = os.path.expanduser("~/bw-security-analysis/db/events")
    os.makedirs(data_dir, exist_ok=True)
    # docker pull（显示进度）
    _pull_image_with_progress(IMAGE)
    sp.run(
        ["docker", "run", "-d", "--name", CONTAINER,
         "-p", "7474:7474", "-p", "7687:7687",
         "-e", "NEO4J_AUTH=neo4j/neo4j_password",
         "-v", f"{data_dir}:/data", IMAGE],
        capture_output=True, timeout=60, check=True,
    )


def _preload_models_blocking() -> None:
    """子线程：Docker daemon + 容器 + BGE-M3 加载（按顺序）。
    
    完整初始化序列：
    1. 确保 Docker daemon 运行
    2. 确保 neo4j-events 容器运行
    3. 创建 Graphiti 对象 + 加载 BGE-M3
    
    任何步骤失败 → _init_error 记录 → finally 唤醒 _ready。
    工具调用 await _ready.wait() 后，要么全部就绪，要么抛 RuntimeError。
    """
    try:
        print("[events-mcp] 确保 Docker daemon 运行...", file=sys.stderr)
        _ensure_docker_daemon_blocking()
        print("[events-mcp] 确保 neo4j-events 容器运行...", file=sys.stderr)
        _ensure_neo4j_container_blocking()
        print("[events-mcp] 加载 BGE-M3...", file=sys.stderr)
        from graphiti_config import create_graphiti
        graphiti, err = create_graphiti()
        if err:
            _init_error.append(RuntimeError(err))
            return
        _ = graphiti.embedder.model  # 触发 BGE-M3 加载
        _state["graphiti"] = graphiti
        print("[events-mcp] 全部就绪", file=sys.stderr)
    except Exception as e:
        _init_error.append(e)
        print(f"[events-mcp] 初始化失败: {e}", file=sys.stderr)
    finally:
        if _loop is not None:
            _loop.call_soon_threadsafe(_ready.set)
```

### 2.4 mcp-manager.ts 改造 — 删除 checkPackages，直接注册

```typescript
// 改造前
const MCP_SERVERS = [
  { name: "knowledge", script: ..., timeout: 60000, requiredPackages: [...] },
  { name: "events", script: ..., timeout: 10000, requiredPackages: [...] },
];

private async registerOne(server, venvPython) {
  const missing = this.checkPackages(venvPython, server.requiredPackages);
  if (missing.length > 0) {
    debugLog(`跳过：缺少依赖包 ${missing.join(", ")}`);
    return;
  }
  // ... client.mcp.add ...
}

// 改造后
const MCP_SERVERS = [
  { name: "knowledge", script: ..., timeout: 60000 },  // ← 删除 requiredPackages
  { name: "events", script: ..., timeout: 10000 },     // ← 删除 requiredPackages
];

private async registerOne(server, venvPython) {
  // 直接 client.mcp.add；如果 server.py 缺依赖，握手失败 → status=failed
  try {
    await this.client.mcp.add({ ... });
    debugLog(`[McpManager] ${name} 注册成功`);
  } catch (e) {
    debugLog(`[McpManager] ${name} 注册失败：${e?.message ?? e}`);
    if (e?.stderr) {
      debugLog(`  server stderr: ${e.stderr.toString().slice(-500)}`);
    }
  }
}
```

**删除的内容**：
- `requiredPackages` 字段（2 处）
- `checkPackages` 方法（17 行）
- 节省每个 server 启动时 ~1-2s 同步子进程开销

### 2.5 不改造的部分

- `knowledge/server.py`：不依赖 Docker，lifespan 已是 lazy 加载，不变
- `plugin security-analysis.ts`：fire-and-forget 模式不变
- `chat.message hook` 检测流程：不变（用户发消息触发 check-preinstall）
- `install.sh` / `detect_env install`：保持启动 Docker/容器职责（_ensure_mcp_infra）

---

## §3 实现规范

### 改动范围表

| 文件 | 改动类型 | 行数估计 |
|------|---------|---------|
| `.opencode/mcp-servers/events/pyproject.toml` | 加 `[tool.opensecurity]` section | +5 行 |
| `.opencode/mcp-servers/knowledge/pyproject.toml` | 加 `[tool.opensecurity]` section | +4 行 |
| `.opencode/binary-analysis/scripts/detect_env.py` | 加 `_load_mcp_metadata` + 拆分检测/启动 + 删除 `_detect_mcp_deps` 内启动逻辑 | ~+80 行 / -30 行 |
| `.opencode/mcp-servers/events/server.py` | 加 `_ensure_docker_daemon_blocking` + `_ensure_neo4j_container_blocking` + 改 `_preload_models_blocking` | ~+100 行 |
| `.opencode/plugins/lib/mcp-manager.ts` | 删除 `requiredPackages` + `checkPackages` | -25 行 |
| `test/mcp_events/test_docker_lifecycle.py` | 新增 Docker 启动路径测试 | ~120 行 |

### 编码规则

1. **pyproject.toml 单一事实源**：MCP server 的依赖、import_names、requires_docker 全部声明在 `[tool.opensecurity]` section
2. **检测与启动分离**：`_check_mcp_deps_fast` 只做无副作用的检测（docker --version/info/ps）；`_ensure_*_blocking` 才有副作用（启动）
3. **Docker 启动逻辑放在 events/server.py lifespan**：每个 MCP server 自包含自己的基础设施需求
4. **错误从 stderr 捕获**：mcp-manager.ts 不预检测依赖；server.py 启动失败时错误走 OpenCode 的 stdio stderr 路径
5. **子线程内的 Docker 命令必须有 timeout**：每个 `sp.run` 显式设置 timeout（3-90s），避免子线程被挂起
6. **pyproject.toml 解析失败不降级**：打印 stderr 日志，让用户看到问题
7. **跨模块代码复制策略**：`_pull_image_with_progress` 在 detect_env.py 和 events/server.py 各维护一份（mcp-servers 不允许依赖 binary-analysis）；两处加注释标明同源，方便未来重构时同步

### §3.1 实施步骤拆分

#### 步骤 1：pyproject.toml 加 `[tool.opensecurity]` section

- 文件：`events/pyproject.toml` + `knowledge/pyproject.toml`
- 改动：
  - events: `import_names = ["mcp", "graphiti_core"]` + `requires_docker = "neo4j-events"`
  - knowledge: `import_names = ["mcp", "sentence_transformers", "sqlite_vec"]`（无 requires_docker）
- 预估行数：~10 行
- 验证点：
  - `python -c "import tomllib; tomllib.load(open('...', 'rb'))"` 解析通过
  - `[tool.opensecurity]` section 存在且字段正确
- 依赖：无

#### 步骤 2：detect_env.py 加 `_load_mcp_metadata` + `_check_mcp_deps_fast`

- 文件：`.opencode/binary-analysis/scripts/detect_env.py`
- 改动：
  - 新增 `_load_mcp_metadata()`（从 pyproject.toml 读）
  - 新增 `_check_docker_binary_and_daemon()`（检测不启动）
  - 新增 `_check_container_status(container_name)`（检测不启动）
  - 新增 `_check_mcp_deps_fast()`（替代 _detect_mcp_deps 在 check-preinstall 路径）
- 预估行数：~80 行
- 验证点：
  - `python -c "compile(...)"` 语法通过
  - `_load_mcp_metadata()` 返回的字典含 knowledge + events 两个 server
  - `_check_mcp_deps_fast()` 不调用 `_ensure_docker_running`（grep 验证）
- 依赖：步骤 1

#### 步骤 3：detect_env.py 改 `_check_preinstall` 调 `_check_mcp_deps_fast`

- 文件：`.opencode/binary-analysis/scripts/detect_env.py`
- 改动：
  - `_check_preinstall` 第 896 行：`_detect_mcp_deps()` → `_check_mcp_deps_fast()`
  - 调整后续逻辑适应新的返回字段（docker_status / container_status）
- 预估行数：~15 行（含字段适配）
- 验证点：
  - check-preinstall 实测 <5s 完成（之前 8s timeout 杀进程）
  - 不输出"正在启动 Docker Desktop"日志
  - 不启动 Docker daemon / 容器
- 依赖：步骤 2

#### 步骤 4：detect_env.py install 路径保留启动逻辑

- 文件：`.opencode/binary-analysis/scripts/detect_env.py`
- 改动：
  - `_run_install` 内的 `_detect_mcp_deps(auto_create=True)` 改为调 `_ensure_mcp_infra()`（启动 Docker + 容器）
  - **不保留**旧 `_detect_mcp_deps` 函数（删除避免混淆，启动路径统一走 `_ensure_mcp_infra`）
- 预估行数：~10 行
- 验证点：
  - install 路径仍能启动 Docker + 容器
  - check-preinstall 路径不调启动函数（grep `_ensure_docker_running` 不在 `_check_preinstall` 调用链上）
  - grep `_detect_mcp_deps` 无残留（函数已删除）
- 依赖：步骤 2+3

#### 步骤 5：events/server.py 加 Docker 启动 + 改 lifespan

- 文件：`.opencode/mcp-servers/events/server.py`
- 改动：
  - 顶部 import 新增：`import shutil` / `import platform` / `import subprocess as sp`
  - 新增 `_ensure_docker_daemon_blocking(timeout=90)`
  - 新增 `_ensure_neo4j_container_blocking()`
  - 新增 `_pull_image_with_progress(image)`（从 detect_env.py 复制实现，避免 mcp-servers → binary-analysis 跨模块依赖；两处独立维护，加注释说明同源）
  - 改 `_preload_models_blocking()`：先调 `_ensure_docker_daemon_blocking` + `_ensure_neo4j_container_blocking`，再加载模型
- 预估行数：~110 行
- 验证点：
  - 语法通过
  - `_preload_models_blocking` 函数体含三步：Docker daemon → 容器 → 模型加载
  - grep `_ensure_docker_daemon_blocking` 在 `_preload_models_blocking` 内
  - grep `import shutil` / `import platform` / `import subprocess` 在文件顶部
- 依赖：步骤 1-4

#### 步骤 6：mcp-manager.ts 删除 requiredPackages + checkPackages

- 文件：`.opencode/plugins/lib/mcp-manager.ts`
- 改动：
  - MCP_SERVERS 数组删除 `requiredPackages` 字段（2 处）
  - `registerOne` 删除 checkPackages 调用
  - 删除 `checkPackages` 方法
  - 错误处理改为：catch + e.stderr 输出
- 预估行数：-25 行
- 验证点：
  - `node --check` 通过
  - grep `requiredPackages` 无残留
  - grep `checkPackages` 无残留
- 依赖：无（独立改动）

#### 步骤 7：单元测试 — Docker 启动路径

- 文件：新建 `test/mcp_events/test_docker_lifecycle.py`
- 改动：
  - 测 `_ensure_docker_daemon_blocking`：Docker 已运行时立即返回
  - 测 `_ensure_neo4j_container_blocking`：容器已运行时立即返回
  - 测 lifespan：Docker + 容器 + 模型完整加载序列
  - 测 _ensure_ready 等待 Docker + 容器 + 模型全部就绪
- 预估行数：~120 行
- 验证点：
  - lifespan 子线程内 Docker + 容器 + 模型顺序执行
  - 任意步骤失败时 _init_error 记录 + _ready.set()
  - 工具调用 _ensure_ready 等待全部就绪
- 依赖：步骤 5

#### 步骤 8：端到端测试 — kill Docker 后启动 OpenCode 自动恢复

- 文件：无（执行验证）
- 改动：手动 kill Docker + 容器 → 启动 OpenCode → 验证 events MCP 自动恢复
- 验证方式：
  ```bash
  # 1. 停止容器 + 退出 Docker
  docker stop neo4j-events
  osascript -e 'quit app "Docker"'
  sleep 5
  
  # 2. 启动 opencode serve
  OPENCODE_SERVER_PASSWORD=test123 opencode serve --port 4099 &
  sleep 60  # 等 lifespan 启动 Docker + 容器 + 模型
  
  # 3. 验证 MCP 注册 + 工具可调
  curl -u opencode:test123 http://localhost:4099/mcp
  # 期望：events: connected
  
  # 4. 调用工具
  curl -u opencode:test123 -X POST http://localhost:4099/session/.../message \
    -d '{"parts":[{"type":"text","text":"调用 mcp__events__recent_context_search..."}]}'
  ```
- 验证点：
  - Docker Desktop 被自动启动
  - neo4j-events 容器被自动启动
  - events MCP 注册成功（connected）
  - 工具调用返回结果
- 依赖：步骤 5+7

#### 步骤 9：端到端测试 — check-preinstall 不再 ETIMEDOUT

- 文件：无（执行验证）
- 改动：通过 opencode serve + 发消息触发 check-preinstall，测量耗时
- 验证方式：
  ```bash
  # 启动 opencode serve，发送测试消息触发 check-preinstall
  # 检查 plugin_debug.log 内 detect_env 输出
  grep "正在启动 Docker" /Users/aserlili/bw-security-analysis/logs/plugin_debug.log
  # 期望：无输出（check-preinstall 不再启动 Docker）
  ```
- 验证点：
  - check-preinstall <5s 完成（plugin timeout 8s 内）
  - 日志无"正在启动 Docker Desktop"
- 依赖：步骤 3

---

## §4 验收标准

### 功能验收

| # | 验收项 | 验证方法 |
|---|--------|---------|
| F1 | pyproject.toml `[tool.opensecurity]` section 存在 | tomllib 解析通过 |
| F2 | detect_env check-preinstall 不启动 Docker | grep 日志无"正在启动 Docker"；实测 <5s |
| F3 | detect_env check-preinstall 不启动容器 | grep 日志无"docker start"/"docker run" |
| F4 | events/server.py lifespan 启动 Docker daemon | Docker 停止时启动 OpenCode，Docker 被自动启动 |
| F5 | events/server.py lifespan 启动 neo4j-events 容器 | 容器停止时启动 OpenCode，容器被自动启动 |
| F6 | mcp-manager.ts 无 requiredPackages | grep 无残留 |
| F7 | mcp-manager.ts 无 checkPackages 方法 | grep 无残留 |
| F8 | events MCP 工具调用在 Docker + 容器 + 模型就绪后立即可用 | opencode serve + curl 调用工具 |

### 回归验收

| # | 验收项 |
|---|--------|
| R1 | knowledge MCP 不受影响（无 Docker 依赖） |
| R2 | detect_env install 路径仍能启动 Docker + 容器 |
| R3 | check-preinstall 仍能正确检测依赖缺失（包 + Docker + 容器） |
| R4 | events MCP 8 个工具功能正常（之前 Layer 5 烟雾测试） |
| R5 | plugin fire-and-forget 模式不变 |
| R6 | chat.message hook 检测流程不变 |

### 架构验收

| # | 验收项 |
|---|--------|
| A1 | pyproject.toml 是 MCP server 元数据单一事实源 |
| A2 | 检测与启动职责分离（check-preinstall 无副作用） |
| A3 | Docker 启动逻辑在 events/server.py lifespan 内（自包含） |
| A4 | mcp-manager.ts 不重复检测依赖（依赖错误从 server stderr 捕获） |
| A5 | 子线程内所有 Docker 命令有显式 timeout |
| A6 | pyproject.toml 解析失败时打印 stderr 日志（不降级） |

---

## §5 与现有需求文档的关系

| 文档 | 关系 |
|------|------|
| `2026-07-19-events-mcp-lazy-loading.md` | **直接前置**——events MCP lifespan lazy 加载已完成，本需求把 Docker 启动也纳入 lifespan（之前 lifespan 只加载模型） |
| `2026-07-19-knowledge-mcp-lazy-loading.md` | 独立——knowledge MCP 不依赖 Docker，本需求仅给 knowledge/pyproject.toml 加 `[tool.opensecurity]` 元数据 |
| `2026-07-19-knowledge-mcp-align-pentagi.md` | 独立——knowledge MCP 功能改造已完成 |
| `2026-07-18-events-mcp-model-replacement.md` | 独立——events MCP 的 LLM/embedder 配置已完成 |
