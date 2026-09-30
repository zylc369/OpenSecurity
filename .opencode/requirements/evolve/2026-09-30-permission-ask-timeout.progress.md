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
