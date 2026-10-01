# progress — 权限询问超时自动拒绝（2026-09-30）

需求文档: 2026-09-30-permission-ask-timeout.md（同目录）

## Phase 记录

- [x] Phase 2 需求文档成稿（零来源叙事检查: 通过）
- [x] Phase 3 审计 3 轮（2 修 + 1 纯），7 问题全修：
  - 轮 1: reject 异步异常兜底未明确 / 类型列表中文逗号容错 / 步骤验证命令不具体 /
    步骤 2 接近 200 行拆分（2a+2b）
  - 轮 2: harness 沙箱前缀（日志防污染）/ 步骤 7 依赖漏 3 / test_control 跑法明确化
  - 纯审计: 零问题
- [x] Phase 4 执行计划确认（架构影响图见下；检查无遗漏步骤、无步骤合并/删除）
- [x] Phase 4.5 跳过：本需求不触碰任何 agent prompt（插件/后端/知识/需求文档）;
  新文件均落在既有目录模式内（plugins/lib、plugins/tests）
- [ ] Phase 5 步骤 1-7
- [ ] Phase 6 实现审计

## 平台实证记录（前置调研，全部实测）

- `permission.ask` plugin hook 未接线（静态: vendor dev 全仓库仅类型定义无触发点;
  实测: hook 无调用日志）——官方文档有但实现无，勿踩坑
- 插件 `event` hook 收 `permission.asked`/`permission.replied` ✓
  （字段: id/sessionID/permission/patterns/metadata/always/tool）
- `POST /permission/{requestID}/reply` body `{reply:"reject", message}` → 200 `true`;
  message 生成 CorrectedError.feedback 随工具错误送达模型; 模型继续执行不终止
  （实测: 模型 reasoning 引用 feedback 文案; 随后尝试 bash 被拒后合理收尾）
- v1 SDK 注入 client: `permission.reply` = undefined;
  `postSessionIdPermissionsPermissionId` = function（body `{response}` 无 message）
- 用户二进制 1.18.32 含 `/permission/{requestID}/reply` 端点（strings 确认）
- bash 工具 external_directory 检查只扫命令行静态路径（脚本文件内部不扫）——
  反馈文案"写 Python 脚本再运行"机制上可走通
- 证据: /var/folders/sk/rm7bl2ks67g7n849g_bsh0nw0000gn/T/opencode/perm-e2e/
  {hook-evidence.log, hook2-evidence.log, msgs.json, msgs2.json}

## 架构影响图（>3 文件，Phase 4 要求）

```
control/backend/services/config_manager.py [改] Keys+2 / extra_configs+2（BEHAVIOR）
  │                                              ←─ .ai_env 唯一权威（机制不动）
  ├─→ tests/test_config_manager.py        [改] 新键断言
  └─→ tests/test_control.py               [改] E2E meta 新键断言

plugins/lib/constants.ts                  [改] +6 常量（键名/默认值/反馈文案）
  └─→ plugins/lib/permission-timeout.ts   [新] manager（提取/配置读取/三级拒绝通道）
        ├─→ plugins/security-analysis.ts  [改] 接线（event 分支双事件名 + dispose）
        │      └─→ security-analysis-evolve/knowledge-base/architecture-map.md [改] hooks 表
        └─→ plugins/tests/test-permission-timeout.ts [新] harness（驱动真实 manager）

知识沉淀（Phase 5 步骤 6）:
  binary-analysis/knowledge-base/opencode-plugin-api.md   [改] 权限事件与自动回复
  security-analysis-evolve/knowledge-base/opencode-references.md [改] 平台行为实证

不动: config_route.py（声明键自动纳入校验）/ 前端全部（meta 驱动）/
      GET /api/config / .ai_env 模板 / 现有 hooks 行为 / mcp-servers
依赖方向: permission-timeout.ts → {context, logging, control-config, constants}
          （叶子/平级，无反向 import 主插件——无循环）
```

## 步骤执行记录

- **步骤 1** ✅ 后端配置声明 + 测试断言
  - 改动: config_manager.py（Keys+2 / extra_configs+2）;
    test_config_manager.py（新键声明/默认值/behavior 分类断言）;
    test_control.py（E2E meta 存在性列表+behavior 断言）
  - 验证: compile ✓ + pyright 0/0 + test_config_manager 5/5 + test_control 94/94 全绿
- **步骤 2a** ✅ 插件常量（constants.ts）
  - 改动: +5 常量（键名×2 / 默认值×2 / 反馈文案）
  - 验证: bun 导入冒烟 ✓（五常量导出值正确）
- **步骤 2b** ✅ 新模块 lib/permission-timeout.ts
  - 改动: 新文件（提取/配置读取/manager/三级通道/异常兜底; ~230 行含注释）
  - 验证: bun 导入冒烟 ✓（四导出齐全）+ bun build 转译 ✓
- **步骤 3** ✅ security-analysis.ts 接线 + 架构地图同步
  - 改动: import / 实例化（input.serverUrl）/ event 分支（双事件名）/
    dispose（行 1432/1435/1582）; 架构地图 hooks 表 +dispose 行
  - 验证: 插件模块加载 ✓ + grep 断言三处调用 ✓ + 架构地图核对 ✓
- **步骤 4** ✅ 插件单元测试 harness（tests/test-permission-timeout.ts）
  - 10 用例全绿: 提取（v1/v2/缺字段）/ 配置读取（默认/0/非法/中文逗号）/
    超时→HTTP 带反馈 / 类型过滤 / 0=关闭 / onReplied 清理 / dispose 清理 /
    SDK 兜底通道 / 通道①探测优先
  - 实施中发现并修复: ①harness mock sessionManager 缺 get——debugLog 路由
    抛 TypeError（生产无此问题; mock 覆盖 debugLog 依赖面后修复）
    ②用例失败时 dispose 未执行致跨用例污染——test() 加 finally 统一清理
  - 观察项（不在本需求修）: logging.ts 的 getAgentName 调用位于 writeLog
    try/catch 之外——mock/异常 ctx 环境下 debugLog 会抛（生产 ctx 恒有效，
    无实际影响）; 记此备查
- **步骤 5** ✅ 端到端集成验证（真实 opencode server + 真实模块 import）
  - 测试插件 import 真实 lib/permission-timeout.ts（绝对路径）+ ctx 注入 +
    configReader 注入 3 秒超时; 起 serve 触发外部目录 read
  - 断言全过: 已布防（真实 manager）/ 3 秒后通道② HTTP 拒绝（4 次一致）/
    工具错误含反馈文案 / 模型继续执行（4 次工具尝试）/ 无死循环（合理放弃收尾）/
    会话未终止
  - 环境说明: 测试项目无"临时文件放置"提示与 allow 白名单，模型写脚本选了
    外部路径被拒——机制正确（测试项目 allow 列表外）; 真实环境有
    tmpdir/opencode 预放行 + 项目内可写，脚本路径更顺畅
  - 证据: perm-e2e/{hook3-evidence.log, manager-evidence.log, msgs3-evidence.json}
- **步骤 6** ✅ 知识沉淀
  - 改动: opencode-plugin-api.md（权限事件与自动回复节; 字段对照/端点表/
    feedback 机制/HTTP 要点/未接线警告）; opencode-references.md（自动处理路径 +
    v1/v2 双轨对照 + bash 扫描边界 + CLI run 行为）
  - 验证: 零来源叙事 grep 清零（两误报为文件名/技术术语）; 不可见字节 0;
    自包含复核 ✓; 同类排查（internal-pentest 的 permission 为 Windows 服务权限
    语境，无冲突）✓
- **步骤 7** ✅ 全量终验 + 收尾
  - pyright backend 0/0; test_config_manager 5/5; test_control 94/94;
    harness 10/10（全部重跑）
  - 端到端免重跑判定: 步骤 6-7 仅改知识库 .md（不涉运行时），步骤 5 结果有效
  - 需求文档/progress 状态收口

## Phase 6 实现审计记录

- 第 1 轮: 8 维度全查——0 修复（2 项判定为非问题: ①rejectViaHttp 无 fetch
  超时——本地 server 为内存操作，不可达时 ECONNREFUSED 立即抛，无实际挂起
  场景; ②logging.ts getAgentName 在 try/catch 外——生产 ctx 恒有效，已记观察项）
- 第 2 轮: 0 修复（多实例/多 directory 隔离、旧版 serverUrl 缺失降级、
  配置键名逐一对照、文案标点一致性——均 ✓）
- 纯审计轮: 发现 1 问题（知识库版本表述"1.18.x 现行版"模糊，违反版本边界
  可操作性要求）→ 修复为"1.18.32 与 dev 最新版均无"（两文件各一处）
- 复核纯审计: 零问题 → Phase 6 通过

## 后置轮: 拒绝请求收口重构（2026-09-30，用户评审驱动）

- 问题: PermissionTimeoutManager 构造传 serverUrl + 裸 fetch——绕开了体系
  "到 opencode server 的请求统一走 ctx.client"的收口（对照: 到控制台统一走
  controlFetch; 现有插件对 opencode server 的请求全走 ctx.client，裸 fetch 是唯一例外）
- 方案验证（perm-e2e 实测）: client._client 为 hey-api 底层面
  （post/get/request/buildUrl/getConfig/interceptors...）; getConfig() 确认
  baseUrl 由 client 自持; `_client.post({url, body})` 调 /permission/{id}/reply
  带 message → 200 true
- 重构: 构造函数去 serverUrl 参数; rejectViaHttp → rejectViaClientRaw
  （ctx.client._client.post）; 手动 Basic auth 逻辑删除
- 验证: harness 重写为 mock _client.post 断言（11/11，含新增"404 不降级"用例）+
  主插件加载冒烟 + 端到端（布防→通道② client._client.post→feedback 送达工具错误，
  证据: 生产日志 per_0f2c3552 布防/拒绝两行 + hook5.log 事件流 + session 消息
  工具错误含文案）+ serverUrl/OPENCODE_SERVER_PASSWORD/rejectViaHttp 残留 grep 清零
- 知识同步: opencode-plugin-api.md 新增"未生成端点的统一调用方式"节
  （client._client.post; 禁止插件裸 fetch opencode server）; 需求文档 §2.3/§2.4
  修订 + 后置修订小节
- 小教训: 端到端测试 serve 启动漏带 OPENSECURITY_HOME 沙箱前缀 → manager 日志
  写入生产日志两行（无害，已确认; 后续测试命令固定带沙箱前缀）

## 后置轮: 配置排序权威化 + 异常防御收口（2026-09-30，用户双问驱动）

**问题 1（配置不相邻）**: 组内排序用 `label.localeCompare`——中文 locale 按拼音重排
（"超时…"chāo 排最前/"权限…"quán 排最后），且跨机器随客户端 locale 漂移不可复现。
- 方案裁定: 不新增 order 字段——组内顺序改 **服务端声明序**（entries 键序），
  与分类顺序（categories 数组序）同源权威; 后端 `_all_fields` docstring 固化
  "声明顺序=展示顺序、同类相邻声明即相邻展示、required 清单先拼接天然在前"约定
- 改动: configGrouping.ts 删本地 sort + 注释; configGrouping.test.ts 排序用例
  改声明序断言; config_manager.py `_all_fields` 顺序约定注释
- 验证: tsc 0 + vitest 41/41

**问题 2（异常面盘点）**: 逐调用点矩阵分析——
- onAsked/onReplied 的 props 属性访问: props 为 null 时抛 TypeError → 位于
  event hook 开头，异常会跳过同次事件的 session 管理处理 → **已修**（入口防御
  + extractPermissionAskInfo optional chaining）
- debugLog 路由层: getAgentName 在 writeLog try/catch 之外，异常 ctx 下抛
  （event hook 内抛=跳过后续; reject 的 catch 内抛=unhandled rejection）→
  **已修**（debugLog 主体兜底 + DEFAULT_LOG 回退，日志层"绝不抛"契约落注释）
- reject 通道链: 各级 try/catch 完备（harness 5xx/网络异常/通道①异常用例锁定）
- dispose: opencode finalizer 自带 catch+ignore，无后果; getCachedConfig 同步
  路径不抛
- harness 新增 2 契约用例（props null 不抛 / 异常 ctx 布防不抛）: 17/17
- 验证: harness 17/17 + 后端 compile/pyright 0/0 + 主插件加载冒烟（logging.ts
  全插件依赖链验证）

## 后置轮: 测试覆盖增强（2026-09-30，用户覆盖度审视驱动）

- 覆盖矩阵盘点发现 7 处缺口，全部补齐（11 用例 → 15 用例，断言 30 → 42）:
  通道② 5xx 降级③ / 通道②网络异常降级③ / 通道①异常落② /
  同 requestID 重复布防幂等 / 类型列表空项·项内空格·纯逗号（空集）·大小写敏感 /
  小数秒·首尾空格·Infinity 回退
- 验证: harness 15/15 全绿
- 有意不测（替代覆盖）: ①主插件接线运行时（加载冒烟+grep 替代——完整加载需
  control 环境; 真实使用即验证）②用户点击与超时竞态端到端（单元层已覆盖
  onReplied 清理）③v2 事件真实流（当前 opencode 不发 permission.v2.*，
  提取函数已按 v2 形态单元验证; v2 接管后自然验证）

## 后置轮: 默认值单一来源改造（2026-09-30，用户三点裁定驱动）

裁定: ①反馈文案改 shell/bat/Python（跨平台脚本表述）②默认值唯一权威在服务端
——GET /api/config 返回生效值（配置值优先，空/缺失回退声明默认），插件零默认
副本，取不到生效值即不启用（fail-safe）+ 排查日志 ③反思/续传开关的"未配置=
开启"语义上收服务端（default_value="1"）

- 后端: ConfigManager.effective_all()（配置值优先/空回退默认/无默认不出现/
  手写键保留）; GET /api/config 数据源切换; RESUME/REFLECT 开关键补
  default_value="1" + hint 更新（"未配置=开启"→"默认开启"）
- 前端: doSave 改 dirty 提交（dirtyUpdates 纯函数）——值接口返回生效值后
  全量回传会把默认值冻结进 .ai_env（服务端后续调默认不再跟随），改为只提交
  变化键（trim 后比较，改回默认同值不写盘）
- 插件: constants 删 3 个默认值常量（PERMISSION_TIMEOUT_DEFAULT_SEC/TYPES、
  REFLECT_NUDGE_DEFAULT_INTERVAL_MIN）; permission-timeout 缺失/非法→不启用+
  日志; reflection 开关/间隔 fail-safe（忙通道高频路径 once 节流日志，间隔
  缺失→Infinity 永不到期两通道不注入）; persistence resume 开关 fail-safe
- 测试: test_config_manager +effective_all 用例（6/6）; test_control E2E
  GET 生效值断言（94/94）; configGrouping +dirtyUpdates 用例（tsc 0 +
  vitest 42/42）; harness 语义更新 + makeManager 模拟 effective 提供语义
  （17/17）; 插件加载冒烟 + 被删常量残留 grep CLEAN
- 实施 note: 上轮对 constants.ts 的两处编辑未持久化（本轮重做时发现文件为
  旧状态，原因不明）——此后编辑关键文件后即时 grep 验证落盘为固定动作
- 覆盖补齐（用户充分性审视驱动，3 缺口全修）:
  ① reflection fail-safe 零测试 → isReflectEnabled/getReflectIntervalMs 加
  configReader 注入点（默认参生产零影响）+ 新建 tests/test-reflection-config.ts
  （开关三态/间隔 Infinity 语义，2/2）
  ② tunables 声明默认融合无断言 → effective_all 用例补 JULIANG/REMOTE 调参
  默认融合断言
  ③ path 型默认值归一化缺口 → effective_all 对 default 走同规 expanduser+
  abspath（当前无 path+default 组合，防御未来声明）
- 终验: 后端 6/6 + reflection 2/2 + harness 17/17 + 插件加载 ✓

## 后置轮: 独立代码评审修复（2026-09-30，review 子代理驱动）

评审发现 4 问题全修复:
1. **[中] PUT/DELETE 响应仍为原始值**——GET 切生效值后契约分裂: 保存响应
   覆盖前端基线 → 默认值字段瞬间空白 → 用户填回再保存 = 默认值冻结进
   .ai_env（复活本次要防的问题）。修复: PUT×2/DELETE 响应统一
   effective_all()（值接口全路由同契约）; E2E 补 PUT 响应生效值断言
2. **[低] effective_all 两循环 path 归一化不对称**（存在但空 vs 不存在
   两条回退路径默认值处理不同）→ 默认回退收口 default_of 单点
3. **[低] "0" 被日志记为"非法"**（0 是文档化关闭语义）→ 0 静默关闭不打
   异常告警; 负数才记非法
4. **[低] ConfigPage dirty（未 trim）与 dirtyUpdates（trim）口径不一**——
   纯空格编辑亮按钮但点保存提示无修改 → dirty 改基于 dirtyUpdates 计算

评审确认的两个有意行为变更（已在后置修订 2 记录）: 插件在控制台不可达时
fail-safe 自禁用（带日志）; GET 不再返回空值键。
终验: 后端 6/6 + 94/94 + pyright 0/0 · 前端 tsc 0 + 42/42 · 插件 17/17 + 2/2 + 加载 ✓

## 后置轮: 配置管理统一重构（2026-09-30，用户蓝图驱动，两轮纠偏）

用户裁定（蓝图）: 配置获取逻辑收口极差需重构——
① get_all 实为 .ai_env 加载 → 私有 `_load_from_ai_env`（path 归一化覆盖全部声明字段），
   不再对外
② 场景归属是 ConfigField 的数据（surfaces **数组**，一键可多场景），不是清单函数的
   硬编码——删除 required/extra/remote_link/node_side/三组 tunables 六个清单方法与
   _tunable_field/_all_fields，收口为类体静态 `_FIELDS` 列表（唯一声明来源，顺序=
   展示顺序，tunables 默认与 dataclass 同源生成）
③ 统一获取函数 `get_entries(surfaces)` → 新建**扁平领域模型 ConfigEntry**
   （用户二次纠偏: 删 raw/default_value/source/validator——调用方只消费最终 value，
   不做任何计算; validator 收进构建层: 配置值非法→记日志+回落声明默认）
④ 对外 KV 统一 `get_kv_list(surfaces)`（场景必填）; **全部配置接口场景轴统一**:
   GET 值接口/required-status 的 surface 必填（缺省 422），PUT×2/DELETE 响应=该场景
   KV（与 GET 同契约），单键 GET 接口删除（零消费）; meta 从领域模型组装并内嵌
   value（DTO 保留 default_value 供前端展示，删零消费的 source）

- 全量消费方同步: 前端 client/hooks（getConfig/getRequiredStatus 带 surface，
  useAllConfig 数据源按场景）· 插件 control-config（?surface=config）·
  proxy_pool · scanner（required_status 方法引用改 lambda——pyright 抓到的
  真实运行时破坏）
- 测试: 后端 6/6（+场景隔离/validator 回落/手写键合成断言）+ E2E 93/93
  （单键用例随接口删除，GET/required-status 全部带 surface）+ pyright 0/0;
  前端 tsc 0 + 42/42; 插件加载 ✓
- 行为变化记录: ① banner 不再展示 validator 细节（非法值→日志+回落，
  banner 只提醒缺失）② 值接口不返回跨场景全量/空值键
- 重构: 重启完成改整页刷新（用户评审: 逐 hook 刷新是枚举式维护, 漏 system
  即证; 重启低频重操作, reload 必然全量对齐）——doRestart 成功分支改为
  sessionStorage 标记 + window.location.reload(); 新页面初始化消费标记显示
  "重启完成"toast; 删除 console:restarted 事件广播与 ConfigPage/RemoteSection
  监听（reload 后无意义）; refreshAll 保留服务手动刷新按钮（轻操作, 含
  system.refresh）。tsc 0 + 44/44 + build ✓
- 修复: 重启后“后端代码已更新”提醒不消失（用户实测发现）——codeStale 来自
  useSystem（/api/system 的 code_stale = 启动冻结代码指纹 vs 当前指纹），
  而 refreshAll 只刷 scan/models/required 且 useSystem 无 refresh 方法 →
  自动刷新够不到，F5 全页重载才能清。修: useSystem 补 refresh（标准模式）
  + refreshAll 纳入 system.refresh（hardware 不随重启变化有意不刷——注释
  说明）; 同类排查: 运行状态页无此缺口（ProcessSection 10s 自轮询;
  OpencodeSection 吃 system prop）。tsc 0 + 44/44 + build ✓
- 控制台重启成功后前端全量刷新（用户驱动）: refreshAll 原本只覆盖 App 级
  hooks（scan/models/required），配置页/远程页的数据 hooks 在子组件内
  触达不到——doRestart 成功分支追加广播 CustomEvent("console:restarted")，
  ConfigPage/RemoteSection 监听后刷新 meta+生效值（useConfigMeta 补 refresh
  方法与 useAllConfig 对齐; 未保存表单编辑保留——刷新仅更新数据源）。
  tsc 0 + 44/44 + build ✓
- ConfigField 全字段必填（用户裁定: 声明不允许隐式默认值）: dataclass 删
  全部字段默认值，_FIELDS 34 条声明逐条显式补全 10 个字段（脚本转换 +
  字符串续行误补逗号修复; 完整性程序化抽查 34/34）——每条声明都是完整
  的可审计/review 对象。终验: pyright 0/0 + 后端 9/9 + 93/93 + 前端
  44/44 + 插件 17/17 + 2/2 + test-control 11/11（单飞用例沙箱残留复跑
  过）+ 加载 ✓
- 未声明键禁入（用户裁定: 声明是配置存在的前提）: get_entries 删手写键
  合成循环——.ai_env 中 _FIELDS 未声明的键不进领域模型/值接口/meta，首次
  发现记 WARNING（去重集合，可感知可审计）; 新增键必须先在 _FIELDS 添加
  声明。ConfigCategory.OTHER 枚举与前端图标映射随之移除（8 分类）;
  _guard_surface 未声明键一律 422（任何场景）; 写入用例改声明键
  （GITHUB_TOKEN/HF_ENDPOINT）; 未声明键断言反转（不出现+告警登记）。
  终验: pyright 0/0 + 后端 9/9 + E2E 93/93 + 前端 tsc 0 + 44/44 +
  插件 17/17 + 加载 ✓
- 配置接口全面 POST 化 + surfaces 列表贯穿全链路（用户指令）: 禁 GET，
  请求结构化（pydantic 模型 ConfigQuery/ConfigUpdate/Delete，单字段也包装）;
  路由 POST /api/config/{list,meta,required-status,update,delete}（单键 GET/PUT
  接口删除）; config_meta 签名改 list[Surface]（多场景天然合并）; _guard_surface
  改交集语义（与读一致）。消费方同步: 前端 client×5（POST+body）+ 契约断言、
  插件 control-config（POST /api/config/list，surfaces:["config"]）、E2E 全量
  转换。插件管道影响（用户问）: controlFetch 原生支持 POST+body 无影响;
  版本窗口——控制台与 opencode 需同批重启（新路由 404 → 插件 fail-safe+日志）。
  实施 note: control-config.ts 编辑残留重复段致语法错误（验证即时抓到修复）。
  终验: pyright 0/0 + 后端 9/9 + E2E 93/93 + 前端 tsc 0 + 44/44 + 插件
  17/17 + 2/2 + test-control 11/11 + 加载 ✓
- 入参类型固定 + get_entries 收敛（用户指令）: surfaces 统一
  list[Surface] | None（消灭 Surface|list|tuple 联合类型; get_kv_list/
  required_status 必填 list）; get_entries 重写为循环内过滤（wanted 交集
  continue）+ 值解析提取 _resolve_value（validator/缓存/回落收口单点）;
  raw 命名改 configs（实际配置值）。调用方同步: routes×5/scanner/proxy_pool
  ×2/tests。清理 3 处历史 __import__ 内联残渣（Any 逃过 pyright，裸单值
  被 set() 拆字符集致手写键丢失——本轮 test_control 2 失败的根因）。
  读数: pyright 0/0 + 9/9 + 93/93
- _TEMPLATE 手写模板删除 → _build_template() 从 _FIELDS 动态拼接（单一来源:
  必要键显式待填+hint 注释/无默认可选键注释提示/有默认键省略; 范围限
  CONFIG 场景; IDA 平台示例并入 hint）; E2E 补动态特性断言（hint 进模板/
  无默认可选注释/有默认省略）; test_env_rw 注释断言同步。读数 9/9 + 93/93
- 配置全链路覆盖审计（用户交付前审视驱动）: 补 5 处缺口——后端单元
  +path 归一化与 validator 链（临时 HOME 验 ~/ 展开/通过/回落/手写键不归一）
  +validator 结果缓存不重跑 +get() 非法回落→None +required_status 三态与
  场景过滤（未配置 False/合法 True/非法 False/remote 空）+get_entries 序列
  场景参数（多场景并集）; E2E +值接口与 required-status 缺 surface 422 +
  值接口场景隔离; 前端 +getConfig/getRequiredStatus surface 契约断言;
  首次回归 test-control.ts（fetchConfig 改 surface 后）11/11
- test-control.ts 两个失败经 stash 对照确认为存量环境问题（沙箱残留 unix
  socket 致 EADDRINUSE 并干扰单飞用例），清理 /tmp 沙箱后 11/11 全绿
- 交付读数: 后端 9/9 + E2E 93/93 + pyright 0/0 · 前端 tsc 0 + 44/44 ·
  插件 17/17 + 2/2 + test-control 11/11 + 加载冒烟 ✓
- 侧证: 交付审计期间一次 bash 外部路径访问被权限超时自动拒绝并返回引导
  文案——功能生产链路真实生效（用户已重启加载新代码）
- 二次评审处置（review 子代理，无正确性 bug、3 低severity 发现全处置）:
  ①validator 副作用进所有读取路径（heartbeat 每 10s sweep 经 get() 触发全量
  校验，配置失效时 WARNING 无限刷屏）→ (key,value) 结果缓存: 同组合只校验+
  告警一次，value 变化自动重校; ②模块头/writableUpdates 过时注释改写;
  ③本文件后置轮恢复编年顺序。三个有意行为变更（插件 fail-safe 自禁用/
  get 返回合并值畸形静默回落/banner error 恒空）经逐一核对消费方确认无破坏

- 后置轮（实测复盘改进，用户确认"都做"）:
  1. onReplied 补日志——撤销布防/无 pending/防御分支全部留痕（用户手动处理路径可排查）
  2. 拒绝反馈文案加"（权限询问超时自动拒绝）"前缀——模型区分自动/手动拒绝；
     测试断言同步增强（超时标识 + 文案双断言）
  3. 知识沉淀: opencode-plugin-api.md 新增"bash 工具 external_directory 触发范围"
     （白名单命令 cd/rm/cp/mv/mkdir/touch/chmod/chown/cat + 工作区外 workdir + ls 不触发）;
     opencode-references.md 修正"只扫描命令行静态路径"为白名单精确表述 + 新增
     "插件日志路由（debugLog 三级）"节
  4. 需求文档 §1 平台实证同步修正（白名单命令表述）
  验证: permission 17/17（含新断言）+ reflection 2/2 + control 11/11（清沙箱后）+
  不可见字节扫描 5 文件 CLEAN + 叙事词清零
  发现（待定）: test-control 沙箱不自清理（socket 残留 → 重跑 EADDRINUSE/单飞假失败）——
  需重跑前 rm -rf /tmp/control_test_ts

- 生产实测（用户重启 opencode 后，用户亲自观测）: 两次 external_directory 触发
  （cat Desktop 文件）均 10 秒自动拒绝（10.043s / 10.020s）——用户观测"弹框出现，
  约 10 秒自动消失"与日志时间线吻合；新前缀文案"（权限询问超时自动拒绝）"送达模型、
  onReplied 新日志（replied 无 pending）均生效；同目录重复触发正常（拒绝不写 always 记忆）;
  连续两次独立 requestID 无状态残留

- test-control 修复（用户确认"要修"）:
  1. socket 清理: uds 测试创建前清残留 + 文件末尾兜底清理（防 EADDRINUSE 连锁:
     残留 → Bun.serve 抛错 → finally 不执行 → 残留永存）
  2. 附带发现并修复: 单飞测试断言数沙箱日志"累计" spawn 行数——重跑必然误报
     （实际 N 递增），改为基线差值（只数本次新增）
  验证: 不清沙箱连续 3 跑 11/11 + 假残留注入跑 11/11 + 跑后无 socket 残留

- 知识沉淀: testing-blind-spot-patterns.md 新增模式 O（沙箱资源不自清理 + 累计量
  断言——重跑假失败连锁；识别/防御/排查纪律三节）+ 防御资产对照表加 O 行 +
  排查指引加第 10 条；字节扫描 CLEAN、叙事词零残留
- 手动处理路径实测（用户操作）: 09:47 手动拒绝 → 模型收无 feedback 通用文案、
  日志"replied 已撤销布防"、无自动拒绝（不补刀）; 09:55 允许一次（once，非始终允许——
  不写 always 记忆）→ 命令正常执行、同样"已撤销布防"——拒绝/允许两路径均闭环

- 记忆语义实测（用户操作）: 09:55 允许一次（once）→ 10:10 同路径再次弹窗（once 不写
  记忆，验证成立）; 10:10 用户对再次询问选择"总是允许"（always，写 pattern 记忆
  /Users/aserlili/.opencode/*）→ 10:11 同路径静默通过（无权限事件，记忆生效）——
  四语义矩阵（自动拒绝/手动拒绝/允许一次/总是允许）全部闭环
