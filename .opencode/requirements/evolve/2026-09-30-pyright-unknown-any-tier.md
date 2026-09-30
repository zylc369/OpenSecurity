# 需求: pyright 三期——Unknown/Any 档打开（reportUnknown* + reportAny）

> 来源: 用户指令（2026-09-30）: "开 `reportUnknown*` 和 `reportAny`。你要防止改完后出问题，之前就是。"
> 前科（本需求安全设计的直接靶子）: pywin32 句柄 int() 化事故（CI run 36585667462）——
> 为消类型告警做运行时转换，破坏 PyHANDLE 对象生命周期 → GC 提前关句柄 → 管道全崩。
> 教训固化于 testing-blind-spot-patterns.md 模式 L / evolution-playbook"跨层修复"反模式。
> 关联: 2026-09-29-pyright-introduction.md（一期/二期）——本文件实施其"后续候选（未排期）"。

## §1 背景与目标

- 一期/二期已完成: bug 类清零（UndefinedVariable 20→0，抓 2 真 bug）、类型流清零
  （57+5+51→0，修 3 真隐患）、注解第一档（reportMissingParameterType=error）。
  Unknown/Any 族自一期起显式 none（当时实测 1400+）。
- **目标**: 打开 `reportUnknownParameterType` / `reportUnknownVariableType` /
  `reportUnknownArgumentType` / `reportUnknownMemberType` / `reportAny`
  （用户指定 5 条）; 顺带 `reportMissingTypeArgument`（同档、防新增 Unknown 于源头、
  产品码仅 97 条——如用户否决可单独摘除）。
- 实测基线（2026-09-30 临时配置，未动任何产品文件）: **总 1850 =
  tests 1017 + 产品码 833**（services 569 / routes 263 / server.py+mcp 1）。
  产品码 top: event_store 103 / model_loader 75 / routes-hardware 64 /
  detect_tools 56 / remote_client 56 / proxy_pool 50 / docker_manager 47。
- 环境: venv Python 3.13.15（注解语法无版本负担）。

## §2 技术方案

### 2.1 修复手法白名单（红线，违反即返工）

只允许**零运行时语义**的改动:
1. 注解（签名/变量/类属性; TypedDict/Protocol/类型别名定义）
2. `cast(T, x)`（运行时恒等返回）
3. 行级 `# pyright: ignore[规则]` + 原因注释
4. typing 相关 import / `from __future__ import annotations`
5. `object` 替代 Any（声明层收紧，要求下游 narrowing）

**禁止**: 任何表达式求值/控制流/返回值/实参变更——运行时转换构造（`int()`/`str()`/
`dict()`）、新增分支、资源对象包装（模式 L 铁律）。类型描述现实，不改造现实——
函数返回 dict 就注解 dict/TypedDict，**绝不**改成返回 dataclass（改返回类型 = 改消费方）。

**补强（B2 推演得出）**: 新增注解凡含类型下标（`X[...]`）一律用**字符串形式**
（`-> "subprocess.CompletedProcess[str]"`）——typeshed-only 泛型在运行时无
`__class_getitem__`，非字符串注解会在 def 执行时求值 → import 期 TypeError。
（例外: 文件有 `from __future__ import annotations` 时任何形式都惰性安全。）

**Any/数据结构政策 v2（2026-09-30 用户二次裁定，取代 TypedDict-first）**:
正确方向是**定义明确的模型替代 dict**（规则 9 的机械化）:
1. 内部数据流（我方构造的数据: 硬件规格/搜索结果/docker 清单/配置）→
   **dataclass 模型**——字段名=JSON 键名，FastAPI 原生序列化，API 形状不变;
2. JSON 解析边界（`json.loads`/`r.json()`/外部 JSON）→ **TypedDict 仅限该层**;
3. 真·透传（不检查内容）→ object / 单点 Any + 逐处论证。
v1 的"给 dict 贴类型标签"（`dict[str, Any]`/TypedDict-everywhere）判定为
**给债务上漆**——废止; B2c/B2d 的 dict 注解为过渡态，随各文件批次被模型
替代吸收。安全模型相应更新: 模型替代批次按"**API JSON 形状不变（或仅
加性变化，消费方按字段读取兼容）+ 调用点全迁移 + 全量回归**"验收——
"零运行时变更"白名单是 pywin32 创伤的过度泛化，仅适用于类型告警修复，
不适用于模型替代重构（后者是显式批准的设计变更）。
合法 Any 仅剩窄口: 子集转发（全类型库、ParamSpec 不可表达）等，逐处论证。

### 2.2 diff 机械审计（每批强制验证点）

对每批 `git diff` 新增行做白名单形态匹配（注解/cast/ignore/import/类定义行），
不匹配即验证失败——把"上次改坏"从纪律约束升级为机器保证。审计命令内联在各批
验证步骤中（不新增仓库文件）。

### 2.3 tests 策略

17 个测试文件**文件级豁免**（扩展二期 `reportMissingParameterType=false` 头部行，
追加 6 条规则）——动态 fake/monkeypatch/patch 场景是合理 Any 领域（二期先例）。
产品码（services/routes/server.py/mcp）全量执行，不豁免。

### 2.4 配置翻转放最后

修复期用临时配置（pyrightconfig.tier3.json，用后即删）计量; 全部落地并 0 报警后，
正式 `pyrightconfig.json` 才 none→error。中途仓库始终保持 0/0 绿线。

### 2.5 Windows 分支

mcp/产品码 nt 分支如涉改动的: 只用 cast/ignore（本地物理不可验证），验收标注
"待 CI 裁决"（windows-ipc 通道）。

## §3.1 实施批次（每批 ≤200 行; 验证点 = 临时配置 pyright 计数 + compile 全量
+ test_control 93/93 + diff 审计零违规; 执行中允许按实测细化追加子批）

- **B0**: 本需求文档落盘
- **B1**: tests 17 文件豁免扩展（预期: tests 范围新规则清零、产品码 833 不变）
- **B2**: 根因聚合①——`threading.Lock` Any 族（~46）/ `*args/**kwargs` 惯用法族
  （单例 `_create_fresh` 等）/ 未注解内部函数返回族（`_run_docker`/`_post_json` 等）
- **B3**: 裸 dict 返回族（routes/hardware.py 64 条大户 + 同型 `dict[Unknown,Unknown]`）
- **B4**: services/event_store.py（103）
- **B5**: model_loader（75）+ model_assets（18）
- **B6**: detect_tools（56）+ remote_client（56）
- **B7**: proxy_pool（50）+ docker_manager（47）
- **B8**: knowledge_db（17）+ knowledge_store（16）+ 其余 services/routes 零头
- **B-final**: 正式配置翻转（none→error）+ 全家族回归（test_control 93/93 + pytest 47
  + oop_singletons/remote_link/config_manager/model_lifecycle/integration）+
  生产 /health 验证 + pyright 文档三期补录 + pending-items #4 更新 + 提交建议

## §4 验收标准

- 功能: 正式配置下 basedpyright **0 error / 0 warning**（含新开规则，71+ 文件）;
  全量 test_control 93/93; 全家族测试绿。
- 回归: 全批次 diff 审计零违规; 生产控制台全程无损（/health、pid 不变）;
  涉 nt 分支处标注"待 CI"并随下次 push 裁决。
- 架构: 不新增仓库文件（除本文档）; 依赖方向不变; 规则 9 同向强化
  （裸 dict → TypedDict/类型参数）。

## §5 与现有文档关系

- pyright-introduction.md"后续候选（未排期）"→ 由本文件实施，完成后回写三期结果。
- pending-items.md #4 → 完成时补录三期闭环。

## 执行进度

- **B0 ✅（2026-09-30）**: 需求文档落盘。
- **B1 ✅（2026-09-30）**: tests 豁免扩展。实测 **16** 个文件带二期头部（非 17 口径），
  追加 6 规则。验证: diff 审计 0 违规（新增行全为 `# pyright:` 指令）; 控制字节 0;
  compile ✓; 临时配置复测 **1850→833**（tests 清零、产品码 833 不变）;
  全量 test_control **93/93**。
- **B2 ✅**: Lock 族 55 条清零。13 处 `__import__("threading").Lock()` 站点
  （10 文件）: 加 `"threading.Lock"` 注解（6 个无 threading import 的文件补
  TYPE_CHECKING 静态导入块）+ 行级 `ignore[reportAny]`。**探针裁决**: 注解只保
  下游收窄、压不住行内 Any; cast 包裹 RHS 无效（内部成员访问仍报）——行级
  ignore 是唯一保住表达式原样的零运行时修法。833→778; 审计 0; compile ✓; 93/93。
- **B2b ✅**: args/kwargs 族 12 条清零（7 个 def 行 ignore+原因: 测试注入透传 ×2 /
  graphiti 桥 ×1 / 外部库签名镜像 ×3 / 通用转发器 ×1）。778→766; 审计 0; 93/93。
- **B2c ✅**: 根因返回族清零——docker_manager **47→0**（`CompletedProcess[str]`
  + `list[dict[str, Any]]`，文件有 future import 故裸下标安全）; remote_client
  `_parse/_post/_put/_get` JSON 边界定型; routes/events 7 个 handler;
  event_store.empty_result。**实证: 嵌套 Any 注解（`dict[str, Any]`）不触发
  reportAny**（knowledge_db L178/191 无报警）——容器定型到此粒度即够。
  期间自伤一次: import 插入守卫写反 → `Any` 未定义 ×7 + 连锁（运行时无害——
  future 惰性注解，93/93 佐证; 但违反绿线），审计轮当场抓获并修复。
  766→**641**; 审计 0; compile ✓; 93/93 + oop 6/6 + remote_link 9/9 +
  config_manager 5/5。
- **B2d ✅（Any 回改第一批，TypedDict-first 政策落地）**: ① `_forward_call` →
  经典 ParamSpec（模块级 `_P`/`_R`——PEP 695 内联式被"名称引用契约"扫描器判
  裸名 → 改经典式，**守护不削弱**）; ② `_create_fresh` ×2 → 显式签名（行为
  等价重构 2 行，调用点全关键字兼容）; ③ knowledge_db Protocol 输入侧定型
  （`texts: "str|list[str]"`、`**kwargs: object`）; ④ remote_client
  embed/rerank → cast 定型——**pyright 抓到 B2c 一处真形状错配**（列表端点
  被我统一注成 dict，isinstance 守卫保留、cast 表达已验证形状）;
  ⑤ model_loader ignore 理由精炼为"子集转发"（object 转发给全类型库不可行
  的 48 条反证; ParamSpec 无法表达固定首参+转发其余——**合法 Any**）。
  **插曲（14:07）**: 并行会话缓冲区覆写抹掉 B2d 五文件（B1/B2/B2c 幸存）——
  用户停会话后按批次标记盘点、精确重放、md5 复核。终态: **635** /
  错误类 0 / 审计 0（1 条正则误报为白名单形态）/ 93/93。
- **B3 ✅（模型替代试点: routes/hardware，政策 v2 首个落地）**: dict 数据流
  → **6 个 dataclass**（CpuInfo/MemoryInfo/OsInfo/GpuInfo/HardwareInfo）+ 1 个
  解析边界 TypedDict（`_WinGpuEntry`，仅 PowerShell JSON 层）。macOS 解析器
  dict 增量构造 → 字段累积 + `_flush()`; `_infer_gpu_capabilities(gpu: GpuInfo)`
  属性化; 路由 `-> HardwareInfo`（FastAPI 原生序列化，字段名=JSON 键名）。
  **API 形状**: 全字段输出（含 null）——GPU 键集由"可变"变"恒定"属加性变化，
  消费方按字段读取兼容; `frequency_mhz: null` 显式保留。原实现两处行为
  零漂移保留（Windows 能力推断不含 vram 的历史怪癖、psutil svmem cast 恒等）。
  **验证**: hardware 64→**0**; 产品码 635→**570**; 非目标 error 级 0
  （监控升级: 从"6 目标规则"扩到"全部 error 级"，因 reportRedeclaration
  浮现暴露盲区）; 93/93（E2E /api/hardware 实跑 system_profiler 验证序列化）。
  **本批修复自伤 ×2**（升级后的监控逮到）: ① ParamSpec 签名承诺 kwargs 但
  体只转发 args（调用方传 kwargs 会被静默丢弃）→ 补 `**kwargs` 转发;
  ② 双 `gpus` 注解 reportRedeclaration → 去重。
- **B4 ✅（模型替代: event_store + graphiti_config + routes/events）**:
  - **graphiti 是全类型硬依赖**（py.typed ✓）——TYPE_CHECKING 导入真类型
    （Graphiti/SearchConfig/SearchFilters/SearchResults），无需手写 Protocol;
    工厂别名 `GraphitiFactoryResult: TypeAlias`（3 签名统一）。
  - **SearchPayload 模型族**（EdgePayload/NodePayload/EpisodePayload/SearchPayload
    dataclass）替代 dict 构造; `_results_payload(results: SearchResults)` 全类型;
    `_search` 由 `**kwargs: Any` 改显式参数（5 个调用点本就全关键字——调用体
    零改动）; `empty_result` 统一返回 SearchPayload; `_on_loop` 泛型化
    （`Coroutine[object, object, _T]`）; `_tasks: list[asyncio.Task[None]]`;
    `_ensure_graphiti -> Graphiti`; **Any import 整体移除**。
  - **enum 陷阱 ×2**: ① EpisodeType 是纯 Enum（非 str-enum）→ 响应模型若按
    枚举建模需运行时解析 → 改急切 `.value` 字符串化（JSON 逐字相同）;
    ② typeshed 的 `Enum.value: Any` → `_episode_source_value` 辅助 + cast。
  - graphiti_config: `CUSTOM_ENTITY_TYPES: dict[str, type[BaseModel]]` +
    `create_graphiti -> tuple[Graphiti | None, str | None]`。
  - routes/events: 7 handler 模型化返回（5 搜索 → SearchPayload; entry/delete
    → QueuedAck dataclass），Any import 移除。
  - **测试适配 1 处**（模型替代预期更新）: fake-graphiti 搜索测试下标访问
    → 属性访问; **HTTP E2E 断言 `r6.json()["edges"] == []` 原样通过**——
    模型序列化与旧 JSON 形状兼容的实证（加性键）。
  - 验证: event_store 96→**0** / graphiti_config 0 / routes/events 0;
    产品码 570→**463**; 非目标 error 0; **93/93**。
- **B5-B7/C1-C2 ✅（2026-09-30 下午连续批次）**: model_loader/model_assets
  （显式子集镜像替代 Any 转发——远端分支本就不用 kwargs、全仓调用方只用
  convert_to_numpy; EmbedArray/ScoreArray 精确数组别名; ST 未注解 **kwargs
  库级 ignore ×4）; knowledge 三件套（SearchHit/SearchKnowledgeResponse/
  StoreKnowledgeResponse 模型 + sqlite fetchall 边界 cast + _SeenEntry）;
  proxy_pool+routes/proxy+proxy_relay（_JuliangResponse/_PersistedState 边界
  TypedDict + ProxyPoolStatus/显式重建解析）; C1: health/ocr/system/docker/
  config_route 全模型化（ConfigMetaEntry; docker {{json .}} 真透传走
  JSONResponse 直通——**object 响应模型会在流阶段炸 pydantic 序列化**，
  连坐后续请求断连——教训入库）; C2: routes/remote 转发端点 JSONResponse
  统一 + remote_client probe 边界 TypedDict + 转发方法定型。
  **过程自伤 ×4 全部当场修复**: import 插入守卫反逻辑（Any 未定义 ×7）/
  装饰器偷窃 ×2（TypedDict 块插进 @dataclass 与类名之间——ModelCacheState、
  ModelFingerprint 先后变裸类）/ 脚本断言半途死致半状态（routes/remote
  头部缺失 → 24 测试挂 → 补齐恢复）。**纪律升级: 多段脚本必须先全段
  assert 预检再统一写盘**。
  累计: 833 → ~189 | 非目标 error 0（持续）| 每批 93/93。
- **B-final ✅（2026-09-30 全量收官）**:
  - **正式配置翻转**: backend + mcp 双 `pyrightconfig.json` 六规则
    none→error; 终态 **backend 0/0（71 文件）、mcp 0/0（5 文件）**。
  - **前端**: `tsc --noEmit` 0 error（strict 模式）+ 全仓显式 any = **0 处**
    （侦察即达标的存量质量，未动代码）。
  - **全家族回归全绿**: test_control 93/93 + proxy_mcp 2 + proxy_pool 25 +
    proxy_relay 13 + proxy_routes 20 + oop 6 + remote_link 9 + config_manager 5 +
    model_lifecycle 14 + integration 6 + api_guard 4 + remote_client 8 +
    remote_routes 5。
  - **tests 侧暴露并修复 104 处**（临时计量曾把 tests 整体过滤——盲区;
    翻正式配置后才现形）: isinstance 真断言收窄 ×2（helper 断言不触发
    窄化）、模型属性访问 ×N、`db_path: str|Path` 放宽（**类型描述现实**
    ——服务实际接受 Path，我的显式签名过窄）、FakeGraphiti 工厂 cast、
    relay 测试 stub 模型化（ProxyPoolStatus 零值默认化以支持 stub 构造）。
  - **生产事件**: 控制台进程在战役中途死亡（非代码问题）→ 手动拉起
    pid 88758/boot_token ca8d5aa9，proxy_mcp 随即转绿。
  - **教训沉淀（新增 2 条）**: ① 临时计量的过滤条件会成为盲区——终验必须
    以**正式配置全量跑**为准; ② 任何 import/插入操作后立即 compile+import
    冒烟（本战役装饰器偷窃 ×2、future 位置错位、typing import 漏加、
    盲替换毁别名——全部被现场抓获，但每次都消耗了回合）。

## 终态总账

| 范围 | 起点（六规则临时开启） | 终态（正式配置） |
|---|---|---|
| backend 产品码 | 833 | **0** |
| backend tests | 1017（豁免后 0） | 0（含 104 处非目标规则修复） |
| mcp-servers | 81（正确环境下） | **0** |
| 前端 | — | tsc strict 0 error / any 0 处 |

**Any 例外终审清单（全部带 ignore+理由注释在代码内）**: ① ST
encode/predict 的库级未注解 **kwargs（方法类型部分未知，ignore ×4）;
② numpy stub 保守点（tolist/__iter__ ×3）; ③ typeshed 设计性 Any
（Enum.value、int.__pow__、urlopen、Popen.stdout、socket accept 元组、
psutil svmem 字段——均 cast/ignore 收口）; ④ pywin32 stub 不精确
（Windows-only 分支，标"CI 裁决"）×8。**显式 `Any` 残留（产品码）**:
remote_client `_parse/_post_json -> dict[str, Any]` 一族 transit 声明
（下游全定型，此为 httpx json() 边界的过渡形态——待后续按端点
TypedDict 化，列为未完事项）。

### 终验补强（2026-09-30 用户质询"测试完成了吗"）

- **两个真链路套件补跑（战役中首次）**:
  - `test_e2e_real`（真 Docker+DeepSeek+Neo4j，壳→控制台→图库全链）:
    **6/6 通过**（knowledge 脱敏检索 / events 提取搜索删除 / 容器自愈 /
    并发写 / 坏库重建 / ocr 懒加载卸载重载）。
  - `test_e2e_remote`（主控+节点双进程真模型）: **全部通过**（远程切换/
    三模型远程链路/降级 fallback/恢复卸载）。
  - **修复存量测试基建缺陷**: e2e_real 的壳 spawn 未镜像生产 spawn 契约
    （缺 `PYTHONPATH=mcp-servers` + `OPENSECURITY_CONTROL_IPC` 注入——
    MCP SDK 子进程环境默认过滤不继承）→ 壳启动即死"壳无输出"。修复=
    在 StdioServerParameters 显式注入两键（自持化）。非本次改造引起
    （壳 diff 仅类型行；生产由 mcp-manager environment 字段注入）。
- **断言审计**: 全战役 tests 改动 21 删/21 增断言行，逐条核对=访问方式
  等价替换（下标→属性）×19 + 语义增强（assert_true→真 assert 以触发
  isinstance 收窄）×2。**零断言丢失、零弱化**。
- **测试盲区终审（3 项结构性，供后续决策）**:
  1. pyright 未进 CI——0/0 门禁目前靠人工跑（建议加 workflow：backend+mcp
     双 0/0 + Any 清单 grep 白名单）;
  2. API 形状无系统性快照对比（局部 E2E 断言，治标）;
  3. 前端零运行时测试设施（仅 tsc+build）。

### CI 门禁与前端测试（2026-09-30，用户批准 #1/#3）

- **`.github/workflows/type-check.yml`**（push/PR 自动触发，path 过滤）:
  - `pyright` job: ubuntu + **钉版依赖**（与本地 venv 逐版本一致——
    无依赖时 fastapi 等全 Unknown 会炸数百假 error，实测 567）+
    basedpyright@1.39.9 → backend 0/0 + mcp 0/0 双门禁;
  - `frontend` job: node 22 + npm ci + `tsc --noEmit` + `vitest run`。
- **CI 环境平价验证（本地完整预演）**: 独立 venv 安装钉版清单 +
  `basedpyright --pythonpath` 双 scope 复跑——**与本地同归 0 error**。
  期间排掉两类环境差异:
  ① 版本漂移（anthropic 0.125→1.9 / mcp 1.29→2.2 大版本类型面变化
    → 钉版解决; mcp 2.x 甚至改名 FastMCP 导入）;
  ② Apple-only mlx_vlm（Linux 无法安装）→ 最小 Protocol
    （`_MlxModelLike`/`_MlxGenerateFn`/`_MlxGenResult`）+ cast 收口，
    **双环境确定性 0/0**（不再依赖 mlx 是否安装）。
- **前端 vitest 套件**（30 用例, node 环境零 DOM 依赖）:
  - `format.test.ts`（时长/相对时间边界——含发现: relTime 文档称"未来→—"
    但实现钳制为 "0 秒前"，测试固化实际行为并注释）;
  - `client.test.ts`（vi.mock axios: URL 编码/payload/params/错误映射;
    fetch stub: SSE 跨 chunk 分帧/abort/错误前缀）;
  - `readiness.test.ts`（computeReadiness 纯化抽取: 跨 agent 去重/skipped
    计 ok/缺失名/空输入/顺序契约/总计对账）;
  - 配套: `computeReadiness` 从 useReadiness 抽为纯函数（hook 薄包装）;
    vitest@3（vite5 配套——vitest5 需 vite≥6 的 peer 冲突已绕）。
- **待用户**: commit + push 后 GitHub 首跑双 job（预期全绿——
  本地已完整预演）。
