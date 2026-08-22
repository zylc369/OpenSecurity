# 需求：控制台 IPC 化——消除端口发现文件

## §1 背景与目标

8/20 竞态事故（`.opencode-control.port` 被临终控制台删除 → 插件 `readControlPortFile()!` 崩溃 → 僵尸 failed 拦截全天消息）暴露了端口文件机制的结构性缺陷。用户决策：**程序间通信全部走 IPC（无端口），浏览器保留固定 9776（物理限制），三个状态文件消亡**。

## §2 技术方案

- **地址常量**（编译期写死，非运行期分配）：
  - macOS/Linux：`$DATA_DIR/opensecurity-control.sock`（Unix Domain Socket）
  - Windows：`\\.\pipe\opensecurity-control-482964`（命名管道，6 位随机后缀防撞名）
  - 浏览器/vite 代理：`127.0.0.1:9776` 固定 TCP（唯一保留端口）
- **控制端**：uvicorn 单实例监听 TCP 9776（零改动）+ IPC 监听线程（accept → 字节泵 → 127.0.0.1:9776），平台差异收口在 `services/ipc_listener.py`
- **互斥**：IPC bind 内核排他（Unix EADDRINUSE / Windows FILE_FLAG_FIRST_PIPE_INSTANCE），取代 `.lock` 文件
- **单例检测**：IPC connect 一次（取代 端口文件+PID+startTime+health 四步）
- **MCP**：Unix 走 httpx `HTTPTransport(uds=)`（原生）；Windows 客户端侧本地代理线程（127.0.0.1 随机端口→管道，进程内实现细节）
- **TS 插件**：Unix 走 Bun `fetch unix:`（实测 ✓）；Windows 走 `node:http` `socketPath`（CI 验证，Bun 不支持时回退 TCP 并告警）
- **vite dev 端口上报**：改经 IPC `POST /api/dev-url`（控制台内存记录），删 `.vite-dev.port`
- **删除**：`.opencode-control.port`、`.opencode-control.lock`、`.vite-dev.port` 及全部读写代码；`acquire_startup_lock`、`bind_port_with_fallback`、`probe_live_control`、端口候选递增

## §3.1 实施步骤

1. `config.py`：IPC/TCP 常量，删 PORT_FILE/LOCK_FILE/端口候选
2. `services/ipc_listener.py`（新 ~170 行）：双平台监听 + 泵
3. `port_manager.py` 重写（~90 行）：固定 bind + IPC probe
4. `server.py` main() 重写：IPC 探测→bind→监听线程→uvicorn
5. `services/dev_registry.py`（新）+ `console_url.py`/`vite_dev.py` 改 + `/api/dev-url` 路由
6. `mcp-servers/control_url.py` 重写 + 3 薄壳 lifespan
7. TS：`constants.ts` + `control-http.ts`（新 controlFetch）+ control-manager/control-config/env-check/security-analysis/mcp-manager
8. `vite.config.ts`：IPC 上报替代文件写入
9. requirements/detect_py_deps：pywin32（win32 标记）
10. 测试适配（test-control.ts / test_control.py / test_integration.py）
11. Windows CI workflow（管道往返验证）
12. 端到端：重启控制台实测（新控制台双监听，旧插件走 TCP 兼容窗口）

## §4 验收

- F1/F2/F3：三个文件不再被创建，读写代码零残留（grep 验证）
- F5：8/20 竞态链机制性消失（connect 即检查即使用）
- F6：浏览器 `http://localhost:9776` 照常
- F7：MCP/插件/配置/事件库功能不回归（bun + python 测试全绿）
- F8：Windows 管道路径 CI 绿（GitHub Actions windows-latest）
- F9/F10/F11：IPC 固定地址、一次连接判活、内核级互斥自动复用

## §6 实施结果（2026-08-21 完成）

- 地址常量：sock = opensecurity-control.sock；pipe = \\.\pipe\opensecurity-control-482964
- 新增：services/ipc_listener.py（双平台监听+泵）、services/dev_registry.py、plugins/lib/control-http.ts（controlFetch）、.github/workflows/windows-ipc.yml、tests/test_windows_ipc.py、plugins/tests/win-pipe-probe.ts
- 重写：port_manager（仅固定 TCP bind）、server.py main（IPC 探测→bind→监听→uvicorn）、control_url.py（IPC 地址+客户端工厂）、control-manager.ts（单飞+IPC 就绪等待）、console_url/vite_dev（dev_registry）
- 删除：.opencode-control.port/.lock/.vite-dev.port 全部读写；acquire_startup_lock；bind_port_with_fallback；probe_live_control；端口候选递增；waitForPortFile
- 测试：TS 19/19；Python 单测 56/56；集成 5/5；沙箱手动端到端（uds 200 + TCP 200）✓
- 实施中修复的真 bug：泵线程参数反写（请求弹回）、bind 前 mkdir、探测 catch 范围、复用分支 pid 语义
- 待办：Windows CI 首跑结果（推送后）；生产切换需重启 opencode

## §7 用户复核后的第二轮重构（2026-08-21）

用户指出的五项全部落实：
1. **IPC bind 并发等待语义**：败者不再立即退出——IpcListener.start 内轮询（IPC_BIND_WAIT_SEC=5s 窗口）等胜者就绪后复用退出；文件消失则清残留重 bind；窗口耗尽才 RuntimeError（真异常）
2. **TCP 顺延**：port_manager/dev_registry/vite_dev 三文件删除，合并为 services/frontend_port.py 的 FrontendPortRegistry 类（TCP bind+顺延+注册 / vite 端口注册+探测+拉起 / console_url 计算——"前端端口唯一事实源"）；/api/console-url 对外暴露真实端口；插件 getControlPort 与 vite proxy target 均动态获取
3. **IPC_READY_WAIT_SEC 删除**（定义后零使用；TS 侧 CONTROL_IPC_READY_WAIT_MS 才是生效常量）
4. **requirements.txt 删除**：零代码引用，依赖检测唯一入口 detect_py_deps.py（pywin32 已入 PYTHON_PACKAGES win32 平台标记）
5. **规则 9 返工**：IpcListener / ControlIpc / FrontendPortRegistry / ControlHttpClient（TS）全部类化 + 模块级单例 + 同名委托。锁的边界：lifecycle_lock 只保护 start/cleanup 状态转移；连接泵（连接局部 socket 对 + Event）与 probe 无共享态不持锁——不是一把大锁（并发连接不被串行化）

修复的真 bug：_wait_or_retry 返回值语义反转（等 到活实例应 False=复用退出，首版写反导致第二实例继续跑抢占顺延端口）
测试：TS 19/19、Python 56/56、集成 5/5；生产已切换（pid 39396，TCP 9776 + IPC uds 双通道，/api/console-url 实测 200）
