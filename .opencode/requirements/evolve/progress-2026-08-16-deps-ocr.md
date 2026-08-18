# 进度：依赖检测收口 + 本地 OCR 服务

需求文档：2026-08-16-deps-layering-and-local-ocr.md

## 阶段 A：依赖检测收口 ✅ 全部完成

- [x] A1 py_deps_detector.py —— 唯一清单（30 包：bootstrap 7 + 全集；uvicorn/pymupdf 新增；sage conda 特例）；scan(agent, python_exe) import/CLI 双入口一致已验证
- [x] A2 tools_detector.py —— 删重复清单改引用（PYTHON_PACKAGES/scan_python_packages/pip_installable_packages 兼容 re-export）；编译器检测迁入（clang 实测检出）
- [x] A3 detect_env.py —— 瘦身纯安装器（install [--full] [--dry-run]）；清单从 py_deps_detector 文件路径加载（sys.modules 注册坑已修）；install.sh 零改动；check-preinstall 已删
- [x] A4 console_url.py + vite write-dev-port 插件 —— 三态验证过（开发态 5173/停回退 9776/发布态 9776）；两坑已修：vite 只监听 [::1]（双栈探测）、PORT_FILE 三行格式（取首行）
- [x] A5 routes/deps.py —— 聚合五分类 + summary（ready/required_missing/optional_missing/console_url）；SHARED_INFRA_AGENTS=8 注册 agent 镜像（对齐 constants.ts）；"all"=coordinator 语义
- [x] A6 plugin env-check —— checkDepsViaControl（轮询等控制台就绪 45s + /api/deps + interpretDepsSummary 纯函数）；preheat 扩到 8 agent；chat.message 两分支统一（evolve/searcher/memorist 特判删除）；detect_env spawn 链零残留
- 回归：后端 53+5 ✓ TS 18 ✓（一个旧契约测试已更新为新契约）

## 阶段 B：OCR 服务 ✅ 全部完成

- [x] B1 ocr_service.py —— 单锁状态机/引用计数/30s 空闲释放/孤儿复用（0ms 热接入）；四场景实测过；发现并修复 reaper "纯 acquire 不释放" 缺陷（_last_activity_at 统一）
- [x] B2 routes/ocr.py（acquire/extract/close/status/release）+ server.py 挂载；沙箱 E2E 全通；修复 mlx server model 字段必须传完整路径的 400
- [x] B3 Ollama 分支 —— 假 Ollama server 协议级验证（keep_alive=30s/keep_alive=0/tags 检测/平台分发含 IntelMac→ollama）
- [x] B4 model_assets glm-ocr（平台化缓存检测+下载：mac=mlx-env+HF / 其他=ollama pull）+ 前端模型页（geekblue OCR 标签+运行状态+停止按钮，Playwright 截图验证）；修复 mlx-env 路径笔误（DATA_DIR/mlx-env）
- [x] B5 mcp-servers/ocr —— FastMCP stdio + extract_text + lifespan acquire/close + pyproject.toml；stdio 握手 E2E 全通（initialize/tools-list/tools-call/退出引用归零）
- [x] B6 mcp-manager 注册 +ocr；TS 18 绿
- [x] B7 卸载 rapidocr/onnxruntime/pyobjc 全家（7 包，残留 0）
- [x] B8 回归 63+53+5+18=139 全绿 + 文档同步（binary/crypto agent prompt、plugin-debugging 知识库、三 agent 加 ocr_extract_text 索引行）

## Phase 6 审计 ✅

轮 1 修复 2 项：deps "all"(coordinator) 补共享底座；install.sh/ps1 透传 --full。
轮 2 修复 1 项：routes/ocr.py 未用 import。
纯审计轮：14 文件语法全绿、依赖方向无环、console_url 单实现、兼容层无悬挂引用。零遗留。

## 待用户操作

- **重启 opencode**：plugin（API 检测 + MCP 注册）与控制台（新路由）都是启动时加载
- 重启后验证：agent 工具列表出现 ocr_extract_text；缺依赖消息含控制台链接
- B4 前端模型页的 glm-ocr 运行状态/停止按钮在 OCR 服务运行时可见（当前未运行属正常）

## 关键实现事实（续作者必读）

- PORT_FILE（~/bw-security-analysis/.opencode-control.port）三行格式：port/pid/start_time，读端口取首行
- vite Node17+ localhost→::1 只监听 IPv6，探测必须双栈（127.0.0.1 + ::1）
- py_deps_detector 被 detect_env 用 spec_from_file_location 加载时必须先 sys.modules 注册（frozen dataclass 内部查 sys.modules[cls.__module__]）
- MLX 环境固化在 ~/bw-security-analysis/mlx-env（PyPI mlx-vlm==0.6.13）；模型 HF 缓存 models--mlx-community--GLM-OCR-4bit (1.2GB)；glm-ocr chat 格式必须图在前（LIST_WITH_IMAGE_FIRST）
- Ollama glm-ocr 2.2GB 在库（备份路径）
- 生产控制台（9776/pid 99785）还跑旧代码——全部完成后需重启 opencode 生效
- 沙箱测试：DATA_DIR=/tmp/xxx + 随机端口；TS 测试 DATA_DIR=/tmp/control_test_ts bun tests/test-control.ts

## 追加整改（用户指出 detect_env.py 未搬迁 + 测试盲区）

- [x] detect_env.py git mv → control/backend/services/（install.sh/ps1 路径更新；OPENCODE_ROOT 四级推导；清单同目录加载）
- [x] 全仓 22 处文档/注释引用清扫（README 树/environment-setup/plugin-debugging/evolve/crypto-methodology/events 同源注释/web_render 提示等），grep 终验零残留
- [x] test/detect_env 重写（35 用例对准新架构：py_deps 清单约束/CLI-import 一致性/dry-run/tools_detector）；删 test_detection/test_preinstall/test_tools（测 HEAD 已不存在的远古函数）
- [x] test/env-check 整目录删除（subject=check-preinstall 流程已退役；HEAD 时即坏死）
- [x] test/runDetectEnv → test/envCheck（bun 测 interpretDepsSummary，5 用例过）
- 既有问题（非本次改造引起，未修，待专项）：test/knowledge 与 test/mcp_events 同名 test_unit_await_behavior.py 导致 `pytest test/` 整树收集错误（HEAD 即如此）；test/mcp_events 执行需 Docker/Neo4j 会挂起；test/shell 为 bats 套件；各目录需按套件单独跑

## 追加整改 2（用户审计 8 项 + 同类全仓排查）

- [x] install.sh/ps1 参数透传删除（--full 按 YAGNI 移除；detect_env 同步删 --full/conda 分支/playwright post-install；test_install 用例同步）
- [x] binary-analysis.md：环境检测节删除（程序化检测，agent 无需知道）；IDA_ENV_JSON 传参删除（env_cache 机制残留）
- [x] crypto-analysis.md：sage 三处改为准确语义（optional 不拦对话；agent 探测 + gmpy2/sympy 降级）
- [x] 3 个领域 agent 的 ocr_extract_text 描述行删除（MCP 描述自动注入，prompt 不重复；pymupdf 分流提示并入 ocr MCP 工具描述）
- [x] evolve.md：规则 6 改 $IDAT（plugin 注入）；规则 8 加第 6 条"不描述已退役机制"+原因；反模式表加"MCP 描述重复"条目
- [x] _analysis.py classify_scene 删 packages 参数（数据源已死）；initial_analysis.py 删 IDA_ENV_JSON 加载链；frida_available 字段删除（frida 为 required，agent 运行时必可用）
- [x] context-persistence.md / environment-setup.md 删除（面向使用者的历史设计文档，零运行时引用；README 树同步）
- [x] plugin-debugging.md 四处旧机制残留重写（真实机制：控制台健康检查 + 配置页）；events/env-check/hooks-lifecycle 措辞去墓碑；tools_detector/docker_manager"迁移自"注记清除
- 判定不动：searcher.md/memorist.md 的 MCP 表格（"什么时候用"选型策略 + 声明 schema 自见，非描述复制）；android/rsa/client-side 知识库的"旧版"（外部技术版本对比，非本项目机制）

## 追加整改 3（命名统一：detect_[类型].py / install_[类型].py）

- [x] services/ 三个文件定名：detect_py_deps.py（检测 Python 依赖）/ detect_tools.py（检测工具）/ install_py_deps.py（安装 Python 依赖——原 detect_env.py，安装器不得占用 detect_ 前缀）
- [x] 全部引用方同步（routes×2/scanner/test_control/install.sh+ps1/venv.ts/evolve.md/technology-selection）
- [x] 符号级对齐：DETECT_PY_DEPS_PATH、_INSTALL_PY_DEPS_BOOTSTRAPPED、_INSTALLER_PATH
- [x] test/detect_env/ → test/deps/（目录+文件名+fixture env→installer）
- [x] 残留扫描整仓零命中；34+63+53+5+18 全绿；install.sh 实跑全链通过

## 追加整改 4（install_py_deps.py 去 .ai_env 职责错位）

- 根因：.ai_env 读写是 detect_env 检测时代遗产——检测迁控制台后，安装流程（venv+pip）零消费
- [x] _load_ai_env()/_ensure_ai_env_template()/_AI_ENV_TEMPLATE/AI_ENV_FILE 从 install_py_deps.py 删除（安装器纯净：只装包）
- [x] ensure_template() 落 config_store（.ai_env 唯一读写方），server.py create_app 启动期调用
- [x] test_config 删两个旧测试类（被测函数已删）；test_control 加 ensure_template 幂等测试（54/54）
- [x] README 中英模板创建时机措辞同步（安装时 → 控制台首启）

## 追加整改 5（安装器并入 detect_py_deps.py，消灭 importlib 动态加载）

- 用户决策：detect_py_deps.py 直接承载"检查 + 安装"两个子命令，install_py_deps.py 删除
- [x] detect_py_deps.py：清单+scan 检测保持，安装函数并入（_find_conda/_get_venv_python/_bootstrap_venv/_run_install），CLI 改 subparsers（scan --agent/--python/--json + install --dry-run）
- [x] install.sh/ps1 → detect_py_deps.py install；venv.ts/evolve.md/install 脚本头注释同步
- [x] 测试重构：test_config.py（被测桥已消失）与 test_install_py_deps.py 删除，install dry-run 用例并入 test_py_deps.py；conftest 只留 py_deps fixture
- [x] bootstrap 语义保留（自举必需：控制台跑在 venv 里，起不来之前只能脚本装）

## 追加整改 6（bootstrap 概念删除——用户否决最小集方案）

- 用户指出矛盾：plugin 经 /api/deps 强制全部 required 存在（不存在即拦截），install 却只装 7 包 bootstrap 集 → 装完必被拦（连 evolve 都拦：mcp/playwright/sympy 为 agents=all 级 required），最小集毫无意义
- [x] PyPkgField.bootstrap 字段/7 个条目标志/scan entry 键/bootstrap_packages() 全部删除
- [x] install 子命令装 required_packages()（required 且平台适用，mac 上 28 个；sage 可选不装）
- [x] install 集合 ⊇ 全部 6 类 agent 的 required 集（脚本验证过）
- [x] install.sh/ps1 防呆注释、security-analysis.ts/detect_tools.ts 措辞、测试（TestRequiredInstallSet + dry-run 动态断言）、README 同步

## 追加整改 7（两条知识库原则：无控制台内部引用 / 无手动操作）

- 原则确立：①领域 agent/知识库不引用控制台内部实现（detect_tools、/api/deps 等）——agent 拿信息走环境注入（$IDAT）或自己 bash 可执行的方式（vswhere/grep .ai_env）；②不写手动操作（打开控制台/点击）——只写 agent 能跑的命令
- [x] technology-selection.md：vcvarsall 路径改为 agent 可执行的 vswhere 命令 + 目录探测 fallback
- [x] crypto-methodology.md 3.3：去 /api/deps 引用，改 agent 视角（sage --version 探测 + 等价路径 + 确认后安装）
- [x] crypto-analysis.md 核心约束补可选依赖指引（零控制台引用；注：早前整改的 3 处 blockquote 在中断期间被外部改动丢失，本次以更简形式补回）
- [x] web-rendering.md + web_render.py：playwright 修复改为 $PYTHON_CMD 命令（agent 可执行）
- [x] plugin-debugging.md：配置查询改 grep .ai_env（读者=evolve，调试用可执行命令）
- 合法保留：GUI 自动化类知识库的"点击"（逆向目标程序的操作）；hooks-lifecycle 的"用户点击 New Session"（宿主触发条件描述）；README 的控制台指引（读者=人类用户）

## 追加整改 8（/api/deps 性能：并行扫描 + 快照缓存 + 启动预热）

- 实测痛点：plugin 启动 8 连击 × 各自独立全扫 = 4431ms（Docker/工具子进程 ×8 份互相竞争）
- [x] S1 detect_tools 并行扫描：_scan_all_tools_parallel（每工具一线程 + 15s 整体超时占位）；scan_agent/scan_all 改为总表过滤（消 ida_pro×4 重复）；串行→稳态 ~175ms（首扫 JVM 冷缓存 ~700ms 由预热吸收）
- [x] S2 deps.py 两阶段：快照层（五项并行 _build_snapshot_sync + 单飞锁双检 + TTL 30s + ?refresh=1 + _safe 单项降级不拖垮快照）+ 组装层（按 agent 过滤 µs 级现算）
- [x] S3 主动失效钩子：install 装包成功 / docker 容器启停 / config 三写点 → invalidate_deps_snapshot；模型下载完成走 model_assets.add_change_callback（service 发布回调，deps 注册——依赖方向 routes→services 合法）
- [x] S4 启动预热：app.on_event("startup") 后台线程构建快照写缓存（首请求实测 431ms→预热吸收大半；稳态命中 1ms）
- [x] 修复顺手发现的 config_store.ensure_template 幂等 bug（已存在分支误返 True）
- 实测：8 连击 4431ms→11ms（400×）；TTL 内单发 1ms；refresh 强制重建 538ms；主动失效后首个请求 306ms（重扫生效）；evolve/binary 底座归属语义不变
- 回归：20+63+54+5+18 全绿

## 追加整改 9（快照层强类型重构——用户指出 dict/any 风格与封装破坏）

- [x] DepsSnapshot dataclass 定型快照（python/tools_table/compiler/docker_global/models/built_at/expires_at + is_valid()）；_assemble 签名强类型、字符串键访问（snap["python"]）全部改属性访问
- [x] 封装收口：_build_snapshot_sync 构建即写缓存（外部不再接触 _cache）；server.py 预热改调公开 warm_deps_snapshot()（不再摸 _snapshot 私有变量）；写缓存 threading.Lock（预热线程×请求线程池共用）
- [x] 降级值收口 _compiler_fallback/_docker_fallback 工厂（dataclass 字段与 _safe 共用同源）；修复工厂定义序（类体引用后置函数的 NameError——测试冒烟逮住）
- 实测：8 连击 7ms / TTL 单发 1ms / 失效重扫 335ms / evolve 语义不变；回归 20+63+54+5+18 全绿

## 追加整改 10（global _cache 消除——状态封装进 _SnapshotCache 容器）

- 说明：原三处 global _cache 中两处是 Python 赋值语义必需（非冗余），但 global 管理可变状态本身是坏味道——封装进 _SnapshotCache（get/get_valid/set/clear，内部 threading.Lock），读写全走方法，global 声明消失
- [x] 验证：8 连击 9ms / TTL 单发 1ms / 失效重扫 349ms / evolve 语义不变；deps 20 + control 63 + 单元 54 + 集成 5 全绿

## 追加整改 11（全链强类型 + OOP 化——用户铁律）

- [x] T1 detect_tools：ToolStatus/CompilerInfo dataclass（timeout/skipped_platform/unavailable 静态工厂）+ ToolsScanner 类（scan_tool/scan_all_parallel/scan_agent/scan_all/detect_compiler 全类化，模块级单例+委托兼容）
- [x] T2 detect_py_deps：PyPkgStatus + PyDepsDetector 类（scan/_detect_one 类化；CLI asdict；安装保持一次性 CLI 流程函数）
- [x] T3 docker_manager：DockerRuntime/ContainerItem/ImageItem/DockerGlobal dataclass + unavailable()/operational
- [x] T4 model_assets：ModelCacheState/HardwareAssessment/DownloadView/ModelAssetStatus dataclass（get_model_assets → list[ModelAssetStatus]）
- [x] T5 deps.py：DepsSnapshot 全强类型字段（python: list[PyPkgStatus]/tools_table/compiler: CompilerInfo/docker_global/models）+ InfraItem/DepsSummary/AgentDepsResponse/SharedInfraView + DepsService 类（缓存/构建/组装/失效一体）+ 泛型 _safe(fn: Callable[[], T], default: T) -> T；_compiler_fallback/_docker_fallback dict 工厂删除（改 CompilerInfo.unavailable()/DockerGlobal.unavailable()）
- [x] T6 ocr_service：OcrService 类（12 个模块级全局变量全部收编实例属性）+ OcrStatus dataclass；routes/ocr asdict
- [x] T7 scanner：ScanResult.global_ → GlobalResources 强类型 + ConfigStatusView（required_status → list，路由 keyed dict 保前端契约）；scan/models/docker 路由 asdict 序列化（JSON 契约零变化）
- [x] T8 测试断言属性化（test_control 9 处 + test/deps 4 处——业务结构变更导致的测试假设更新，非弱化）；evolve.md 规则 9（强类型+OOP 铁律，含合法例外边界：JSON 边界/定型 map/纯函数/CLI 过程）
- 验证：deps 20 + control 63 + 单元 54 + 集成 5 + TS 18 + envCheck 5 全绿；8 连击 86ms（沙箱无 Docker 路径）；OCR acquire×5 单飞/extract/force_release 行为复验通过；E2E JSON 契约（deps/scan/models/docker/config）全保

## 追加整改 12（白名单收口唯一清单——用户指出 detect_tools 职能错位 + 双表冗余）

- [x] detect_tools.py 删除 Python 包职能残留（pip_installable_packages/兼容 re-export 整段）——工具检测模块纯净
- [x] detect_py_deps.py：pip_installable_packages → one_click_installable()（语义即"唯一清单 installer=pip 且平台适用"；conda 特例 sage 天然排除）
- [x] routes/install.py：PIPPABLE_PACKAGES 双表删除，白名单 = one_click_installable() 实时计算；孤儿死条目清理（frida-tools/html2text 代码零引用+venv 未装+依赖页不显示；pillow 是清单内 PIL 的 pip 名重复）
- [x] scanner.py：detect_tools.scan_python_packages → detect_py_deps.scan 直连
- E2E：白名单 28 项=唯一清单；非白名单 400；回归 deps 20 + control 63 + 单元 54 + 集成 5 全绿

## 追加整改 13（sage 一键可装——用户指出 installer 字段不应切安装能力）

- 用户论点：安装全在服务端执行，服务端环境本就有 conda（venv 由它创建），"能否 pip 装"没有能力意义——installer 只该决定执行哪条命令
- [x] one_click_installable() 去掉 installer=="pip" 过滤 → 唯一清单全量（29 项，sage 纳入）
- [x] install.py 新增 _install_command(pip_name)：按清单 installer 字段分发（pip → venv pip install；conda → conda install -p <venv> -y <conda_name>）；超时 120s→1800s（conda 装 sage 是 GB 级）
- 验证：白名单 29 项含 sagemath-standard；命令分发单测（pymupdf→pip / sagemath-standard→conda install sage / 未知→None）；pip 路径真实安装成功；回归 20+63+54+5 全绿

## 追加整改 14（GET /api/install 端点删除——用户指出冗余）

- 论据：白名单=唯一清单后，前端依赖页数据源（scan 的 python_packages 含 pip_name/installer）已含答案，GET 端点纯冗余；实测零消费方（client.ts getPippable 是死方法）
- [x] GET /api/install（list_pippable）删除；client.ts getPippable 死方法删除
- [x] 顺带修真 bug：App.tsx pipInstallable/pipManual 的 installer==="pip" 过滤与后端全量可装语义漂移（sage 被错归"手动"）——pipManual 列表整体删除，conda 包纳入自动安装
- 验证：GET→405、POST 安装正常；tsc+vite build 过；deps 20 + control 63 全绿

## 追加整改 15（dev 模式 vite 自动拉起——用户重启后前端 404）

- 根因：CONTROL_FRONTEND_DEV=1 时前端由 vite dev server 服务，但 vite 依赖开发者手动启动，控制台/opencode 重启后无人拉起 → 5173 无监听
- [x] services/vite_dev.py：vite_running（端口文件+双栈探测+5173-5175 候选段扫描兜底）+ start_vite_dev（后台/独立进程组/cwd=frontend 目录）
- [x] server.py startup 事件挂 dev 分支自动拉起（幂等不抢占开发者手动实例）；dev 提示页补 url 字段
- 踩坑修复：cwd 曾错算为 node_modules（vite 起不来）；端口文件丢失时误判重复拉起（补候选段扫描）
- 验证：冷启动自愈/幂等跳过（进程数恒 1）/SIGKILL 残留自愈 三场景过；startup 序列实测拉起成功；前端 200
- 注：生产控制台（83880）仍是旧代码（无自动拉起）——本次已手动起 vite 兜底；下次 opencode 重启后新控制台自带该逻辑

## 追加整改 16（第一层 CLI 自举检查补齐——用户指出需求执行偏差）

- 用户原需求："chat.message 做完最基本的环境检查后调用控制台检查接口"——"最基本的环境检查"此前被偷换成 venv 存在性（一行 getPythonCmd），丢了缺包时主动提示 install.sh 的职责；detect_py_deps 的 CLI 入口（用户明确要求的 import/CLI 双入口）没被 plugin 使用
- [x] env-check.ts 两层串联：第一层 checkPyDepsViaCli（CLI 调 detect_py_deps.py scan --agent all；venv 缺/包缺 → install.sh 提示，不进第二层）→ 第二层 /api/deps（console_url 引导）
- [x] interpretScanExit 纯函数：exit 0 放行 / exit 1 提取 [-] 缺失行给 install.sh 提示 / 检测自身异常不拦（第二层权威）
- 验证：四纯函数场景 + 真实链路（全装 venv 放行）+ 真实负例（只装 fastapi 的 venv → 28 项缺失精确列出 + install.sh 引导）；envCheck 9 用例全过；deps 20 + control 63 + 单元 54 + TS 18 全绿

## 追加整改 17（checkDepsViaControl 参数 bug + sage 探测实测）

- bug：checkDepsViaControl 把 agent 名当 pythonCmd 传给 checkPyDepsViaCli → runProcess spawn "binary-analysis" 失败 → status=null → interpretScanExit 判"检测异常"放行 → 第一层被静默跳过（上轮只单测 checkPyDepsViaCli 直调，没测串联路径）
- [x] 签名改 checkDepsViaControl(agent, sessionID, pythonCmd)，preheatEnvCheck 传 getPythonCmd()
- sage 探测实测：CLI 场景 28 包中 27 个走 importlib.metadata 零子进程；仅 sage 特例子进程探测（find_spec 不执行模块代码）~11-30ms；完整 scan 总耗时 114ms，SCAN_TIMEOUT_MS=30000 为防御上限
- 验证：串联路径真实复验（正常 venv 放行 / 缺包 venv 精确 28 项缺失 + install.sh 引导）；deps 20 + envCheck 9 + TS 18 全绿

## 追加整改 18（sage 转 required + 第一层 fail-closed）

- 用户决策：sage 改为必须（外部改动未落盘，本次落实：required=False 删除、注释"conda 安装器（必需）"）
- [x] install 子命令接 conda 分支（sage 走 conda install -p venv -y sage，GB 级提示）；crypto-analysis.md/crypto-methodology.md 的 optional 措辞同步为必需；测试断言更新
- fail-closed 整改（用户追问"为什么静默跳过"暴露的设计缺陷）：interpretScanExit 原把 status=null（spawn 失败）当"检测工具异常→放行"——把"不知道"当"没问题"，调用方任何 bug（如传错 pythonCmd）都会无声跳过第一层。修复：status=null/异常码 → 拦截 + error 信息进消息（金标准复验：传错参数现在报"Executable not found: binary-analysis"而非静默放行）；error 字段从 runProcess 传递到 interpretScanExit 第三参数
- 回归：deps 19 + control 63 + envCheck 10 + TS 18 全绿

## 追加整改 19（四组清理：docs 更新/env_cache 删除/OCR extract bug/pyproject 删除）

- [x] docs 三文档过时机制描述更新（新机器配置指南 9 处含第 4 节重写；知识体系 4.2/4.3；介绍的工具拦截节）——detect_env/check-preinstall/env_cache 零残留
- [x] ~/bw-security-analysis/env_cache.json 删除（退役机制孤儿，零消费方）；web registry.json 保留（现役脚本注册表）
- [x] OCR 真机测试逮住并修复真 bug：routes/ocr.py 名字遮蔽（路由函数 extract 与 import 的方法 extract 同名 → 路由递归调自己 → TypeError 500）——OOP 化整改 11 埋的雷，当时复验漏了 extract 端点。修复后四端点全通（acquire ready/extract 中英+hex 正确/close 归零/reaper 30s 释放）；去空格渲染瑕疵为模型特性非 bug
- [x] mcp-servers 三个 pyproject.toml 删除：零代码消费（mcp-manager 注释宣称读 import_names 实为撒谎注释）、依赖安装收口 detect_py_deps 唯一清单（三个 server 声明的依赖清单全覆盖核实）、server 由 venv python 直跑不经 pip install。不换 requirements.txt（那只是死文档换格式）
- 回归：deps 19 + control 63 + 单元 54 + TS 18 全绿

## 追加整改 20（死 registry.json 清理——用户追问 registry 用途）

- 事实：registry.json 无任何运行时代码解析，唯一潜在消费者是 agent prompt——两种合法模式：binary（prompt 指引读 registry+templates.md，渐进式披露，活文件）；web（prompt 内建完整脚本表，registry 零引用=双轨漂移死文件）
- [x] web-analysis/scripts/registry.json 删除（prompt 208-215 行的表更详细，JSON 无人读）
- [x] mobile-analysis/scripts/registry.json 删除（prompt/knowledge-base 双确认零引用）+ README 树同步
- 保留：binary-analysis registry.json（prompt 明确指引消费，活链路）

## 追加整改 21（classify_scene 删除——语义判断归还 AI）

- 分析结论：classify_scene 是语义分类器（原始信号→场景标签→方案模板），但输入与 AI 读到的 initial.json 完全同源（脚本无私有信息优势）；规则窄（KMDF/minifilter/Qt 漏判→错误暗示 standard）+ 硬编码 5 个文档名=知识库索引第二入口（双轨地雷）+ 无反调试/VM 维度。计算/枚举归脚本（detect_packer 保留），语义/分类/方案选择归 AI
- [x] R1 _analysis.py 删 classify_scene（AST 精确定位 383-512 行）+ 头部注释条目
- [x] R2 initial_analysis.py 删调用/scene 输出字段/import；import_names 未使用改 _
- [x] R3 binary-analysis.md 阶段 A：场景判断归还 AI 的措辞
- [x] R4 analysis-planning.md：新增场景判断信号表（packed/crypto/gui/kernel_driver/standard 的原始信号描述，含 WDM/KMDF/minifilter、ChaCha 常量等语义级特征）；四模板进入条件改原始信号；场景组合措辞同步
- [x] R5 packer-handling.md 解壳后引导同步；全仓 classify_scene/scene_tags 零残留
- 验证：AST（剩余 5 函数/query.py 依赖完整/输出结构五信号保留）；deps 19 绿。idat 端到端留待真实分析任务（无 .i64 样本）

## 追加整改 22（initial_analysis 命令模板收口单一源）

- 用户问题：initial.json/log 语义 + 命令模板在各 agent 分布不一（binary 全文展开/mobile 引用/其他不涉及）
- 事实：templates.md 已是模板持有者（bash/PS 双份）——binary-analysis.md 阶段 A 的展开版是双轨（且已现 $AGENT_DIR vs $SHARED_DIR 路径漂移雏形）
- [x] binary-analysis.md 阶段 A 改引用式（"命令模板见 templates.md"），补 initial.json（数据）/initial.log（idat 日志，诊断用）语义
- [x] templates.md 初始分析节补：binary/mobile 共用（目标含 .so/.dylib）+ 两文件语义注释
- [x] web/crypto/ai 零引用保持（场景无二进制，写了反而误导）；mobile 引用式保持

## 追加整改 23（initial_analysis 输出自解释 + 双平台示例恢复 + 环境变量机制固化）

- [x] 输出自解释：initial.json 六个数据段全部带 description（用途+场景判断信号示例）——字段语义跟着数据走，改脚本一处即同步；idat 真机复验 description 全覆盖
- [x] binary-analysis.md 双平台示例恢复内联（用户裁定：阶段 A 高频流程应内联，读 templates 违反渐进式披露的正确方向）；路径 $AGENT_DIR→$SHARED_DIR 漂移修正；analysis-planning 引导改为指向自解释 description
- [x] 环境变量 vs 命令行实测裁定：-S 参数可传但仅 idc.ARGV 可取（sys.argv 实测拿不到）+ 外层引号占据后 $TASK_DIR 含空格无法转义 → 保留环境变量；机制理由固化到 templates.md 头部 + idapython-conventions.md 传参规范节（消"机制无文档"认知坑）

## 追加整改 24（三处收口收尾：行话人话化 / mobile 索引补强 / 判断表删除）

- [x] idapython-conventions："经 _base.env_str/env_int 读取"行话改人话（说明是 _base.py 的环境变量读取工具 + import 写法）
- [x] mobile-analysis：.so 分析节补"标准起手"指引（initial_analysis → description 判断场景 → analysis-planning 模板），索引补强不复制内容；不抽 agents-rules 片段（会把 IDA 内容注入 searcher/memorist 等所有 agent，污染面大）
- [x] analysis-planning.md 判断信号表 + 四处"进入信号"行全删——与 initial.json 的 description 重复（上一轮改一半的残留）；信号唯一源=description，文档只留场景→方案模板路由

## 追加整改 25（控制台进程页：受管进程可视化）

- 用户需求：活动监视器里两个 python 进程（3.65GB/1.35GB）查身份后，要求控制台标出后端启动的所有进程，引用计数/访问时间可见
- [x] 后端 ocr_service：新增 `mlx_pid()`（Popen 句柄优先，孤儿回退 pid 文件+psutil 验活）+ `holders()`（client_id 解析 pid，psutil 取 cmdline 识别持有者身份）+ HolderInfo dataclass
- [x] vite_dev：抽公共 `vite_port()`（端口文件优先，候选段探测兜底；process_registry 复用，不重复实现）
- [x] services/process_registry.py：ProcessInfo/ProcessRegistryView dataclass + collect_processes()（console/ocr_mlx/vite 三源汇总，psutil 读 RSS/cmdline）
- [x] routes/processes.py GET /api/processes + server.py 注册
- [x] 前端 ProcessSection.tsx（10s 自轮询；引用计数列 tooltip 显示持有者；行展开持有者明细表：PID/存活/最后心跳/命令行）+ types + api + App.tsx 页尾挂载
- 验证：后端语法全过 / tsc 零错误 / TestClient 端到端（三进程 keys 齐全）/ holders 链路模拟验证 / pytest 59 passed / 集成 5/5（pytest 报 test_integration 2 errors 是框架误收集自研装饰器，直接 python 跑 5/5 通过，原有现象非本次引入）
- 注意：生产控制台 9776 是旧代码，需重启后 /api/processes 才可用

## 追加整改 26（控制台自重启按钮——用户自助让新代码生效）

- 用户需求：控制台前后端加重启按钮，不再依赖手动 kill
- [x] services/restart.py：ConsoleRestarter 类（幂等调度锁 + POSIX execv / Windows helper 等待旧 PID 死亡再接管）
  - 关键陷阱（已解）：exec 不改 PID 的 start_time → 新实例 is_control_running() 会误判"已有实例"exit(2) → exec 前必须 delete_port_file()
  - MLX 子进程独立进程组不受影响，新实例经 pid 文件孤儿复用
- [x] routes/system.py POST /api/system/restart；health.py 加 BOOT_TOKEN（exec 下 PID/start_time 均不变，唯 token 必变，前端判定重启完成）+ /api/health 别名（vite dev 代理只转发 /api）
- [x] 前端：api.restartConsole + 顶栏 Popconfirm 按钮（PoweroffOutlined，重启中 spin+禁用）+ boot_token 轮询（2s 间隔，120s 超时）→ 完成后 refreshAll
- [x] 测试：test_control.py 新增 2 用例（调度幂等+路由契约 monkeypatch perform / boot_token 形态）；56/56
- [x] E2E 沙箱：spawn→POST restart→同 PID boot_token 翻转→/api/processes 新实例服务 ✓
- [x] 生产迁移：SIGTERM 旧实例(14888)→canonical spawner 拉起(50652)→**再用新代码的 restart 端点真机自重启一次**（同 PID 50652 token 3d34f5b4→000a90df）→模型重载完成 200
- 验证：tsc 零错误 / pytest 56 passed（1 error 为自研 test() 装饰器被误收集，既有现象）/ TS 18/18

## 追加整改 27（进程页内存口径对齐活动监视器）

- 用户反馈：进程页显示 1064MB，活动监视器同 PID 显示 3.62GB，差 3 倍+
- 根因：口径不同。活动监视器"内存"列 = phys_footprint（含压缩页 + GPU/Metal 映射）；
  psutil RSS 只算驻留未压缩页。BGE 走 MPS、GLM-OCR 走 MLX——模型权重在 Metal 缓冲区，
  RSS 完全看不见（footprint 分解实测：console 3034MB 在 IOAccelerator graphics 段）
- [x] process_registry：新增 `_footprint_mb()`（macOS 调 /usr/bin/footprint 解析 header，
  ~0.2s/进程）；ProcessInfo 加 memory_footprint_mb 字段；console/ocr_mlx 双口径都填
- [x] 前端：内存列主显 footprint（缺失回退 RSS），与 RSS 差异 >1MB 时 tooltip 解释两种口径
- [x] tsc 修一处 `}}` 手误；后端经重启端点生效（dogfood 自重启链路第二次真机验证）
- 终验：console footprint=3710.0MB (3.62GB) == 活动监视器截图数值 ✓；RSS=1077MB 并存展示
- 附带验证：OCR 75099 在截图 OCR 识图后被正确释放（孤儿复用→识图→引用清零→30s reaper），全生命周期闭环

## 追加整改 28（引用计数列说明 + vite PID 反查）

- [x] 引用计数列头加问号悬浮（OCR 持有者机制说明：acquire +1/close -1/归零 30s 释放/悬停数字看明细/仅 OCR 行有值）
- [x] vite PID：spawn 时未记录（独立进程组）→ process_registry 新增 `_pid_on_port()`（lsof -ti :port 反查监听进程；psutil net_connections 在 macOS 无 root 会 AccessDenied 故不用），vite 行补 PID/内存/命令行与 console/ocr 同等展示
- 验证：tsc 零错误；生产重启后 vite 行 pid=4640（与实际监听进程一致）mem=114MB；重启端点 dogfood 第三轮正常

## 追加整改 29（跨平台补缺 / vite 判活收口 / 模型分区改矩形块网格）

- Q1 进程实现跨平台审计：footprint 有 darwin 守卫（优雅回退 RSS）、restart/ocr 有 win32 分支；缺口 = _pid_on_port 用 lsof（Windows 无）→ 补 psutil.net_connections Windows 分支（该平台无需 admin；macOS 下 psutil 无 root 会 AccessDenied 故仍走 lsof）
- Q2 vite_running/vite_port 逻辑重复确认 → vite_running 委托 vite_port（判活单一源，删 12 行重复）
- Q3 模型分区重设计：删顶部缓存目录行（各模型块自带全量路径，悬浮可见）；按类型分组 + 组内两列矩形块；所有长文本（名称/用途/repo/路径/硬件说明）Typography ellipsis 截断 + 悬浮全量
- 验证：tsc 零错误 / 后端 56/56 / 重启 dogfood 第四轮 / vite HMR 服务新组件

## 追加整改 30（模型分区两列修复）

- 用户反馈：模型块右侧空白，仍一行一个
- 根因：上一版按"类型分组 + 组内两列"实现，但现状每类型各只有 1 个模型 → 每组独占一行、行内仅一块 → 右半永远空
- [x] 改全局单一两列网格（分组行删除；类型由块上彩色 Tag 标识）；3 模型 = 第一行两块、第二行一块
- 验证：tsc 零错误；vite 编译产物确认分组残留 0、md:12 在位

## 追加整改 31（Q&A：mlx_pid 读文件的设计依据 + _pid_on_port 平台策略补强）

- Q1 mlx_pid 读 pid 文件 = 孤儿收养交接协议（设计内，非缺陷）：控制台重启（execv/按钮）后 MLX 子进程独立进程组存活，
  _adopt_orphan 显式置 _subprocess=None（无 Popen 句柄）→ pid 文件是新旧控制台间唯一的 PID 交接通道；今天 75099（14888 spawn→50652 收养）全程实证
- Q2 psutil 即成熟库，但端口→PID 的全局连接表在 macOS 无 root 会 AccessDenied（实测）；改进 _pid_on_port：
  非 darwin 一律 psutil 优先（Windows 免 admin / Linux 经 /proc 同用户免 root），AccessDenied 才 lsof 兜底；macOS 直接 lsof

## 追加整改 32（用户重启后全链路真机复验）

- 用户操作：通过重启按钮重启了控制台（boot_token 706de69f）——第一次用户侧按钮重启，链路正常
- [x] 全链路真机复验（生产 50652）：
  - /api/processes 三行数据齐（console footprint=3703MB≈截图 3.62GB / vite pid=4640 经 lsof 分支 / OCR stopped）
  - OCR 完整闭环：acquire spawn（42558，有句柄路径，ref=1 holder 明细含命令行）→ 新 client 复用（无句柄→pid 文件路径，ref 正确）→ close（ref=0）→ 30s reaper 自动释放（stopped）——mlx_pid 两条路径 + 引用计数 + holders 全部实证

## 追加整改 33（plugin 写入收口到控制台，进行中）
- 需求文档: requirements/evolve/2026-08-17-plugin-writers-to-console.md
- [x] 步骤 1 memory_writer.py: MemoryEntry + MemoryWriterService（线程+队列+惰性 MemoryDB）；
      fake 注入验证落库（question 前缀/type/flow_id/向量行全对、非法条目跳过）；
      踩坑记录: fake encode 必须处理 str 输入返回 1D（SentenceTransformer 语义）；查询 vec0 表需 sqlite_vec.load

## 追加整改 33 完成（plugin 写入收口到控制台）

- 需求: requirements/evolve/2026-08-17-plugin-writers-to-console.md（7 步全部完成）
- [x] 控制台新增: services/memory_writer.py（线程+队列+MemoryDB）、services/event_writer.py（专用线程+独立事件循环+Graphiti）、
      routes/ingest.py（POST /api/memory/entry、/api/events/entry、/api/events/delete，入队即返 202）
- [x] plugin 改造: 删 daemon 管理全套 ~250 行（spawn/READY/暂存/背压/exit handler）；
      新增 postToControl（readControlPortFile 实时读端口 + fetch + AbortSignal.timeout(5s)）；
      fireAndForgetEvent/fireAndForgetMemory/deleteGraphitiEvents 语义不变（白名单/isRegisteredAgent/格式化文本保留）
- [x] 删除: write_event_daemon.py、memory_writer_daemon.py；db.py 注释更新；全仓 grep 零残留
- [x] 验证: 单测 59/59（+3 新例）、集成 5/5、bun 加载 OK、E2E 三链路真机（memory 2 行落库+真 embed 范数 1.0；
      events add → DeepSeek 提取 3 实体入 Neo4j；delete → 清零）；生产两轮重启（token 1ed0fe94 → 8209303f）
- 审计修复: sys.path insert(0)→append（曾遮蔽 backend server.py）；stop→start 可重用（清残留哨兵）；
  fetch 超时；memory/event 连接泄漏（重建前 close 旧连接）；墓碑注释清理
- 已知边界: 当前 opencode 会话的 plugin 仍是旧代码（旧 daemon 脚本已删 → existsSync 安全降级只记日志，不崩），
  用户重启 opencode 后新 postToControl 生效

## 追加整改 34 完成（knowledge/events 按 ocr 标杆终态收口）

- 需求: requirements/evolve/2026-08-17-mcp-ocr-standard-consolidation.md（11 步全部完成）
- [x] 移库 5 个: db.py→knowledge_db.py（embedder Protocol 化）、anonymizer.py、graphiti_config.py（.ai_env 路径修正+embed 直连 model_loader）、
      llm_client.py、reranker.py（直连 model_loader.get_reranker）
- [x] 新服务: knowledge_store.py（单 MemoryDB+队列写+3 同步方法）、event_store.py（单 Graphiti+专用线程/独立事件循环+读者线程喂单+
      跨循环桥 run_coroutine_threadsafe+5 搜索+Docker 惰性 ensure）；删除 memory_writer.py/event_writer.py
- [x] docker_manager 收编 ensure_daemon_blocking/ensure_neo4j_events_blocking；volumes 补 $DATA_DIR/db/events:/data
      （修复控制台手动启容器无卷的隐性 bug）；Docker CLI 唯一入口恢复
- [x] 路由: routes/knowledge.py（4 端点）+ routes/events.py（7 端点）；删 routes/ingest.py
- [x] 薄壳重写: knowledge/server.py（3 工具）/events/server.py（6 工具），签名/description 逐字保留，httpx 代理+端口自愈
- [x] 删除: mcp-servers/embed_client.py（HTTP 回环全消灭）；全仓引用清零
- [x] 验证: 单测 61/61（改名 3+新增 2）、集成 5/5、生产重启（token 8e7ced7f）、
      knowledge 壳 stdio 3 工具真链（store id=895 真embed+脱敏/search 命中/flow 隔离）、
      events 壳 stdio 4 工具真链（time_search 命中 7 节点含 DeepSeek 提取的 frida/objection 实体、
      entity_search(Tool)、episode_context、delete→Neo4j 清零）
- 审计修复: executor 阻塞 get 进程卡死→读者线程+call_soon_threadsafe；loop 就绪竞态→Event 屏障；
  EdgeSearchMethod.breadth_first_search 不存在（真实枚举 bfs——老 server 该工具从未跑通，顺带修复）；
  SearchResults pydantic 重建失败→原地过滤；未用 import 清理；pyflakes 全净
- 测试分层说明: entity_relationships_search/diverse_results_search 已在 service+route 层（fake）覆盖，
  未做真 Neo4j stdio E2E（需 center_node_uuid 链+DeepSeek 往返，性价比低）

## 追加整改 35（真 E2E 补全 + BFS 真 bug 修复 + 测试提速）

- 用户裁定: 不接受 fake/mock 级验证覆盖本轮大改；测试慢是真问题
- [x] 真 E2E 补全（真 Neo4j + 真 DeepSeek + stdio 壳全链）:
      写入 2 事件 → DeepSeek 提取 10 实体 → entity_search(Tool) 取真 center uuid →
      entity_relationships_search 真 BFS 二跳 → diverse_results_search 真 MMR+cross_encoder
- [x] 真 E2E 抓出并修复隐藏 bug: BFS 传 center_node_uuid 给 search_() 不生效——
      graphiti 的 BFS 只认 bfs_origin_node_uuids（列表），origin None → 恒空。
      老代码该工具从第一天起就返回空（AttributeError 修复只修了枚举名，参数层仍坏）。
      修复: 改传 bfs_origin_node_uuids=[uuid]; 真链验证 BFS 返回 3 条 DeepSeek 提取的真实关系边
      （HOOKS/CONNECTS_TO/BYPASSES）; 单测断言同步（禁 center 直传回归）
- [x] 测试提速: E2E 段共享控制台进程（get_shared_server 懒加载 + main 统一 stop），
      17 例改共享 / singleton 复用共享作第一进程 / 端口耗尽例先停共享（候选端口全覆盖需要）
- 效果: 全量 61 例 4-6min → 26.5s（~10 倍），61/61 全绿，集成 5/5
- 根因确认（用户判断正确）: 生产链路模型只加载一次（常驻进程），慢是测试架构每例起新进程重复加载 4.3GB

## 追加整改 36（用户裁定全量验证：真 E2E 全覆盖——一次性抓出 6 个真 bug）

用户: "都验证！还有什么没验证的全部验证！"——逐项执行结果:

### 抓出并修复的 6 个真 bug（全部真 E2E 暴露，fake 层不可见）
1. BFS center_node_uuid 不进 BFS 分支 → 改传 bfs_origin_node_uuids（整改 35 已记）
2. bolt 端口级就绪是假就绪（TCP 可连但握手无响应）→ 升级为 bolt 协议握手探测（20 字节 magic+版本）
3. 读路径无自愈（缓存 graphiti 实例在容器死后不失效）→ _search 失败 reset 重试一次（重试走完整 ensure 链）
4. docker ensure 的 status 采样时序 bug（拉 daemon 前采样恒 unknown → 误报 daemon 不可用）→ 拉起后重新采样
5. BRIDGE_TIMEOUT 180s 被 daemon 冷启动挤爆 + TimeoutError str 为空 → 600s + 可读化错误
6. torch/MPS 并发推理堆损坏 SIGABRT（8 并发 add_episode → 8 线程并发 encode → 崩溃报告实锤 nanov2_guard_corruption）
   → model_loader 推理串行锁（embed_sync/rerank_sync/embed_batch_sync），graphiti_config/reranker 全部走带锁方法

### 验证矩阵（全部真链路）
- plugin postToControl: searcher 子 agent bash probe → SQLite 落库命中（evolve 自身不写是设计：知识双轨分离）
- ocr MCP 壳: acquire → MLX 拉起 → 推理（本会话工具真调）
- MemoryDB 坏库重建: EXCLUSIVE 锁 → A 丢弃 → B 自动重建落库
- Graphiti 断连重连: docker restart 容器 → 写入 → 7 实体落库
- Docker 全分支: not_exists（rm 容器 → 8.7s 一次调用重建+握手+真数据）/ stopped（stop → 36s 自愈）；
  daemon 冷启动 open -a Docker 拉起验证过（ensure 链行为正确）；Docker Desktop 自身 quit/open 竞态僵死 4 次 = 外部产品缺陷（pkill 恢复），如实记录
- 端口自愈: 占 9776 → 控制台 fallback 9777 → 壳读端口文件跟随 → stdio 工具通
- 并发写入: 8 条并发（修复前 160s 零落库+进程 SIGABRT；修复后 10s 内 8/8 落库+存活）
- 终态: 61 单测（Docker 死环境也全绿——单测隔离修复）+ 5 集成 + 三壳 stdio + 6030 实体数据完整

### 单测隔离缺陷修复
event_store._ensure_graphiti 注入 factory 时跳过 docker ensure（此前单测隐式依赖真 Docker 活着）

### 附带产出
- 控制台崩溃恢复流程: 端口文件残留（指向死 PID）→ rm 端口文件 + canonical spawner 重拉
- pkill -9 docker 会损坏容器文件系统（RWLayer/conf 乱码）→ rm 容器让 ensure 重建即愈
