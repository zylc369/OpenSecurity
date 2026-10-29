# 需求: 权限询问超时自动拒绝（目录权限无人值守兜底）

> 2026-09-30 | 状态: 完成 | 来源: 用户直接需求（多轮对话裁定 + 平台实证）

---

## §1 背景与目标

### 痛点
用户离开电脑让 agent 自主分析时，opencode 的权限询问弹窗（以 external_directory 为主）
会一直挂起等待点击——分析流程停摆直到用户回来。需要在无人响应 X 后自动拒绝，
并给出引导反馈让 agent 继续执行。

### 平台实证（前置调研，全部实测，证据见 progress.md）
- 插件 `event` hook 可收到 `permission.asked` / `permission.replied` 事件
  （字段: `id` / `sessionID` / `permission` / `patterns` / `metadata` / `tool`）。
- 拒绝通道: `POST /permission/{requestID}/reply` body `{reply:"reject", message?}`——
  `message` 生成 `CorrectedError.feedback`，随被拒工具的错误结果送达模型
  （实测: HTTP 200 `true`；工具错误含完整文案；模型继续执行不中断）。
- 官方文档的 `permission.ask` plugin hook 在 1.18.32 及 dev 最新版均**未接线**
  （仅类型定义，全仓库无触发点）——不可用，勿踩坑。
- v1 SDK 注入 client 无 `permission.reply`（运行时探测 `undefined`）；旧方法
  `postSessionIdPermissionsPermissionId`（body `{response}`）不支持 message。
- v2 基建（`permission.v2.asked` 事件 / `/api/session/:sid/permission/:rid/reply`）
  已在 dev 代码中，但 v2 插件 API 尚无权限/事件能力（PluginContext 无 event/permission 域）。
- bash 工具的 external_directory 检查只对白名单命令（cd/rm/cp/mv/mkdir/touch/chmod/chown/cat）的参数路径触发（脚本文件内部访问不扫描）
  ——反馈文案引导"写 Python 脚本再运行"在机制上可走通。

### 用户裁定记录（多轮对话）
- 默认超时 300 秒，`0`=关闭功能；时间单位用**秒**
- 范围: 仅 `external_directory`；代码设计支持扩展（类型列表配置化）
- 配置入口: 控制台配置页（配置区独立 TAB 已由
  `2026-09-30-config-surface-categories.md` 战役完成——本需求零前端改动）
- 超时拒绝附反馈文案（引导"先检查合理性；需要则写 Python 脚本再运行"），不中断会话
- 实现并入 security-analysis 插件体系（逻辑落 `lib/`，主插件接线）

### 目标
1. `external_directory` 权限询问超时（默认 300s）自动拒绝 + 反馈文案送达模型
2. 全部参数经控制台配置（ConfigManager 唯一权威；插件 `getCachedConfig()` 读取）
3. 适用权限类型可扩展（配置化逗号分隔列表）
4. v1/v2 事件名与回复通道双兼容（升级不静默失效）

---

## §2 技术方案

### 2.1 后端（config_manager.py + 测试）

**Keys 新增**（`ConfigManager.Keys`）:

```python
# 权限询问超时自动拒绝（插件 lib/permission-timeout.ts 经 /api/config 消费）
PERMISSION_ASK_TIMEOUT_SEC = "PERMISSION_ASK_TIMEOUT_SEC"
PERMISSION_ASK_TIMEOUT_TYPES = "PERMISSION_ASK_TIMEOUT_TYPES"
```

**extra_configs() 新增两条**（category=BEHAVIOR，与续传/反思键同类；surface 默认 CONFIG）:

| key | label | type | default_value | hint |
|---|---|---|---|---|
| PERMISSION_ASK_TIMEOUT_SEC | 权限询问超时（秒） | text | "300" | 权限询问超过该秒数未处理则自动拒绝（附引导反馈）; 0=关闭; 默认 300 秒，改后 30s 内生效 |
| PERMISSION_ASK_TIMEOUT_TYPES | 超时自动拒绝的权限类型 | text | "external_directory" | 逗号分隔的权限类型名; 默认仅 external_directory（目录权限），可加 edit/bash 等 |

**不动**: config_route.py（`_guard_surface` 对声明键自动纳入校验，新键 config 面可写）、
config_meta 机制（自动汇总渲染）、前端全部（meta 驱动）、`_TEMPLATE`（保持最小）。

**测试更新**:
- `tests/test_config_manager.py`: 新键声明存在 + category_code=behavior +
  default_value 断言（参照反思键断言段）
- `tests/test_control.py` E2E `test_e2e_config_meta`: 新键加入 config 面存在性
  断言列表 + behavior 分类断言（或新增独立断言行）

### 2.2 插件常量（lib/constants.ts）

```ts
// ─── 权限询问超时自动拒绝 ──────────────────────────────────────

// .ai_env 键名（见 lib/permission-timeout.ts）。
// 取值规则: 未配置/非法 → 默认 300 秒; 0 → 关闭; 正数 → 秒数。
export const ENV_KEY_PERMISSION_TIMEOUT_SEC = "PERMISSION_ASK_TIMEOUT_SEC";

// 超时自动拒绝的权限类型（逗号分隔）。未配置 → 仅 external_directory。
export const ENV_KEY_PERMISSION_TIMEOUT_TYPES = "PERMISSION_ASK_TIMEOUT_TYPES";

// 默认超时（秒）与默认适用类型（未配置时生效）。
export const PERMISSION_TIMEOUT_DEFAULT_SEC = 300;
export const PERMISSION_TIMEOUT_DEFAULT_TYPES = "external_directory";

// 超时拒绝时携带的反馈文案（随工具错误送达模型，不创建新消息）。
export const PERMISSION_TIMEOUT_REJECT_MESSAGE =
  "请先检查访问路径的合理性；如果确实需要访问，请将访问逻辑写进 Python 脚本并运行脚本（不要在命令行中直接写外部路径）。";
```

### 2.3 新模块（lib/permission-timeout.ts）

**职责**: 权限询问超时计时 + 超时拒绝（三级通道探测降级）。
**依赖方向**: `context` / `logging` / `control-config` / `constants`（均叶子/平级，
不反向依赖 security-analysis.ts——无循环）。

**数据结构与函数**:

```ts
/** 权限询问事件的最小信息集（v1/v2 字段差异在提取层归一） */
export interface PermissionAskInfo {
  requestID: string;
  sessionID: string;
  permissionType: string;
}

/** v1: props.permission; v2: props.action; 无效返回 null */
export function extractPermissionAskInfo(props: Record<string, unknown>): PermissionAskInfo | null

/** 超时毫秒: 未配置/非法→默认 300s; 0→0(关闭); 正数→秒*1000 */
export function getPermissionTimeoutMs(configReader?: () => Record<string, string>): number

/** 生效类型集合: 未配置→默认; 逗号分隔 trim 过滤空项（英文/中文逗号均容错） */
export function getPermissionTimeoutTypes(configReader?: () => Record<string, string>): Set<string>
```

```ts
export class PermissionTimeoutManager {
  constructor(configReader: () => Record<string, string> = getCachedConfig)
  onAsked(props: Record<string, unknown>): void   // 布防: 类型过滤→timeout>0→setTimeout
  onReplied(props: Record<string, unknown>): void // 清理: props.requestID 命中则 clearTimeout
  dispose(): void                                  // 清空全部定时器（插件 dispose 调用）
}
```

**onAsked 行为**:
1. `extractPermissionAskInfo` 失败 → debugLog，不布防
2. `getPermissionTimeoutMs() <= 0` → 关闭，不布防
3. 类型不在 `getPermissionTimeoutTypes()` → 不布防
4. 同 requestID 先清再 set（幂等去重）；定时器到期先自删 Map 再 `void this.reject(info)`

**异常兜底**: `reject()` 方法体整体 try/catch（三级通道全失败也只 debugLog）；
定时器回调内绝不抛 unhandled rejection。`onAsked`/`onReplied`/`dispose` 同步方法
不抛异常（内部提取失败走 debugLog 分支）。

**reject 三级通道**（探测降级，每级 debugLog）:

| 级别 | 通道 | feedback | 说明 |
|---|---|---|---|
| ① | `client.permission.reply({requestID, reply:"reject", message})` | ✅ | 未来 SDK 面（1.18.32 探测为 undefined，自动跳过） |
| ② | `client._client.post({url: "/permission/{requestID}/reply", body})` | ✅ | hey-api 底层方法，与 SDK 生成方法同一 client 实例——baseUrl/认证统一复用（请求收口）; `status 200/404` 视为完成 |
| ③ | `client.postSessionIdPermissionsPermissionId({path:{id:sessionID,permissionID:requestID}, body:{response:"reject"}})` | ❌ | v1 SDK 兜底（保证至少拒绝成功） |

**client 窄化类型**（SDK 类型无 permission 面）:

```ts
type ReplyCapableClient = {
  permission?: { reply?: (input: { requestID: string; reply: string; message?: string }) => Promise<unknown> };
  postSessionIdPermissionsPermissionId?: (input: {
    path: { id: string; permissionID: string };
    body: { response: string };
  }) => Promise<unknown>;
};
```

**configReader 注入**: 默认 `getCachedConfig`（生产）；测试 harness 注入假配置
（隔离控制台依赖，见 §3.1 步骤 4）。

### 2.4 主插件接线（security-analysis.ts）

1. import `PermissionTimeoutManager`
2. 插件函数内实例化: `const permissionTimeout = new PermissionTimeoutManager();`
3. `event` hook 开头（`const sessionID` 之后、`session.created` 之前）新增分支——
   **独立于 SECURITY_AGENTS / session 判断（所有会话生效）**:

```ts
// ── 权限询问超时自动拒绝（全会话生效，独立于 agent 判断）──
const eventType: string = event.type;
if (eventType === "permission.asked" || eventType === "permission.v2.asked") {
  permissionTimeout.onAsked(props);
}
if (eventType === "permission.replied" || eventType === "permission.v2.replied") {
  permissionTimeout.onReplied(props);
}
```

（`event.type` 先赋给 `string` 变量再比较——v1 SDK Event union 不含 v2 字面量，
直接比较会触发 TS2367）

4. hooks 返回对象新增 `dispose`:

```ts
dispose: async () => {
  permissionTimeout.dispose();
  debugLog("SecurityAnalysisPlugin dispose: 已清理权限超时定时器");
},
```

### 2.5 知识沉淀

- `$SHARED_DIR/knowledge-base/opencode-plugin-api.md` 增补「权限事件与自动回复」节:
  事件字段 / reply 端点两种 body 形态 / feedback(CorrectedError) 机制 /
  `permission.ask` hook 未接线警告 / v2 对照
- `$AGENT_DIR/knowledge-base/opencode-references.md` 平台行为实证记录增补:
  权限询问自动处理实证（含 CLI run --auto/非 auto 行为、bash 命令行扫描 vs
  脚本内访问、v1 插件在 v2 runtime 的 loader 形态差异迁移风险）
- `$AGENT_DIR/knowledge-base/architecture-map.md` Plugin hooks 表同步:
  `event` 行补权限超时职责、补 `dispose` 行

---

## §3 实现规范

### 改动范围表

| 文件 | 改动 |
|---|---|
| control/backend/services/config_manager.py | Keys +2; extra_configs +2（BEHAVIOR） |
| control/backend/tests/test_config_manager.py | 新键断言 |
| control/backend/tests/test_control.py | E2E meta 新键断言 |
| plugins/lib/constants.ts | +6 常量 |
| plugins/lib/permission-timeout.ts | 新模块（~150 行） |
| plugins/security-analysis.ts | 接线（import/实例化/event 分支/dispose） |
| plugins/tests/test-permission-timeout.ts | 新 harness（~180 行） |
| security-analysis-evolve/knowledge-base/architecture-map.md | hooks 表同步 |
| binary-analysis/knowledge-base/opencode-plugin-api.md | 权限事件章节 |
| security-analysis-evolve/knowledge-base/opencode-references.md | 实证记录 |
| requirements/evolve/2026-09-30-permission-ask-timeout.md + .progress.md | 本对文档 |

### 编码规则
- TS: strict；禁 `any`（测试 harness 的 mock 允许 `as unknown as` 窄化）；面向对象
  （定时器状态私有化进类，规则 9）
- Python: 强类型；新字段走既有 ConfigField 模式；pyright 0/0
- 知识沉淀: 先读 `knowledge-writing-guide.md`；零来源叙事；grep 验证叙事词清零
- 不新增前端代码；不改 config_route.py；不改 `.ai_env` 模板

---

## §3.1 实施步骤（每步 ≤200 行，验证点独立可判）

**步骤 1**. 后端配置声明 + 测试断言
- 文件: config_manager.py + tests/test_config_manager.py + tests/test_control.py
- 内容: Keys +2; extra_configs +2; 两测试文件补断言
- 预估 ~80 行
- 验证: `python -c "compile(open('services/config_manager.py').read(),'x','exec')"` +
  pyright backend 0/0 + `python3 tests/test_config_manager.py` 全绿 +
  `python tests/test_control.py` 全绿（自隔离沙箱，生产控制台运行期可直接跑）
- 依赖: 无

**步骤 2a**. 插件常量（constants.ts）
- 文件: constants.ts
- 内容: §2.2 五常量（含反馈文案）
- 预估 ~15 行
- 验证: `cd .opencode/plugins && bun -e "import('./lib/constants.ts').then(()=>console.log('ok'))"`
- 依赖: 无

**步骤 2b**. 新模块 lib/permission-timeout.ts
- 文件: lib/permission-timeout.ts（新）
- 内容: §2.3 全量（提取/配置读取/manager/三级通道/异常兜底）
- 预估 ~180 行
- 验证: `cd .opencode/plugins && bun -e "import('./lib/permission-timeout.ts').then(m=>console.log(Object.keys(m)))"`
  导出符号齐全（PermissionTimeoutManager/extractPermissionAskInfo/
  getPermissionTimeoutMs/getPermissionTimeoutTypes）
- 依赖: 2a

**步骤 3**. security-analysis.ts 接线 + 架构地图同步
- 文件: security-analysis.ts + architecture-map.md
- 内容: import/实例化/event 分支（双事件名）/dispose; 架构地图 hooks 表
- 预估 ~45 行
- 验证: bun 转译冒烟（同步骤 2b 手法导入 security-analysis.ts）+ grep 断言
  （`permissionTimeout.onAsked` / `permissionTimeout.onReplied` / `permissionTimeout.dispose` 各出现）+
  架构地图人工读一遍
- 依赖: 2b

**步骤 4**. 插件单元测试 harness
- 文件: plugins/tests/test-permission-timeout.ts（新）
- 内容: 驱动真实 `PermissionTimeoutManager`（mock ctx + `Bun.serve` 假 server +
  注入 configReader）; 用例: ①默认布防→超时→HTTP POST 收到（带 message）;
  ②类型过滤（edit 不布防）; ③`0`=关闭; ④`onReplied` 清理后不触发;
  ⑤`dispose` 清理; ⑥serverUrl 缺省→降级 mock client 通道③; ⑦非法配置回退默认
- 预估 ~180 行
- 验证: `OPENSECURITY_HOME=/tmp/perm_timeout_test bun .opencode/plugins/tests/test-permission-timeout.ts`
  全绿（沙箱前缀防日志污染生产路径）
- 依赖: 2b

**步骤 5**. 端到端集成验证（真实 opencode server）
- 文件: 无（验证步；复用 `/var/folders/.../opencode/perm-e2e` 测试项目基建）
- 内容: 测试项目插件改为 import 真实 `lib/permission-timeout.ts`（绝对路径），
  `ctx.init` 注入真实 client，configReader 注入 `{PERMISSION_ASK_TIMEOUT_SEC:"3"}`
  → 起 `opencode serve` → 触发外部目录 read → 断言: 3s 后自动拒绝 /
  工具错误含反馈文案 / 模型继续执行 / hook 日志含"通道②"记录
- 预估 ~60 行（测试插件改写）
- 验证: 上述断言逐条检查（hook 日志 + session 消息）
- 依赖: 2b（接线步骤 3 由 grep 验证，不阻塞本步）

**步骤 6**. 知识沉淀
- 文件: opencode-plugin-api.md + opencode-references.md（先读 knowledge-writing-guide）
- 内容: §2.5 三项
- 预估 ~120 行（净增）
- 验证: 人工自包含检查 + 本次产出 grep 叙事词清零 + 引用路径正确
- 依赖: 5（先有验证结论）

**步骤 7**. 全量终验 + 收尾
- 文件: progress 文档更新
- 内容: pyright backend 0/0; pytest（test_config_manager + test_control）;
  bun harness 重跑; 步骤 5 重跑; `getCachedConfig` 链路（GET /api/config 含新键）;
  进度/需求文档状态收口
- 依赖: 1, 3, 4, 5, 6

---

## §4 验收标准

### 功能验收
1. 配置页"行为"分类出现两个新键（meta 接口 `surface=config` 返回、category=behavior、
   默认值正确）; 经 `PUT /api/config?surface=config` 写入 `.ai_env` 落盘正确
2. `external_directory` 权限询问在超时后自动拒绝: 工具结果错误含反馈文案;
   模型继续执行（不终止、不循环挂起）
3. 非生效类型（如 `edit`）的询问不受影响
4. 边界: `0`=关闭（不布防）; 未配置/非法=默认 300s; 用户已处理（replied）
   的请求不被超时重复拒绝
5. 插件 dispose 后无孤儿定时器（harness 断言）

### 回归验收
- pyright backend 0/0; test_config_manager + test_control 全绿
- 前端零改动（tsc 不涉及）; 现有 event hook 行为不回归（端到端验证中
  session.created/idle 等逻辑正常）
- 插件既有测试（tests/test-control.ts）不受影响

### 架构验收
- 配置声明唯一来源 = ConfigManager；插件只读 `getCachedConfig()`（不直接读 .ai_env）
- 权限事件处理独立于 SECURITY_AGENTS 判断（所有会话生效）
- 无循环依赖: `lib/permission-timeout.ts` 不反向 import 主插件
- v1/v2 双兼容设计落地（事件名 + 三级通道）

---

## §5 与现有需求文档的关系

- 承接 `2026-09-30-config-surface-categories.md`: 配置面模型（surface/category）
  已就位，本需求新键走同一模型，**前端零改动**；该战役的 `writableUpdates`
  过滤逻辑自动覆盖新键（config 面、非 readonly）
- 平台实证部分与 `opencode-references.md` 既有"opencode 平台行为实证记录"
  同源——本需求完成后回填沉淀
- 与 `2026-09-29-single-source-consolidation.md` 无交集（不涉及知识/脚本收口）

---

## 执行进度（随步骤更新）

- [x] Phase 2 需求文档成稿
- [x] Phase 3 审计需求文档（3 轮: 2 修 + 1 纯，7 问题全修）
- [x] Phase 4 执行计划确认（架构影响图见 progress.md）
- [x] Phase 4.5 跳过（不触碰 agent prompt; 新文件均在既有目录模式内）
- [x] Phase 5 步骤 1-7 全部执行完毕（逐条记录见 progress.md）
- [x] Phase 6 实现审计（2 轮 + 纯审计发现 1 问题修复 + 复核零问题; 证据见 progress.md）

## 完成结论（2026-09-30）

全部 7 步执行完毕、三类验收全过:
- 功能: 配置页新键声明（meta 断言）/ 超时自动拒绝 + feedback 送达 + 不终止
  （真实 server 端到端 4 次一致）/ 类型过滤 / 0=关闭 / 边界（harness 10 用例）
- 回归: pyright backend 0/0 + test_config_manager 5/5 + test_control 94/94 +
  harness 10/10 + 插件加载冒烟
- 架构: 配置声明唯一权威 ConfigManager; 插件只读 getCachedConfig; 事件处理
  独立于 agent 判断; 无循环依赖; v1/v2 双兼容落地

**生效条件（交付注意）**: 控制台进程与 opencode 需重启加载新代码
（控制台加载 config_manager.py 新声明 → 配置页显示新键; opencode 加载插件新
代码 → 超时功能生效）。默认: 300 秒 / 仅 external_directory / 配置页"行为"分类。

## 后置修订: 拒绝请求收口重构（2026-09-30，用户评审驱动）

用户指出 Manager 构造传 serverUrl + 裸 fetch 破坏了"到 opencode server 的请求统一走
ctx.client"的收口约定（对照: 到控制台统一走 controlFetch）。重构: 通道② 由
"裸 fetch + 手动 Basic auth"改为 `ctx.client._client.post`（hey-api 底层方法，
与 SDK 生成方法同一 client 实例——baseUrl/认证/拦截器统一复用）; 构造函数去掉
serverUrl 参数，三级通道全部经 ctx.client 收口。验证: harness 11 用例（含新增
"404 不降级"）+ 端到端（布防→通道②→feedback 送达）全绿; serverUrl/手动 auth
残留 grep 清零。详见 progress.md 后置轮记录。

## 后置修订 2: 默认值单一来源（2026-09-30，用户裁定）

§2.2 的 `PERMISSION_TIMEOUT_DEFAULT_SEC/TYPES` 常量与 §2.3 的"未配置→默认"设计
**作废**——默认值唯一权威移至服务端: `GET /api/config` 返回生效值（配置值或
ConfigField 声明默认）; 插件零默认副本，取不到生效值即不启用（fail-safe）+
排查日志。反思/续传开关的"未配置=开启"语义同步上收（default_value="1"）。
配置页保存改 dirty 提交（防默认值冻结进 .ai_env）。反馈文案改 shell/bat/Python
跨平台表述。详见 progress.md 后置轮记录。

## 后置修订 3: 默认值 300 → 60 秒

配置优化批次将权限询问超时默认值由 300 秒调整为 60 秒（`ConfigField` 声明的
`default_value` 与 hint 同步变更；"默认值单一来源"架构不变——插件仍零默认副本，
以服务端生效值为准）。§2 正文与"生效条件"节中的 300 秒为历史值，以本节为准。
`test_config_manager` 中该默认值的断言已同步（2026-10-01）。
