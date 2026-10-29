# 需求：依赖检测分层 + 本地 OCR 服务（glm-ocr）

> 状态：待复核
> 来源：2026-08-16 OCR 引擎横评后的架构决策（用户逐条拍板）

## §1 背景与目标

### 任务 A：依赖检测分层

**痛点**：
1. install.sh（detect_env install）装全部 25+ Python 包（含 angr 1GB+），但控制台启动只需 7 个小包——新设备 bootstrap 被重型包拖慢
2. chat.message 的环境检测走 detect_env check-preinstall 子进程（fail-fast 文字流），与控制台 /api/deps 的检测是两套重复逻辑（tools_detector.py:227 注释自认"双清单同步维护"是债务）
3. 缺依赖提示只有脚本命令，没有控制台链接

**目标**：
- install.sh 装全部必需依赖（装完即满足全部 agent 的 required 检查）
- chat.message 环境检测改调控制台 `/api/deps/{agent}`，缺失必需依赖 → 终止 + 控制台链接
- detect_env check-preinstall 子进程从 chat.message 链路退役

### 任务 B：本地图像识别（替代 zai 视觉 MCP）

**痛点**：zai MCP 又慢（实测 12~60s）又限流（429），已禁用。本地 glm-ocr（MLX 路径实测 3~4.3s/页、峰值内存 <2GB、中英/代码/表格满分）待服务化。

**目标**：
- 新 MCP server `ocr`（工具 `ocr_extract_text`），HTTP 调控制台 OCR 服务
- 控制台加载/释放 glm-ocr，引用计数 + 30s 空闲释放（热启动复用），并发安全
- 平台分支：macOS(Apple Silicon) → MLX 子进程；win/linux → Ollama HTTP
- 控制台模型页显示 glm-ocr（状态/下载/停止）
- 卸载 rapidocr + pyobjc（决策：只用 glm-ocr）

## §2 技术方案

### 2.1 依赖检测收口（单一清单 + 控制台唯一检测方）

```
.opencode/control/backend/services/
  ├── py_deps_detector.py（新增，Python 依赖唯一清单+检测）
  │     • 纔 stdlib（venv 建立前可被文件路径加载）
  │     • PYTHON_PACKAGES 唯一副本：含 bootstrap 标志（8 包，含 uvicorn）
  │       + 全集（含 pymupdf 新增）
  │     • 检测函数 scan(agent="all", python_exe=sys.executable)：
  │       import 调用与 CLI 调用（--agent --json）同一函数同一参数
  │     • install.sh 的 detect_env 经 importlib 文件路径加载此清单
  └── tools_detector.py（改造，外部工具唯一清单+检测）
        • 删除自身 PYTHON_PACKAGES 段（引用 py_deps_detector 保持兼容）
        • 编译器检测并入（本质是外部工具）

detect_env.py（迁至 control/backend/services/，纯安装器）
  • git mv 自 binary-analysis/scripts/（收口：安装器归属依赖体系所在目录）
  • install 子命令保留：bootstrap venv → 装 bootstrap 集清单包；清单从同目录 py_deps_detector 加载
  • check-preinstall 子命令及重复清单删除；OPENCODE_ROOT 推导改四级
  • 唯一调用方 = install.sh / install.ps1（无参数透传）
  • 整改记录：初版实现过 --full 全集模式（CI 设想），审计后按 YAGNI 删除——
    无真实 CI 消费者，控制台 /api/install 可装全集，双入口纯冗余

chat.message（plugin，只调控制台 API）
  ├─ venv 存在性（getPythonCmd，缺失 → install.sh 提示，保留）
  ├─ 控制台启动等待（不变）
  └─ GET /api/deps/{agent}
       后端聚合全分类：Python 包 + 外部工具 + 编译器 + Docker/镜像 + 模型资产
       按 agent 归属过滤（Docker/模型 → 9 领域 agent；evolve 不在其列）
       summary: {ready, required_missing, optional_missing, console_url}
       required 缺失 → 终止 + console_url；optional 缺失 → 不拦（决策）
       evolve/searcher/memorist 统一走此 API（特判分支删除，
       evolve 只查 agents=["all"] 必需项 = venv 基础包 + 编译器）

console_url（后端计算，塞进 deps 响应）
  发布态 = backend 端口（mount dist 同源）
  开发态 = 读 DATA_DIR/.vite-dev.port + TCP 探测 → 活则 vite 端口，
           死则回退 backend 端口
  vite.config.ts 插件：listening 时写实际端口（冲突自动换端口可感知）
```

**bootstrap 集确定**（从 server.py 实际 import 推导）：

| 包 | 用途 |
|---|---|
| fastapi + uvicorn | Web 框架 + 服务器 |
| psutil | 硬件检测/进程管理 |
| portalocker | 端口文件锁 |
| numpy | embed 返回值 |
| httpx | 控制台 HTTP 客户端/测试 |
| huggingface_hub | 模型缓存扫描与下载 |

### 2.2 前端链接解析（console_url）

- 发布态：`http://localhost:{backend_port}`（backend mount dist/，同源）
- 开发态（is_dev_mode）：读 `DATA_DIR/.vite-dev.port` + TCP 探测（100ms 超时）
  - 通 → `http://localhost:{vite_port}`（vite 端口冲突自动递增后也能感知）
  - 不通 → 回退 backend 端口
- vite.config.ts 加 write-dev-port 插件：`configureServer` → httpServer `listening` 事件时写实际端口到 `DATA_DIR/.vite-dev.port`

### 2.3 控制台 OCR 服务

```
mcp-servers/ocr/server.py（FastMCP stdio，轻进程不驻模型）
  │ lifespan: acquire(pid)     工具调用: extract → POST /api/ocr/extract
  │ 退出时: close(pid)         （复用 control_url.py 端口发现 + embed_client 模式）
  ▼
control/backend
  ├─ POST /api/ocr/acquire    引用+1（client_id = mcp_pid+start_time）
  ├─ POST /api/ocr/extract    识图（刷新 last_active）
  ├─ POST /api/ocr/close      引用-1
  ├─ GET  /api/ocr/status     状态（前端模型页）
  └─ services/ocr_service.py
```

**状态机（单把 asyncio.Lock 串行化全部状态变更）**：

```
idle → starting → ready → stopping → idle
starting 期间并发请求 await 同一个 ready 事件（单飞，不重复 spawn）
stopping 期间来新请求 → 等停止完成再重启
```

**引用计数与释放**：

```
clients: {client_id → last_active}
释放条件（后台线程每 5s 检查）：
  clients 空 AND 距最后 extract > 30s AND 非 idle
  → 释放（mac: kill MLX 子进程；win/linux: keep_alive=0 请求）
MCP 被 SIGKILL 忘了 close 的兜底：
  后台线程用 psutil 检测 client 死亡 → 清引用
  （复用 ref_counter.py 已验证的 pid+start_time 模式）
```

**平台分支**：

| | macOS (Apple Silicon) | Windows / Linux |
|---|---|---|
| 实现方式 | spawn `~/bw-security-analysis/mlx-env/bin/python -m mlx_vlm.server --port {随机}` | Ollama HTTP（127.0.0.1:11434） |
| 依赖检测 | mlx-env venv 存在 + HF 模型缓存 | `ollama --version` + /api/tags 有 glm-ocr |
| 调用 | OpenAI 兼容 /v1/chat/completions（图在前消息格式） | POST /api/generate（keep_alive="30s"） |
| 释放 | kill 子进程 | keep_alive=0 显式卸载 |
| 11434 不通 | — | 尝试 spawn `ollama serve` → 仍失败报错 |

**MCP 工具定义**：

```
名称: extract_text（server 名 ocr → 工具全名 ocr_extract_text）
参数: image_path: str（本地路径）
       prompt: str = ""（可选引导，如"注意保持表格结构"）
描述: 明确能力边界——提取图像中的文字（文档/截图/表格），
      不做图表语义分析/UI 对比/视频理解
```

### 2.4 模型资产管理

model_assets.MODELS 加条目：

```python
ModelAsset(
    id="glm-ocr",
    repo_id="mlx-community/GLM-OCR-4bit",   # win/linux 走 ollama，下载动作按平台分发
    type="ocr",
    display="GLM-OCR (0.9B)",
    purpose="本地图像文字识别（OCR MCP 后端）",
    min_free_gb=4.0,
    disk_gb=1.2,
)
```

- mac 下载动作：HF snapshot_download + 确保 mlx-env 存在（无则 `python -m venv + pip install mlx-vlm==0.6.13`）
- win/linux 下载动作：`ollama pull glm-ocr`
- 前端模型页：复用现有卡片模式 + 运行状态（/api/ocr/status）+ 停止按钮（强制释放）

## §3 实现规范

### 改动范围表

| # | 文件 | 改动类型 | 内容 |
|---|---|---|---|
| 1 | control/backend/services/py_deps_detector.py | 新增 | Python 依赖唯一清单（bootstrap 标志/uvicorn/pymupdf）+ scan() + CLI |
| 2 | control/backend/services/tools_detector.py | 修改 | 删重复清单段（引用 py_deps_detector）；编译器检测并入 |
| 3 | control/backend/services/detect_env.py | 修改 | 纯安装器（唯一调用方 install.sh，无参数）；清单从 py_deps_detector 加载 |
| 4 | control/backend/services/console_url.py | 新增 | console_url 解析（dev 态 vite 端口探测 + 回退） |
| 5 | control/backend/routes/deps.py | 修改 | 聚合五分类 + agent 归属过滤 + summary + console_url |
| 6 | control/frontend/vite.config.ts | 修改 | write-dev-port 插件 |
| 7 | plugins/lib/env-check.ts + security-analysis.ts | 修改 | chat.message 检测改走 /api/deps/{agent}，删 detect_env spawn 链 |
| 8 | control/backend/services/ocr_service.py | 新增 | 状态机 + 引用计数 + 平台分支（MLX/Ollama） |
| 9 | control/backend/routes/ocr.py | 新增 | acquire/extract/close/status 4 端点 |
| 10 | control/backend/server.py | 修改 | include_router(ocr) |
| 11 | control/backend/services/model_assets.py | 修改 | +glm-ocr 条目（平台化下载） |
| 12 | mcp-servers/ocr/server.py + pyproject.toml | 新增 | FastMCP stdio + extract_text + lifespan acquire/close |
| 13 | plugins/lib/mcp-manager.ts | 修改 | MCP_SERVERS +ocr |
| 14 | control/frontend/src/App.tsx（模型区） | 修改 | glm-ocr 卡片 |
| 15 | venv | 操作 | 卸载 rapidocr-onnxruntime/onnxruntime/pyobjc 全家 |

### 编码规则

- ocr_service 状态变更全部走单锁；对外 API 用 async（extract 推理走 to_thread 不阻塞 event loop）
- MCP server 遵循 lazy lifespan 模式（对齐 events/knowledge server）
- 所有新端点对齐现有错误处理风格（HTTPException + 明确 detail）
- plugin 改动充分打日志（规则 9）

### §3.1 实施步骤拆分

**阶段 A：依赖检测收口**

A1. py_deps_detector.py（唯一清单）
  - 文件: services/py_deps_detector.py（新）
  - 预估行数: ~160（清单含 bootstrap 标志/uvicorn/pymupdf + scan(agent, python_exe) + CLI）
  - 验证点: `python py_deps_detector.py --agent binary-analysis --json` 输出含 uvicorn/pymupdf 且本机"已装"；`--agent all` 全量；import 调用与 CLI 输出一致
  - 依赖: 无

A2. tools_detector.py 改造
  - 文件: services/tools_detector.py
  - 预估行数: ~80（删 PYTHON_PACKAGES 段改引用 py_deps_detector；编译器检测并入为工具条目）
  - 验证点: routes/install.py 白名单不变（pip_installable_packages 经引用仍工作）；routes/scan.py 或 deps 路由的 Python 页数据不缺行；python compile 语法检查
  - 依赖: A1

A3. detect_env.py 瘦身为纯安装器并迁至 services/
  - 文件: control/backend/services/detect_env.py（git mv）+ install.sh/ps1 路径
  - 预估行数: 净删 ~250（check-preinstall/重复清单/编译器检测/安装指南函数删除；install 循环改为加载 py_deps_detector 清单；加 --full 参数）
  - 验证点: `python detect_env.py install --dry-run`（新增 dry-run 输出待装清单不执行）默认=8 bootstrap 包，--full=全集；grep 全仓无 check-preinstall 残留调用方（plugin 在 A6 改）
  - 依赖: A1

A4. console_url 服务 + vite 端口文件
  - 文件: services/console_url.py（新）、frontend/vite.config.ts
  - 预估行数: ~70 + ~25
  - 验证点: 发布态 → backend 端口；开发态 vite 起（故意占 5173 使跳 5174）→ 5174；vite 停 → 回退
  - 依赖: 无

A5. deps 路由聚合 summary
  - 文件: routes/deps.py
  - 预估行数: ~90（聚合五分类 + agent 归属过滤 + summary 组装 + console_url 注入）
  - 验证点: `curl /api/deps/binary-analysis` 含 summary.ready=true、console_url 正确；`/api/deps/security-analysis-evolve` 只含 all 级必需项（无 Docker/模型）；临时屏蔽一个必需包 → required_missing 出现该包
  - 依赖: A1, A2, A4

A6. plugin 环境检测改 API
  - 文件: plugins/lib/env-check.ts、security-analysis.ts
  - 预估行数: ~150（新 checkViaControl() 替换 runDetectEnv 链；chat.message 分支统一；evolve/searcher/memorist 特判删除；错误消息含 console_url；控制台不可达 → 终止+明确报错）
  - 验证点: 三分支——①正常 agent 放行（日志见 deps 检查通过）②临时屏蔽必需包 → 终止+消息含控制台链接 ③控制台停 → 终止+报错；node --check 通过
  - 依赖: A5

**阶段 B：OCR 服务**

B1. ocr_service 核心（mac MLX 分支）
  - 文件: services/ocr_service.py（新）
  - 预估行数: ~200
  - 验证点: 单元级——acquire×2 → extract 成功出文字 → close×2 → 30s 后（测试时缩短为 2s）子进程退出；并发 acquire 竞态测试（同时 5 个 acquire 只 spawn 一次）
  - 依赖: 无

B2. ocr 路由 + 挂载
  - 文件: routes/ocr.py（新）、server.py
  - 预估行数: ~80
  - 验证点: curl 四端点全通；extract 传测试图返回正确文字
  - 依赖: B1

B3. Ollama 分支（win/linux 路径，mac 上写好 + 逻辑单测）
  - 文件: services/ocr_service.py
  - 预估行数: ~120
  - 验证点: 分支选择函数单测（platform mock）；Ollama HTTP 客户端参数单测（keep_alive 值、tags 检测逻辑）；mac 上不误入 ollama 分支
  - 依赖: B1

B4. model_assets + 前端模型页
  - 文件: model_assets.py、App.tsx
  - 预估行数: ~40 + ~60
  - 验证点: /api/models 含 glm-ocr（本机已缓存显示"已缓存"）；前端模型页渲染 glm-ocr 卡片（Playwright 截图验证）；OCR 服务运行中显示运行状态
  - 依赖: B2

B5. MCP server ocr
  - 文件: mcp-servers/ocr/server.py（新）、mcp-servers/ocr/pyproject.toml（新，含 [tool.opensecurity].import_names 依赖声明，mcp-manager 预检用）
  - 预估行数: ~150 + ~15
  - 验证点: stdio 手动握手（echo tools/list）返回 extract_text；调用 extract 传图返回文字；退出后控制台引用归零
  - 依赖: B2

B6. MCP 注册 + 端到端
  - 文件: plugins/lib/mcp-manager.ts
  - 预估行数: ~8
  - 验证点: 重启 opencode 后 agent 工具列表出现 ocr_extract_text；真实会话识图成功；会话结束后 30s 模型释放（日志验证）
  - 依赖: B5

B7. 清理：卸载 rapidocr/pyobjc
  - 文件: venv 操作
  - 预估行数: 0（pip uninstall）
  - 验证点: pip list 无残留；全量测试回归（pytest 63 + 后端 53+5 + TS 18）仍绿
  - 依赖: 无（放最后，防中途还要用）

B8. 回归 + 文档同步
  - 文件: 全部测试 + agent prompt 索引（OCR MCP 使用说明）
  - 预估行数: ~20
  - 验证点: 139 全绿；领域 agent prompt（或 agents-rules）有 OCR MCP 能力说明
  - 依赖: A5, B6

## §4 验收标准

### 功能验收
1. 新 venv + `install.sh`：秒级完成（仅 8 bootstrap 包），控制台可启动，/api/deps 可检测
2. 缺必需依赖的 agent 发消息：终止 + 消息含可用控制台链接（dev/release 态均正确）；optional 缺失不拦
3. 全仓只有 install.sh/ps1 调 detect_env.py；无任何代码调 check-preinstall
4. Python 依赖清单全仓唯一（py_deps_detector.py）；控制台 /api/install 白名单行为不变
5. ocr_extract_text：文档图/截图输入，中文+十六进制+表格逐字正确（对齐横评基准）
6. 引用计数：多会话并发使用单实例；全部结束 30s 后内存释放（psutil 验证子进程退出）
7. MCP 异常退出（kill -9）：后台线程清引用，不泄漏
8. 模型页：glm-ocr 显示缓存/运行状态，可停止

### 回归验收
- pytest 63 + 后端单元 + 集成 5 + TS 18 全绿（引用清单的测试同步更新）
- 现有 knowledge/events MCP 注册与调用不受影响
- 控制台 /api/install 既有行为不变

### 架构验收
- detect_env 与 tools_detector 不再有"检测逻辑"重复（detect_env 仅剩安装器职责）
- OCR 模型只经 ocr_service 加载/释放（其他模块禁止直连）
- 依赖方向无违反（ocr_service 不 import routes；MCP 不 import 控制台内部模块，仅 HTTP）

## §5 与现有需求文档的关系

- 前序：progress-2026-08-15-frontend-redesign.md（前端迭代，已完成的 UI 基础上模型页增量改动）
- 本文档不修改 knowledge 双轨分离设计（evolve 的 events/knowledge deny 不变）
- zai MCP 禁用（.opencode/opencode.json 的 enabled:false）为本方案的前置已落地项
