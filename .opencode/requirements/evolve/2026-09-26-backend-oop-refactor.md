# 后端 OOP 全面重构（配置统一 + 单例化 + 函数式清除）

> 状态: 已确认（用户逐条裁决 E1-E4 豁免 + D1-D5 边界，2026-09-26）
> 范围: control/backend 全部 41 个 .py 文件 + tests。前端不动（D4）。
> 铁律: **写对，而不是改少**。任何一处被用户指出才改 = 失败。

---

## §1 背景与目标

**来源**: 用户对后端架构的三项判定——① 配置两套机制（config.py 的 os.environ 散读 + config_store.py 的 .ai_env 读写）逻辑散开，绝对禁止; ② 模块级实例导出（`xxx = Xxx()`）是违禁单例写法，必须 Java 式; ③ 函数式编程写法全部清除，常量必须收进类的静态字段。

**用户裁决清单**（实施不得偏离）:

| # | 裁决 |
|---|------|
| E1 | FastAPI 路由处理函数豁免类化（框架硬约束），但必须薄壳化: 1-3 行，零业务逻辑，全部下沉 service 类 |
| E2 | pydantic BaseModel 与 dataclass 豁免（本身是类/数据类） |
| E3 | 测试用例函数（@test 装饰器）与 main() 进程入口豁免 |
| E4 | 局部闭包尽量换私有方法，压到接近零 |
| D1 | DATA_DIR / OPENCODE_ROOT / CONTROL_TCP_PORT 三个引导参数保留 env 读取，收口为 ConfigManager 内部唯一 env 读取点，全项目其余零 os.environ |
| D2 | 纯协议常量（EXIT_CODE_*/IPC socket 名/TCP 候选段/模型名等 plugin↔console 两端一致的）→ 类静态字段不进 .ai_env; 行为可调参数（HEARTBEAT 三件套/代理池调参 5 项等现有 env 覆盖式常量）→ .ai_env hidden 化 |
| D3 | 单例提供 `_reset_for_tests()` 类方法（仅 tests 使用） |
| D4 | 前端不动 |
| D5 | 全部 41 文件纳入（含 detect_tools.py 2416 行），手法为保语义迁移不重写逻辑 |

**调研基线**（Phase 0 实测）: 类外函数 259 个（routes 约 80 个属 E1）; 顶层常量 112 个; 模块级实例导出 15 处; config/config_store 消费方 24 文件; os.environ 29 处 8 文件。

---

## §2 技术方案

### 2.1 Java 单例标准模板（全项目统一，双检锁）

```python
class XxxService:
    _instance: "XxxService | None" = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "XxxService":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._init_once()          # 全部构造逻辑（代替 __init__）
                    cls._instance = inst
        return cls._instance

    @classmethod
    def get_instance(cls) -> "XxxService":
        return cls()

    @classmethod
    def _reset_for_tests(cls) -> None:
        with cls._instance_lock:
            if cls._instance is not None:
                cls._instance._shutdown_for_tests()   # 默认空实现，有资源的类覆盖
            cls._instance = None

    def _shutdown_for_tests(self) -> None:
        """测试重置时的资源收尾（默认无资源空实现; 持线程/连接的类覆盖）。"""
```

规则: `XxxService()` 与 `get_instance()` 等价返回同一实例; **禁止任何模块级 `xxx = Xxx()` 导出**; `__init__` 不定义（防重复初始化），构造逻辑全部在 `_init_once`。

### 2.2 ConfigManager（services/config_manager.py，配置唯一权威）

```python
class ConfigManager:
    # ── 嵌套静态类: 常量全部收口 ──
    class Bootstrap:   # D1 引导参数 env 键名（唯一 env 读取点）
        DATA_DIR / OPENCODE_ROOT / CONTROL_TCP_PORT
    class Keys:        # 全部 .ai_env 键名常量（46 个，含 DEEPSEEK_*/REMOTE_*/CONTROL_*/JULIANG_*/HEARTBEAT_*/PROXY_*）
    class Defaults:    # 可调参数默认值（REMOTE 六项/HEARTBEAT 三项/PROXY 调参五项...）
    class Protocol:    # D2 协议常量（EXIT_CODE_*/IPC_UNIX_SOCKET_NAME/IPC_WINDOWS_PIPE/
                       #   CONTROL_TCP_PORT_START/TCP_CANDIDATE_COUNT/BIND_HOST/
                       #   EMBED_MODEL/RERANKER_MODEL/MODEL_LOAD_TIMEOUT_SEC/HEALTH_POLL_INTERVAL_SEC/
                       #   IPC_BIND_WAIT_SEC/REMOTE_RELAY 端口段/JULIANG_API_URL/OCR 常量...）
    class Meta:        # ConfigField dataclass + required/extra/remote_tab/tunable 清单构建

    # ── dataclass（E2 豁免）: RemoteTunables/HeartbeatTunables/ProxyTunables ──

    # ── 实例 API ──
    get(key) -> str | None            # .ai_env 读
    get_all() -> dict[str, str]
    set(updates) -> dict              # .ai_env 写（原子，保留注释）
    delete(key) -> dict
    ensure_template() -> bool
    # 属性: data_dir / opencode_root / ai_env_path / is_dev_mode / is_windows
    #       tcp_port_start()（Bootstrap env 覆盖，测试隔离用）
    #       ipc_addr() / ipc_unix_socket_path()
    # tunables（每调重读 .ai_env，非法回退默认）:
    remote_tunables() / heartbeat_tunables() / proxy_tunables()
    # 元数据与校验:
    config_meta() -> dict             # /api/config/meta 数据源（含 hidden）
    required_status() -> list[ConfigStatusView]
    validate_api_key(v) / validate_ida_pro_home(v)
    required_configs() / extra_configs() / remote_tab_configs() / tunable_configs()
```

- 原 config.py 与 config_store.py **删除**（全部消费方切换后）。
- `.ai_env` 唯一读写方 = ConfigManager（架构验收 grep 红线不变）。
- graphiti_config.load_ai_env（os.environ setdefault 兜底）删除——消费方改读 ConfigManager。

### 2.3 单例化映射表（15 处模块级实例）

| 旧导出 | 新访问方式 |
|--------|-----------|
| ocr_service = OcrService() + extract/force_release/status 委托函数 | OcrService.get_instance()（委托函数删） |
| remote_link = RemoteLinkService() + should_use_remote 等 3 委托 | RemoteLinkService.get_instance()（委托删; model_loader/ocr_service/routes 调 get_instance()） |
| heartbeats = HeartbeatRegistry() | HeartbeatRegistry.get_instance() |
| frontend_ports = FrontendPortRegistry() | FrontendPortRegistry.get_instance() |
| ipc_listener = IpcListener() + start_ipc_listener/cleanup 模块函数 | IpcListener.get_instance()，start/cleanup 为实例方法 |
| scanner = Scanner() | Scanner.get_instance() |
| _service = EventStoreService() + start/submit_entry 委托 | EventStoreService.get_instance() |
| _service = KnowledgeStoreService() + 委托 | KnowledgeStoreService.get_instance() |
| _detector = PyDepsDetector() | PyDepsDetector.get_instance() |
| _scanner = ToolsScanner() / _installer = ToolsInstaller() | 各自 get_instance() |
| console_restarter = ConsoleRestarter() | ConsoleRestarter.get_instance() |
| _embedder_managed/_reranker_managed（model_loader） | 并入 ModelInferenceService 实例字段 |
| proxy_pool/proxy_relay 模块级状态与函数 | ProxyPool.get_instance()/ProxyRelay.get_instance() |
| process_registry 模块级状态 | ProcessRegistry.get_instance() |

### 2.4 函数式 → 类化映射（services 域 ~180 个函数）

| 旧模块 | 目标态 |
|--------|--------|
| model_loader.py（24 个类外函数） | ModelInferenceService 单例: LockedEmbedder/LockedReranker 保留为内部类; embed_sync/embed_batch_sync/rerank_sync/get_embedder/get_reranker/is_models_ready/is_reranker_loaded/embedder_status/reranker_status/release_all_local/preload_*/路由层(_use_remote/_route_encode/_route_predict/note) → 实例方法; EMBED_MODEL 等引用 ConfigManager.Protocol |
| docker_manager.py（15 函数+13 常量） | DockerManager 单例: KNOWN_CONTAINERS/KNOWN_IMAGES → 类静态字段; ensure_daemon_blocking/ensure_neo4j_events_blocking/_run_docker/list/start/stop/create/pull/status → 实例/静态方法 |
| model_assets.py（13 函数） | ModelAssetRegistry 单例: MODELS → 类静态; _states/_lock → 实例字段; get_model_assets/download/start_download → 方法 |
| detect_py_deps.py（11 函数） | PyDepsDetector 方法化（保留既有内部类） |
| remote_link.py（6 函数: _read_config/_local_fingerprints/3 委托） | _read_config/_local_fingerprints → RemoteLinkService 私有方法; 委托删 |
| api_guard.py（2 函数） | _is_local/_path_allowed → ApiGuardMiddleware 静态方法; LAN_ALLOWED_PATHS → 类静态 |
| launchd_setup.py（7 函数+2 常量） | LaunchdManager 单例: LABEL/PLIST_PATH → 类静态; install/uninstall/status → 方法 |
| logging_setup.py（2 函数+4 常量） | LogManager 单例: setup()/setup_auxiliary(name, filename); LOG_FILE/格式常量 → 类静态 |
| process_lock.py（4 函数） | ProcessLockUtil 静态方法类（get_process_start_time/atomic_write/...） |
| heartbeat.py（collect_opencode_processes + 模块常量） | → HeartbeatRegistry 方法; 常量 → ConfigManager（HEARTBEAT 三件套 .ai_env 化 per D2; OpencodeProcessInfo 保留 dataclass） |
| frontend_port.py（effective_bind_host + _port_alive） | → FrontendPortRegistry 静态/实例方法 |
| restart.py（refresh_env 等） | → ConsoleRestarter 方法 |
| anonymizer.py（1 函数） | Anonymizer 静态方法类 |
| scanner.py（1 函数） | Scanner 方法 |
| event_store.py / knowledge_store.py（模块级委托 start/submit/...） | 删委托，消费方 get_instance().xxx |
| graphiti_config.py（3 函数+load_ai_env） | GraphitiFactory 静态方法类（create_graphiti/get_deepseek_api_key→删，读 ConfigManager; BgeM3Embedder 保留类） |
| proxy_relay.py（9 函数）/ proxy_pool.py（4 函数+模块级 _log/_cache） | 类化 + get_instance |
| process_registry.py（4 函数） | ProcessRegistry 方法 |
| knowledge_db.py（顶层常量 6 个） | → MemoryDB 类静态字段（EMBEDDING_DIM/DEFAULT_TOP_K/SCORE_THRESHOLD/SCHEMA_SQL/INDEX_SQL/MIGRATE_COLUMNS） |
| ocr_engines.py（3 函数+4 常量） | MlxEngine 静态方法化（mlx_available/find_mlx_model）+ MlxSupport 静态类（footprint_mb）; OLLAMA_*/MAX_TOKENS → 类静态 |
| docker_build_toolbox.py / docker_push_toolbox.py（各 5-6 函数） | ToolboxBuilder/ToolboxPusher 类 |
| detect_tools.py（15 函数+13 常量） | 辅助函数 → 就近归入 23 个既有类的静态方法; 常量 → 类静态 |
| llm_client.py（若有模块级辅助） | 入 DeepSeekLLMClient |
| console_url.py（1 函数） | 并入 FrontendPortRegistry 或就近类（调研后定，文档实施时记录） |
| model_lifecycle.py（_get_worker+注册表） | ModelWorkerRegistry 静态类（worker 按名共享语义不变） |
| remote_client.py | 已全类 ✅ 仅核对 |
| scanner.py / detect_* 内部 os.environ | 切 ConfigManager |

### 2.5 routes 薄壳化（E1）

全部 18 个 route 文件: 处理函数 ≤3 行（参数解析 + service 调用 + 返回）; config_store/config 引用全部切 `ConfigManager.get_instance()`; 逻辑（如 routes/remote.py 的转发编排函数 _forward_or_local 等）下沉到对应 service。

### 2.6 server.py

create_app()（装配: 全部 get_instance）/ main()（E3 豁免）; `from config import ...` 全部移除。

### 2.7 tests 适配

- 全部 `from config import X` / `config_store.xxx` → ConfigManager
- 沙箱隔离: `ConfigManager._reset_for_tests()` + 引导 env（测试进程级）——替代原 monkeypatch config_store 的用例改为 patch ConfigManager 实例方法或写沙箱 .ai_env
- 测试文件自身函数（E3 豁免）

---

## §3 实现规范

### 3.0 改动范围

新增: services/config_manager.py（~450 行）。删除: config.py（340）+ services/config_store.py（274）。重写/迁移: services 25 文件 + routes 18 文件 + server.py + tests 8 文件。总量估 ~6000 行 diff。

### 3.1 实施步骤（依赖序; 每步 ≤200 行 diff; 每步 compile+相关测试）

**批次 A: 配置中枢**
1. config_manager.py 骨架: 单例模板 + Bootstrap/Keys/Protocol/Defaults 静态类 + 引导属性（data_dir/opencode_root/is_dev_mode/ipc_addr/tcp_port_start）+ get/get_all/set/delete/ensure_template（自 config_store 迁移）
2. config_manager: tunables 三件（Remote/Heartbeat/Proxy dataclass + 读取器）
3. config_manager: ConfigField + 四清单 + config_meta + required_status + validators + _init_validators 等价物
4. tests/test_config_manager.py: 单例身份/重置/读写/回退默认/hidden 元数据/沙箱隔离

**批次 B: 模型域切换**（每文件一步: 类化+单例化+切 ConfigManager+编译+test_model_lifecycle 回归）
5. model_lifecycle.py（WorkerRegistry 静态类化）
6. ocr_engines.py（静态类化+常量入类）
7. ocr_service.py（get_instance; 委托删; 消费方 model_assets/routes/test_control 同步）
8. model_loader.py → ModelInferenceService（最大单文件，含路由层方法化; model_assets/graphiti_config/knowledge_store/routes 同步切换）
9. model_assets.py → ModelAssetRegistry

**批次 C: 远程域**
10. remote_link.py（get_instance; _read_config/_local_fingerprints 方法化; 委托删; model_loader/ocr_service/routes 切换）
11. remote_client.py 核对 + routes/remote.py 薄壳化（转发编排下沉 RemoteLinkService/新 NodeAdminService）
12. api_guard.py（辅助函数→中间件静态方法）
13. launchd_setup.py → LaunchdManager

**批次 D: 基础设施**
14. logging_setup.py → LogManager（server.py/remote_link 切换）
15. process_lock.py → ProcessLockUtil（消费方 config_manager/config_store 迁移期内切换）
16. heartbeat.py（Registry get_instance + collect 方法化 + HEARTBEAT 参数 .ai_env 化; routes/system 切换）
17. ipc_listener.py（get_instance; start/cleanup 方法化; server.py/测试切换）
18. frontend_port.py（get_instance; effective_bind_host/_port_alive 方法化; console_url.py 并入; server/routes/health 切换）
19. restart.py → ConsoleRestarter.get_instance（routes/system 切换）
20. anonymizer.py → Anonymizer（knowledge_store 切换）

**批次 E: 存储与编排**
21. event_store.py（get_instance; 委托删; routes/events/server 切换）
22. knowledge_store.py（同上; routes/knowledge 切换）
23. knowledge_db.py（常量入类）
24. graphiti_config.py → GraphitiFactory（load_ai_env 删; event_store 切换）
25. process_registry.py（get_instance; routes/processes 切换）
26. proxy_pool.py / proxy_relay.py（类化+get_instance; routes/proxy 切换）

**批次 F: 检测器**
27. scanner.py（get_instance; routes 切换）
28. detect_py_deps.py（get_instance）
29. docker_manager.py → DockerManager（常量入类; routes/docker/deps/scan 切换）
30. detect_tools.py（辅助函数归类+常量入类+双 get_instance; 2416 行保语义迁移）
31. docker_build/push_toolbox（类化; routes/install 切换）

**批次 G: 装配与收尾**
32. server.py 全装配切换 + routes 余量（hardware/system/fs/models/scan/install/ocr/embed/heartbeat/config_route/deps）+ routes/health.py 的 BOOT_TOKEN/_BOOT_FINGERPRINT/_code_fingerprint 顶层常量与函数 → HealthService 类（常量入类）
33. 删 config.py + config_store.py; grep 验收: `os.environ` 仅 config_manager.py 3 处（Bootstrap）; `from config import`/`config_store` 零残留; 模块级实例导出零残留
34. tests 全量适配（test_control 80 用例的 config/单例引用; AST 守护断言同步; 其余 5 文件）
35. 全量回归（119+config_manager 新测）+ e2e 双进程 + 前端 build 确认不受影响（接口契约不变）

**补遗（并入既有步骤执行）**: llm_client.py 模块级辅助 → DeepSeekLLMClient（随步骤 24 graphiti_config 切换一并）; ipc_listener.py 的 probe 等全部模块函数方法化（步骤 17 表述含全部模块函数）。

### 3.2 编码规则

- **跨批次消费方铁律**: 任何步骤改变了某模块的公开调用面（函数→方法/委托删除），其**全部消费方的调用点必须在同一步骤内同步切换**（消费方自身结构可留待其所属批次，仅切调用）——杜绝中间态 import 挂
- 单例模板严格统一（§2.1）; 禁止 `__init__`（用 _init_once）; 禁止模块级实例
- 常量只存在于: ConfigManager 嵌套静态类 / 各服务类的类静态字段。模块级大写变量 = 违规（dataclass/`__all__` 除外）
- 保语义迁移: 逻辑/分支/锁语义/日志文案不动，只动组织结构; 发现原逻辑疑似 bug 记录到 progress 待办，不顺手改（混淆回归归因）
- 路由薄壳 ≤3 行; E4 闭包换私有方法（线程 target 用实例绑定方法）
- 每步完成即 compile + 该域测试; progress.md 每批次更新
- 既有 AST 守护测试（_infer_lock 锁点数/sentence_transformers 唯一 import 等）随结构迁移同步更新断言，语义不弱化

---

## §4 验收标准

### 4.1 功能
1. ConfigManager 全项目配置唯一权威: get/set/tunables/validators 全通
2. 全量测试通过: 既有 119 用例（适配后）+ config_manager 新用例
3. e2e 双进程全链路（探测/鉴权/切换/转发/embed 远程/降级 fallback/恢复卸载）不回退

### 4.2 架构（grep 红线）
1. `os.environ` 全项目仅 services/config_manager.py 内 3 处（Bootstrap 三键）
2. `from config import|import config$|config_store` 零残留; config.py/config_store.py 文件不存在
3. `^[a-z_]+ = [A-Z]\w+\(` 模块级实例导出零残留（services 全域）
4. 顶层大写常量仅允许出现在: 嵌套类/异常类注册/`__all__`（AST 扫描脚本验收）
5. `.ai_env` 直接 open 仅 config_manager.py
6. routes 处理函数体 ≤3 行（AST 扫描豁免装饰器/签名行）

### 4.3 回归
- 默认模式行为不变（懒加载/心跳自杀/事件库/OCR 空闲卸载）
- HTTP API 契约不变（前端零改动可正常 build+交互）

---

## §5 与现有需求文档的关系

- 2026-09-26-remote-model-offload.md: 功能语义完全保留，本重构只动组织结构; 其 §4 验收继续有效
- 2026-09-25-locked-embedder-serialization.md: 串行不变量语义不变（_infer_lock 机制随 ModelInferenceService 迁移，锁点数断言同步更新）
- 2026-08-22-ocr-*.md: OCR 生命周期语义不变（ManagedModel 收口保持）
