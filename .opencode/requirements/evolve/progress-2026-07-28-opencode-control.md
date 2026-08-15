# opencode-control 进度

## 步骤 1. 控制台后端骨架 + embed 迁移 ✓

**完成时间**：2026-07-28

**改动要点**：
- 新建 `.opencode/control/backend/` 目录结构
- `config.py`：常量收口（端口、模型名、超时、必要配置清单、exit code 约定）
- `services/model_loader.py`：BGE-M3 + Reranker 加载（线程安全单例）+ 后台线程预加载（B 方案）
- `routes/embed.py`：/embed、/rerank 路由（兼容现有 embed_client.py 调用约定）
- `routes/health.py`：/health 路由（模型加载中 503，就绪 200）
- `server.py`：FastAPI 主入口 + B 方案启动 + 前端 dev/release 模式判断
- `requirements.txt`：fastapi、portalocker、psutil

**抽象点收口**：
- 所有常量在 `config.py`，其他模块只导入
- 模型加载逻辑只在 `model_loader.py`
- embed/health 路由分离到独立文件

**验证点**：
- ✓ 语法检查全部通过
- ✓ fastapi + portalocker 依赖安装成功
- ✓ /health 返回 200（模型已在 HF cache 中加载快）
- ✓ /embed 返回 1x1024 维向量
- ✓ / 路由返回 JSON 提示 dist/ 不存在（开发态判断工作）

**未做**：
- 端口管理（步骤 2 加 port_manager）
- 单实例检测（步骤 3 加 ref_counter + flock）
- 配置管理（步骤 4 加 config_store + /api/config）

---

## 步骤 2. 跨平台文件锁 + 端口管理 ✓

**完成时间**：2026-07-28

**改动要点**：
- `services/process_lock.py`：跨平台文件锁（portalocker）、PID 存活检测（含启动时间戳防复用）、原子写
- `services/port_manager.py`：端口候选 + bind、端口文件读写、控制台运行检测

**抽象点收口**：
- 所有 portalocker 调用只在本模块（grep 唯一性）
- 所有 socket.bind 只在 port_manager（grep 唯一性）
- is_process_alive 是公共函数，被 port_manager 和后续 ref_counter 复用

**验证点（实测）**：
- ✓ 端口分配：bind 9777 成功（9776 被 embed_server 占，正确 fallback）
- ✓ 端口文件读写正确（port + pid + start_time 三行）
- ✓ is_control_running 三重校验工作
- ✓ SIGKILL 后 flock 自动释放（内核行为）
- ✓ PID 复用防护：start_time=0 时判定为 false（防 PID 复用）

**修复的 bug**：
- atomic_write 加 mkdir parents 兜底
- macOS 中文 locale 导致 ps lstart 解析失败 → 强制 LC_ALL=C

**未做**：
- 单实例检测（步骤 3 加 ref_counter + 在 server.py 加 exit code 2 复用）
- 引用计数周期清洗（步骤 3）

---

## 步骤 3. 引用计数 + 单实例检测 ✓

**完成时间**：2026-07-28

**改动要点**：
- `services/ref_counter.py`：users 文件读写 + 周期清洗后台任务 + 自杀检测
- `server.py`：加单实例检测（拿锁 → 端口文件校验 → exit 2 复用）+ 引用计数后台清洗 + uvicorn 用预绑定 socket fd

**抽象点收口**：
- users 文件读写函数（read_users/write_users/cleanup_dead_users/is_users_empty）都在本模块
- 单实例检测的"已有实例"判断用 port_manager.is_control_running()，不重复实现

**验证点（实测）**：
- ✓ 第一次启动：bind 端口成功 + 写端口文件（PID + 端口 + 启动时间戳）
- ✓ 第二次启动：exit code = 2（复用），不重复 spawn
- ✓ /embed 在已有实例上正常工作
- ✓ users 清洗：写入 2 条（含 1 个死 PID）→ 清洗后剩 1 条 → 文件实际更新
- ✓ users 全死后周期清洗触发自杀：exit code = 0，端口文件清理
- ✓ SIGTERM kill 后端口文件被清理

**未做**：
- 配置管理（步骤 4 加 config_store + /api/config）
- 工具/Docker 检测（步骤 5、5.1）
- 全量扫描协调（步骤 6）

---

## 步骤 4. 配置管理 ✓

**完成时间**：2026-07-28

**改动要点**：
- `services/config_store.py`：.ai_env 唯一读写方（read_all / read / write / write_one / delete / required_status）+ validator 函数
- `routes/config_route.py`：/api/config/* CRUD 路由
- `config.py`：ConfigField 加 validator 字段 + _init_validators 延迟绑定（避免循环 import）
- `server.py`：注册 config_route 路由

**抽象点收口**：
- 所有 .ai_env 读写只在 config_store（grep 唯一性，例外：server.py 的 is_dev_mode）
- validator 函数（validate_ida_pro_home / validate_api_key）在 config_store，与 ConfigField 配套
- _init_validators 解决 config ↔ config_store 循环 import：config 定义 ConfigField 不带 validator，服务启动后由 server.py 调一次 _init_validators 绑定

**验证点（实测）**：
- ✓ GET /api/config 返回 4 项配置
- ✓ GET /api/config/required-status 返回必要配置 banner 数据
- ✓ GET /api/config/{key} 单个读取
- ✓ PUT /api/config/{key} 单个更新
- ✓ PUT /api/config 批量更新
- ✓ DELETE /api/config/{key} 删除
- ✓ .ai_env 注释完美保留（写入和删除测试 key 后，原有注释行不变）
- ✓ validator 校验 IDA_PRO_HOME 路径有效

**未做**：
- 工具检测（步骤 5 加 tools_detector）
- Docker 管理（步骤 5.1 加 docker_manager）
- 全量扫描协调（步骤 6）

---

## 步骤 5+5.1+6 综合：检测/管理/扫描层完成 ✓

**完成时间**：2026-07-28

**改动要点**：
- `services/tools_detector.py`：迁移 EXTERNAL_TOOLS，收口所有外部工具检测（含 IDA_PRO_HOME 通过 config_store 读）
- `services/docker_manager.py`：迁移 Docker 检测和操作，KNOWN_CONTAINERS/IMAGES 常量化便于扩展
- `services/scanner.py`：扫描协调器单例 + 30s 缓存 + 并发扫描（ThreadPoolExecutor）
- `routes/deps.py`、`routes/docker.py`、`routes/scan.py`、`routes/install.py`、`routes/hardware.py`：5 个新路由
- `server.py`：注册所有新路由

**抽象点收口**：
- 工具检测唯一入口：tools_detector.scan_agent / scan_all
- Docker 操作唯一入口：docker_manager 模块的所有函数
- 扫描协调唯一入口：scanner.get_scanner().scan_all()
- pip 安装白名单：PIPPABLE_PACKAGES（防任意命令执行）
- KNOWN_CONTAINERS / KNOWN_IMAGES 常量化（扩展只改两处）

**验证点（实测）**：
- ✓ /api/deps/mobile-analysis 返回 6 个工具状态（含版本号）
- ✓ /api/deps 返回所有 agent 工具状态
- ✓ /api/docker/status 返回 daemon + 容器 + 镜像状态
- ✓ /api/docker/containers 列出实际容器（neo4j-events Up 6 days）
- ✓ /api/docker/images 列出实际镜像（neo4j:5 988MB）
- ✓ /api/hardware 返回完整硬件信息（CPU 14核 + 内存 48GB + Apple M4 Pro + Metal 4）
- ✓ GPU 能力推断：mlx + mps + metal
- ✓ /api/scan 返回全量扫描结果（agents + global.docker + configs + models）
- ✓ 缓存命中（0.02s）vs 强制刷新（0.37s）—— 缓存有效

**后端总计**（步骤 1-6）：
- 文件：18 个 Python 文件
- 代码：~1500 行（不含注释）
- 路由：8 个（embed、health、config、deps、docker、scan、install、hardware）
- 收口点：8 个（config_store、process_lock、port_manager、ref_counter、scanner、tools_detector、docker_manager、model_loader）

**未做**：
- detect_env.py 精简（步骤 7）
- embed_client.py 端口收口（步骤 8）
- Plugin 改造（步骤 9-12）
- 前端（步骤 13-17）

---

## 步骤 7-12 综合：detect_env 精简 + embed_client 收口 + Plugin 改造 ✓

**完成时间**：2026-07-28

**改动要点**：
- `detect_env.py`：删除 EXTERNAL_TOOLS、Docker 检测、embed_server 检测（1368 → 791 行，删 577 行）
- `mcp-servers/embed_client.py`：删端口文件读取，只读环境变量 `OPENCODE_CONTROL_PORT`
- `plugins/lib/ref-counter.ts`：users 文件读写（与控制台共享格式协议）
- `plugins/lib/process-utils.ts`：PID 存活检测 + 启动时间获取（跨平台，LC_ALL=C 修复中文 locale）
- `plugins/lib/control-manager.ts`：spawn 控制台 + 端口发现 + exit handler 减引用
- `plugins/lib/control-config.ts`：HTTP /api/config + 内存缓存
- `plugins/lib/mcp-manager.ts`：注册 MCP server 时 env 注入 OPENCODE_CONTROL_PORT
- `plugins/lib/venv.ts`：删除 readAiEnv / getIdatPath（配置读取收口到 control-config）
- `plugins/lib/persistence.ts`：readAiEnv → getAllConfig（取 RESUME_ANALYSIS_ENABLED）
- `plugins/lib/constants.ts`：加 CONTROL_STARTUP_SERVICE / CONTROL_PORT_FILE / ENV_CONTROL_PORT 等
- `plugins/security-analysis.ts`：删 startEmbedServer / pollEmbedServerHealth（253 行）→ 替换为 startControlService / control-manager 调用；shell.env hook 改用 getCachedConfig / getAllConfig；chat.message 的 waitFor 改用 CONTROL_STARTUP_SERVICE

**抽象点收口（grep 验证）**：
- ✓ EMBED_SERVER_PORT / embed_server_port / startEmbedServer / pollEmbedServerHealth：全部删除
- ✓ readAiEnv / getIdatPath：只剩 venv.ts 的迁移注释
- ✓ 控制台端口读取唯一入口：control-manager.readControlPortFile
- ✓ 配置读取唯一入口：control-config.getAllConfig / getConfig
- ✓ users 文件操作唯一入口：ref-counter.ts

**验证点（实测）**：
- ✓ detect_env.py check-preinstall binary-analysis：只返回 compiler + packages（第二层）
- ✓ embed_client.py：OPENCODE_CONTROL_PORT 环境变量优先，无环境变量时兜底 9776
- ✓ ref-counter.ts：addSelfToUsers / removeSelfFromUsers / cleanupDeadUsers 全部工作
- ✓ process-utils.ts：PID 复用防护工作（startTime=0 视为未提供，宽容处理）
- ✓ control-manager.ts：spawn 控制台 + 端口发现 + users 文件维护
- ✓ control-config.ts：HTTP 拉配置 + 内存缓存
- ✓ 端到端：bun 脚本启动控制台 → 拉配置 → /embed 返回 1024 维向量

**已完成的整体进度**：
- ✓ 控制台后端（步骤 1-6）：18 个文件，~1500 行
- ✓ detect_env.py 精简（步骤 7）：-577 行
- ✓ embed_client.py 收口（步骤 8）
- ✓ Plugin 引用计数（步骤 9）
- ✓ Plugin 控制台启动（步骤 10）
- ✓ Plugin 配置获取（步骤 11）
- ✓ Plugin mcp-manager 端口注入（步骤 12）

**未做（前端，工作量大）**：
- 步骤 13：前端骨架（React + Vite + 路由）
- 步骤 14：状态总览页 + 必要配置 banner
- 步骤 15：依赖管理页
- 步骤 16：Docker 管理页
- 步骤 17：构建脚本 + .ai_env 开关

---

## 步骤 13-17 综合：前端全部完成 ✓

**完成时间**：2026-07-29

**改动要点**：
- `control/frontend/package.json` + `vite.config.ts` + `tsconfig.json` + `index.html`：前端骨架
- `src/types/index.ts`：TypeScript 类型定义收口（与后端 dict 结构对齐）
- `src/api/client.ts`：axios API 客户端收口（含 SSE 镜像拉取进度）
- `src/hooks/index.ts`：自定义 hooks 收口（useHardware / useRequiredStatus / useScan / useAllConfig）
- `src/main.tsx`：主入口 + 路由 + 全局布局
- `src/styles.css`：全局样式
- `src/components/RequiredConfigBanner.tsx`：必要配置缺失 banner
- `src/pages/StatusPage.tsx`：状态总览（硬件 + 全局资源）
- `src/pages/DepsPage.tsx`：依赖管理（loading + 缺失项汇总 + agent 折叠 + Python 包安装）
- `src/pages/DockerPage.tsx`：Docker 管理（容器启停 + 镜像拉取 SSE 进度）
- `src/pages/ConfigPage.tsx`：配置编辑（必要配置 + 可选配置 + 其他配置）
- `src/pages/HardwarePage.tsx`：硬件详情
- `control/build.sh`：前端构建脚本（bun/npm 自动检测）
- `.ai_env` 增加 `CONTROL_FRONTEND_DEV=0` 开关
- `.gitignore` 不忽略 dist/

**抽象点收口**：
- API 调用唯一入口：`src/api/client.ts` 的 `api` 对象
- TypeScript 类型唯一来源：`src/types/index.ts`
- 数据获取唯一通过 hooks（组件不直接调 api）
- 后端 is_dev_mode 判断逻辑：在 config.py，根据 CONTROL_FRONTEND_DEV 决定挂载 dist/ 还是返回 dev 提示

**验证点（实测）**：
- ✓ `bun install` + `bun run build` 成功生成 dist/（93 个模块）
- ✓ 控制台后端挂载 dist/ 后，`GET /` 返回 HTML、`GET /assets/*.js` 返回 JS 资源
- ✓ CONTROL_FRONTEND_DEV=1 时 `/` 返回 JSON dev 提示
- ✓ 前端集成测试 10 个全部通过（HTML / 资源 / API 不互相干扰）

---

## Phase 6 最终审计 + 全量测试 ✓

**完成时间**：2026-07-29

**第 1 轮审计 + 修复**：
- 发现 3 个高级问题：
  1. mcp-servers/embed_server.py 未删除 → 已删除
  2. mcp-servers/events/server.py 仍有 embed_server_port / EMBED_SERVER_PORT → 改为 OPENCODE_CONTROL_PORT
  3. mcp-servers/events/graphiti_config.py 读 .ai_env → 注释明确为兜底
- 发现 1 个测试 bug：is_process_alive startTime=0 应宽容处理 → 修复 process_lock.py + process-utils.ts

**架构验收（A1-A7）全部通过**：
- A1 配置读取收口：detect_env.py（install.sh 流程）+ graphiti_config.py（兜底）+ tools_detector.py（提示文字）+ config_store.py（控制台） + server.py（is_dev_mode）—— 都有合理例外
- A2 端口 bind 收口：只在 port_manager.py（port.py 是注释提到）
- A3 文件锁收口：只在 process_lock.py（test_control.py 是测试用）
- A4 EXTERNAL_TOOLS 已从 detect_env.py 删除
- A5 mcp-servers/embed_server.py 已删除
- A6 embed_server_port 残留全部清零
- A7 EMBED_SERVER_PORT 残留全部清零

**测试套件**：
- 后端测试：35 个全部通过（`tests/test_control.py`）
- Plugin 测试：12 个全部通过（`tests/test-control.ts`）
- 前端集成测试：10 个全部通过（`test_frontend.sh`）
- **总计 57 个测试全部通过**

**测试覆盖**：
- 模块单元测试：process_lock / port_manager / ref_counter / config_store / tools_detector / docker_manager / scanner
- 端到端测试：控制台启动 + /health + /embed + 单实例检测 + 全部 API 路由
- 边界条件：PID 复用防护、SIGKILL 后 flock 释放、原子写、白名单外拒绝
- 集成测试：Plugin spawn 控制台 + 配置获取 + users 引用计数 + 前端资源服务

---

## 全部完成总览

| 步骤 | 内容 | 行数 | 状态 |
|------|------|------|------|
| 1 | 控制台后端骨架 + embed 迁移 | ~180 | ✓ |
| 2 | 跨平台文件锁 + 端口管理 | ~150 | ✓ |
| 3 | 引用计数 + 单实例检测 | ~120 | ✓ |
| 4 | 配置管理（config_store + API） | ~180 | ✓ |
| 5 | 工具检测迁移 | ~200 | ✓ |
| 5.1 | Docker 管理迁移 | ~200 | ✓ |
| 6 | 全量扫描协调 | ~180 | ✓ |
| 7 | detect_env.py 精简 | -577 行 | ✓ |
| 8 | embed_client.py 端口收口 | ~30 | ✓ |
| 9 | Plugin ref-counter.ts | ~100 | ✓ |
| 10 | Plugin control-manager.ts | ~250 | ✓ |
| 11 | Plugin control-config.ts + 删 venv.ts | ~250 | ✓ |
| 12 | Plugin mcp-manager 端口注入 | ~120 | ✓ |
| 13 | 前端骨架 | ~200 | ✓ |
| 14 | 状态总览页 + banner | ~150 | ✓ |
| 15 | 依赖管理页 | ~200 | ✓ |
| 16 | Docker + 配置 + 硬件页 | ~300 | ✓ |
| 17 | 构建脚本 + .ai_env 开关 | ~50 | ✓ |

**新增/修改文件清单**：
- 新增 `.opencode/control/backend/`：18 个 Python 文件
- 新增 `.opencode/control/frontend/`：14 个 TypeScript/CSS 文件
- 新增 `.opencode/control/{build.sh,test_frontend.sh}`：2 个脚本
- 新增 `.opencode/plugins/lib/{ref-counter,process-utils,control-manager,control-config}.ts`：4 个 TS 模块
- 新增 `.opencode/control/backend/tests/test_control.py` + `.opencode/plugins/tests/test-control.ts`：2 个测试套件
- 修改 `.opencode/mcp-servers/embed_client.py`：删端口文件读取
- 修改 `.opencode/mcp-servers/events/server.py` + `graphiti_config.py`：环境变量改名
- 修改 `.opencode/binary-analysis/scripts/detect_env.py`：精简 577 行
- 修改 `.opencode/plugins/{security-analysis.ts,lib/venv.ts,lib/persistence.ts,lib/mcp-manager.ts,lib/constants.ts}`：5 个 Plugin 文件
- 删除 `.opencode/mcp-servers/embed_server.py`：功能迁移到控制台

**总计**：~6500 行新代码 + ~1000 行删除，57 个测试全部通过。

