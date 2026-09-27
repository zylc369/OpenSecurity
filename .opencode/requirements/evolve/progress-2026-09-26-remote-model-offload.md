# Progress: 远程模型卸载（一期）— 已完成

> 需求文档: requirements/evolve/2026-09-26-remote-model-offload.md（19 步）
> 最终状态: 全部步骤 ✅ + review 修复轮 ✅; 回归 119/119; 端到端全链路（含转发锚点）✅

## 步骤进度（全部完成）

| # | 步骤 | 状态 | 要点 |
|---|------|------|------|
| 1-2 | model_lifecycle.py + 单测 | ✅ | ModelWorker(call/post 按 name 进程共享) + ManagedModel（非阻塞加载提交/单飞/排队卸载/reaper）; 13 测试 |
| 3 | OCR 迁移 | ✅ | _MlxWorker 删除; MlxEngine 纯实现; OcrService 生命周期→ManagedModel; 8 个旧测试适配（含"竞争窗口防御"升级为"窗口消灭"更强语义） |
| 4 | embedder/reranker 纳入 | ✅ | LockedEmbedder/Reranker 零改动（锁串行+壳常驻动态绑定）; unload 持 _infer_lock 与推理互斥; 守护断言 2→6 锁点 |
| 5 | config + logging | ✅ | ConfigField.hidden + REMOTE_TAB_CONFIGS(6 KEY) + 6 env 常量; setup_auxiliary_logger |
| 6-7 | remote_client + 单测 | ✅ | RemoteUnavailable 统一异常; embed/rerank/ocr/probe/node 转发; 8 测试 |
| 8 | 路由层 + fallback | ✅ | _route_encode/_route_predict + ocr 路由; 请求级 fallback+note; get_* 远程态跳过加载（修复 bug） |
| 9-10 | remote_link + 单测 | ✅ | OFF/REMOTE/DEGRADED 阈值状态机 + Timer 延迟卸载 + 独立日志; 9 测试 |
| 11-12 | api_guard + server 集成 + 单测 | ✅ | 中间件（本机全放/白名单+token/403）; effective_bind_host; 节点预加载/ENABLED 跳过预加载; 4 测试 |
| 13 | heartbeat resident + launchd | ✅ | resident 豁免; launchd install/uninstall/status（darwin） |
| 14-15 | routes/remote + 配置页隐藏 + 单测 | ✅ | ?node=remote 转发; node-config 三 KEY 白名单 + API_KEY 脱敏; meta.hidden + ConfigSection 过滤; 5 测试 |
| 16-18 | 前端 | ✅ | types/client + RemoteSection 三卡片（切换按钮互斥/降级红闪/节点管理）+ App 第三 Tab + 闪烁 keyframes; tsc + build 过 |
| 19 | 端到端 + 回归 | ✅ | 双进程真机联调全链路通过（见下）; 119/119 |

## 端到端验证结果（tests/test_e2e_remote.py，OPENSECURITY_E2E_REMOTE=1）

1. 节点 health 探测 + 三模型指纹 ✅
2. 鉴权: 无 token 401 / 非本机管理面 403 ✅
3. 主控切换远程（校验+置位）✅
4. embed 走远程（0.3s）→ 稳定期后本地 embedder 卸载 ✅
5. kill 节点 → 2 周期内 DEGRADED → fallback 本地 embed 成功（HOLD 语义）✅
6. 重启节点 → 3 周期恢复 REMOTE → 稳定期后本地模型卸载 ✅
7. A 日志确认请求发往 B ✅

## 执行中发现并修复的 bug

1. 【初版设计缺陷】ManagedModel 持锁等待加载 → status 轮询被卡 30s。修复: 非阻塞 post + Future 回调置态
2. 【实现 bug】get_embedder/get_reranker 远程态仍强制本地加载。修复: _use_remote() 时跳过 ensure_loaded
3. 【测试注入缺陷】stub 只换 sys.modules 不换 services 包属性（先行测试触发真模块 import 后 stub 失效）。修复: 双保险注入
4. 【真 bug·e2e 发现】`_use_remote()` 以模块身份调用实例方法（remote_link.should_use_remote 把模块当单例）→ AttributeError 被 except 吞掉 → 永远走本地。单测 stub 恰好定义模块级函数而掩盖。修复: remote_link.py 增加模块级委托函数（should_use_remote/note_request_failure/get_client），并写明调用纪律注释

## 验收对照（需求 §4）

> **测试运行方式**: 各测试文件独立进程执行（`python3 tests/<file>.py`）——自研 @test 框架非 pytest; 模块级 env 注入（小阈值/DATA_DIR）依赖进程隔离，不可单进程合并执行。

- §4.1 功能: 1-8 全过（常驻隐式验证: e2e 节点 B 配 RESIDENT=1 无 opencode 心跳存活全流程; 心跳日志独立文件双端确认; 开关忠实性 fallback 场景验证 enabled=true + state=degraded 分离展示）
- §4.2 回归: 默认模式行为不变（test_control 80/80 含懒加载/预加载/OCR 空闲卸载/health 语义/心跳自杀/事件库）; 前端 build 过; 两页不回退（零改动区域）
- §4.3 架构: _MlxWorker 零残留; .ai_env 唯一读写方不变; LockedEmbedder/Reranker 签名不变; 消费方（graphiti_config/knowledge_store/knowledge_db/mcp-servers/reranker.py）零文件改动（git status 确认）

## Review 修复轮（实施后独立 review 发现，已全部修复并回归）

| 级别 | 问题 | 修复 |
|------|------|------|
| B1 高 | node-config 转发永不成功（POST 打 PUT-only 端点 405 + 载荷未包 {"configs":...} 422）——卡片 3 全部不可用 | remote_client 增 `_put_json`，`put_node_config` 改 `PUT {"configs": updates}`; 单测断言修正方法+载荷契约; e2e 补转发读写锚点用例 |
| B2 中高 | 转发端点同步 httpx 跑事件循环——节点网络黑洞时全控制台冻结最长 30s | `_forward_get`/`_forward_call` 统一 `asyncio.to_thread` |
| B3 中 | _route_encode/_route_predict 在 ensure_loaded 与拿锁间读到被清空引用 → AttributeError | 引用读取移入 `_infer_lock` 内 + 3 次有界重试 |
| N1 | MlxEngine.infer() 绕过 worker 线程（thread-local Metal stream 脚枪） | 删除（无生产调用方） |
| N2 | CONTROL_RESIDENT 仅启动读一次——运行中开启不生效 | heartbeat 每轮 sweep 重读（即时生效） |
| N3 | progress 文档"全量 pytest"表述与实际机制不符 | 修正为独立进程运行说明（见上） |
| N4 | _local_fingerprints 硬编码 repo 名 | 改用 EMBED_MODEL/RERANKER_MODEL 常量 |
| N5 | 前端表单回填条件会在用户清空编辑时被轮询回填打断 | ref 标记只回填一次 |

## 部署速查（Mac Mini 节点）

1. 同步代码 + venv; 首次手动 `python server.py`（或配置页面操作）
2. 本机页面（localhost）远程资源 TAB → 卡片3: 生成并保存 CONTROL_API_KEY → 重启控制台（自动绑 0.0.0.0 + 三模型预加载; macOS 防火墙允许）
3. 卡片3: 开启常驻（CONTROL_RESIDENT=1）+ 开机自启（LaunchAgent; 系统需开自动登录）
4. 本地主控: 远程资源 TAB → 填 URL（http://<mini-ip>:9776）+ TOKEN（与 CONTROL_API_KEY 同值）→ 保存 → 切换远程
