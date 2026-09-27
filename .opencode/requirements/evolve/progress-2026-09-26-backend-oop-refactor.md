# Progress: 后端 OOP 重构

> 需求: 2026-09-26-backend-oop-refactor.md（35 步，批次 A-G）
> 当前: 批次 A ✅ + 批次 B ✅ + 步骤 10 ✅（remote_link 单例化被依赖倒逼提前）
> 测试: 124/124 全绿（80+13+9+5+5+4+8）; 当前为**可运行中间态**（新旧并存、无半成品文件）

## 已完成（细节）

| 步骤 | 内容 | 关键产出 |
|------|------|---------|
| 1-4 | ConfigManager | services/config_manager.py: Java 单例(__new__ 双检锁+get_instance+_reset_for_tests); Bootstrap(4 env 键=全项目唯一 os.environ 点)/Keys(28 键)/Protocol/RemoteTunables/HeartbeatTunables/ProxyTunables/ConfigField/ConfigStatusView 全嵌套静态类; get/set/delete/ensure_template/config_meta/required_status/validators; 5/5 单测 |
| 5 | model_lifecycle | ModelWorkerRegistry 静态类(get_worker); STATE_* → ManagedModel 类静态; logger 类化 self.logger |
| 6 | ocr_engines | mlx_available/find_mlx_model/footprint_mb → MlxEngine 静态方法; OLLAMA_*/MAX_TOKENS → 类静态; logger 类化 |
| 7 | ocr_service | OcrService 单例化; 模块级实例+3 委托删除; 消费方(model_assets/remote_link/routes/model_loader/tests)全切 get_instance() |
| 8 | model_loader | → ModelInferenceService 单例: LockedEmbedder/LockedReranker 为内部类; 路由层/推理/生命周期全部实例方法; EMBED_MODEL 引用 ConfigManager.Protocol; 24 个类外函数清零 |
| 9 | model_assets | → ModelAssetRegistry 单例: MODELS/_states/_lock/_change_callbacks 入类; 13 函数全方法化; 消费方(routes/models,deps,system + scanner + tests)全切 |
| 10 | remote_link | RemoteLinkService 单例化(+_shutdown_for_tests 关 client); 模块级实例+3 委托删除; 消费方(model_loader/ocr_service/routes/remote/server/tests)全切 |

## 执行中固化的经验（续作必读）

- **测试顶部 services import 必须在 env 设置之后**（model_assets→config 链冻结 DATA_DIR; 已在 test_control L48 附近修正并有注释）
- **跨批次依赖倒逼**: 消费方先切 get_instance() 时提供方必须立即有单例（步骤 8→10 的教训，运行时静默走 fallback）
- 机械迁移脚本风险: 字符串 replace 会伤 docstring/嵌套词（"def self."、"_ocr_download_worker" 二次命中、MODELS 块缩进）——**每步 compile+测试兜底有效**，但优先 AST 定位
- 测试 patch 私有: `ModelInferenceService.get_instance()._embedder_managed`; OcrService 隔离用 `OcrService._reset_for_tests() or OcrService()`
- stub fake remote_link: 需提供 `stub.RemoteLinkService` 假类（get_instance 返回带三方法的实例）+ sys.modules 与 services 包属性双写

## 剩余步骤（需求 §3.1 逐条执行，映射表在需求 §2.3/§2.4）

- 步骤 11 剩余: routes/remote.py 薄壳化; remote_link._read_config/_local_fingerprints 方法化; STATE_OFF/REMOTE/DEGRADED 常量入类
- 12: api_guard 辅助函数 → 中间件静态方法（LAN_ALLOWED_PATHS 入类）
- 13: launchd_setup → LaunchdManager 单例（LABEL/PLIST_PATH 入类）
- 14-20 批次 D: logging_setup→LogManager; process_lock→ProcessLockUtil（切 ConfigManager._atomic_write）; heartbeat（Registry get_instance+collect 方法化+HEARTBEAT 参数读 ConfigManager.heartbeat_tunables）; ipc_listener（get_instance+全部模块函数方法化）; frontend_port（get_instance+effective_bind_host/_port_alive 方法化+console_url.py 并入）; restart→ConsoleRestarter.get_instance; anonymizer→Anonymizer 静态类
- 21-26 批次 E: event_store/knowledge_store（get_instance+委托删）; knowledge_db（6 常量入 MemoryDB 类）; graphiti_config→GraphitiFactory（load_ai_env 删→ConfigManager）; process_registry; proxy_pool/proxy_relay（模块级状态入类+get_instance）
- 27-31 批次 F: scanner（get_instance）; detect_py_deps（get_instance）; docker_manager→DockerManager（KNOWN_* 入类）; detect_tools（15 辅助函数归类+13 常量入类+ToolsScanner/ToolsInstaller get_instance）; docker_build/push_toolbox 类化
- 32-35 批次 G: server.py+routes 余量薄壳化+health 的 BOOT_TOKEN 等入 HealthService; **删 config.py+config_store.py**（全部 24 消费方切 ConfigManager.get_instance()——grep 清单: routes/config_route,proxy,system + services/api_guard,detect_tools,docker_manager,frontend_port,heartbeat,ipc_listener,knowledge_store,launchd_setup,logging_setup,proxy_pool,proxy_relay,restart,scanner + server.py + tests×2）; 架构 grep 验收（需求 §4.2 六条）; 全量回归+e2e

## 架构验收红线（§4.2，最终检查）

1. os.environ 全项目仅 config_manager.py 内 Bootstrap 读取点
2. from config import / config_store 零残留; 两文件不存在
3. `^[a-z_]+ = [A-Z]\w+\(` 模块级实例导出零残留
4. 顶层大写常量仅嵌套类/异常注册/__all__（AST 扫描）
5. .ai_env 直接 open 仅 config_manager.py
6. routes 处理函数体 ≤3 行

## 追加修复（2026-09-27 晚）：restart execv 自我重跑 bug
- 现象: test_control 全量跑 387s（套件被 os.execv 重跑 2-4 遍，竞态决定次数）
- 根因: services/restart.py L142 残留模块级实例导出 `console_restarter = ConsoleRestarter()`（批次 D 遗漏项）; routes/system.py import 该旧实例; restart 测试 _reset_for_tests 后 patch 的是新实例——路由在旧实例上 schedule 挂真 Timer(1.5s)，perform 里 `os.execv(sys.argv[0])` 在测试进程 = 重跑 test_control
- 修复: 删模块级导出（OOP D 规则彻底达标）; 路由改 `ConsoleRestarter.get_instance().schedule()`; 测试注释同步
- 验证: TC_FULL_RUN=1 全量 97.79s 单遍 80/80（修复前最坏 387s）; grep console_restarter 零残留

## 追加改进（2026-09-27 晚二）：OCR 测试 fake 化提速
- 背景: 套件基线 99s 中 OCR 段占 ~69s——12+1 用例全真模型，加载税 ~20 次 × 2-3s; 其中 9 个用例断言的是状态机行为（非识别正确性）
- 改造: tests/test_control.py 新增 FakeMlxEngine（接口对齐 load/unload/loaded/preprocess/_infer_impl; load_delay 确定性窗口; infer gate; 计数器; fail_load_error 注入; 未加载防御对齐真引擎）; 9 用例切 fake（单飞/串行/在途×2/加载失败/并发失败/reaper/idle_sec/竞态）
- 防覆盖退化三硬约束落地: ①单飞用例加"窗口存在"（starting 轮询）+ "单飞语义"（总耗时 < 3×load_delay）行为特征断言 ②在途用例用 fake infer gate ③fake 计数直接断言（load_count/infer_count）
- 真模型 3 用例保留（lifecycle/窗口卸载/worker 稳定性）: 识别正确性 + stream 复用 + footprint——兼作 fake 接口漂移守卫
- 实施中修两 bug: fake _infer_impl 返回值对齐 (text, stats) 二元组; 串行用例 slow_gen 递归调用自身挂死（改走类原始方法）
- 结果: 9 用例 35.7s → 7.9s; 全量套件 99s → 69.6s（连续两轮 69.56/70.16 稳定）; 80/80

## 追加（2026-09-27 晚三）：[77] 挂起结案 + 生产 bug 修复
- 复测: restart bug 修复后挂起消失（档案 3/3 挂 → 3/3 过，70s 稳定）; 根因统一理论: 旧模块级实例武装真 Timer → perform → os.execv 与 ~20 线程碰撞——成功=套件重跑（×2/×4），冻结=进程级 GIL 冻结（即 [77] 挂起全部"玄学"观测）
- [77] 恢复执行即抓到两处被挂起掩盖的生产 bug: routes/knowledge.py:70 + routes/events.py:73,83 的 submit_entry → submit（OOP 接口漂移，写端点一直 500）; 全路由静态核对无其他漂移
- [77] TC_FULL_RUN 守卫删除（环境变量零残留），保留子进程隔离形态（防 TestClient 循环互锁——独立真实防御）
- 验证: 无守卫全量 3/3 通过 80/80; 档案已结案（§9）

## 追加（2026-09-27 晚四）：全量验收——4 个被掩盖的生产 bug + 测试盲区修复
验收自查发现回归清单遗漏 4 个测试文件（test_e2e_real/test_integration/test_proxy_mcp/test_windows_ipc），补跑后揪出被掩盖的生产 bug 链：
1. **event_store 三处日志 f-string 缺 f 前缀**——异常细节被吞（写入失败的真因不可见）
2. **Keys.DEEPSEEK_SMALL_MODEL 键丢失**（config.py 合并遗漏）——events 提取链断裂; 补回 + 全量键核对（28 键 vs 全部引用，零漂移）
3. **graphiti_config/reranker 裸模块函数调用**（model_loader.embed_batch_sync/rerank_sync 实为实例方法）——落库 embed 与 diverse 搜索 500; 全部改 ModelInferenceService.get_instance()
4. **IpcListener.__init__ 重入抹状态**（单例 __new__ 未防 __init__ 重跑）——每次 get_instance() 复位 _running/_listener → 退出 cleanup 静默跳过 → IPC sock 文件泄漏（生产日志 11 次"死残留"即此因）; 修为 _init_once 模板 + AST 排查全项目无同款
测试侧修复：
- test_integration bun_env 适配 D1 收口（HEARTBEAT_* 小值从进程 env 改独立 OPENCODE_ROOT + .ai_env + backend 目录 symlink）; 宽限 5→15s（覆盖 TS 就绪确认链）; 自杀等待 12→40s
- test_control IPC 测试改 object.__new__ 模拟第二实例（原依赖 __init__ 重入 bug 行为）
- test_proxy_mcp 无 __main__ 入口（直跑=假绿）——确认为 pytest 收集形态，2/2 通过
最终验收全绿：control 80 + integration 5 + e2e_real 6 + e2e_remote 全链路 + 7 快族 51 + proxy 58+2 + mcp 2 + 前端 build; 生产控制台重启吃全部修复（pid 60146）

## 追加（2026-09-27 晚五）：graphiti 适配器真链测试（需求文档 2026-09-27-graphiti-adapter-real-test.md）
- 背景: FakeGraphiti 把组装链（BgeM3Embedder/BgeRerankerClient/GraphitiFactory.create_graphiti）整体短路——纯项目胶水层曾零单测级动态覆盖（晚四 bug #2/#3 藏点）
- 实施: test_control 新增 81 号用例（四段断言: create 1024 维 / create_batch 2×1024 / rank 真推理区分度+降序 / create_graphiti 组装类型——graphiti 未传参静默默认 OpenAIEmbedder 的唯一防线）; 置 E2E /rerank 后
- 防作弊闭环: 注入旧 bug 形态（reranker.py 裸模块调用）→ 用例红（报错与生产当天一字不差）→ 还原 → 绿
- 验收: 81/81（耗时 77.8s，增量 ~8s 含测试进程首次模型加载）; e2e_real 6/6; config_manager 5/5 + api_guard 4/4 抽测绿; 生产代码零改动
