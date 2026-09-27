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
