# 需求: 配置分类 TAB + surface 页面声明模型 + 反思键可配置化

> 2026-09-30 | 状态: 执行中 | 来源: 用户直接需求（多轮对话裁定）

---

## §1 背景与目标

### 痛点
1. 反思相关变量（`REFLECT_NUDGE_ENABLED` / `REFLECT_NUDGE_INTERVAL_MIN`）只能手编
   `.ai_env`——插件经 `/api/config`（30s TTL/SWR）读取它们，但后端 ConfigField
   清单从未声明，`config_meta()` 不含 → 前端无渲染。
2. 配置项持续增长（现状 9 显式 + 14 hidden tunables + 6 远程键），全部平铺在
   环境总览页底部一个 Card 里，无分类、无独立页面、密度失控。
3. tunables 三组 14 项无任何 UI（只能手编文件）。

### 用户裁定记录（多轮对话）
- 分类名: 工具/模型/代理/**行为**（续传+反思）/开发/远程/远程调参/系统/其他
- `DEEPSEEK_MODEL` 联动归模型类; `GITHUB_TOKEN` 归工具类（按"配置服务的能力域"
  分类，密钥形态不构成归类依据）
- 代理池 5 调参: 配置页显示且可配置
- 远程 6 调参: 远程资源页显示，**先只读不许改**（readonly 字段承载，将来开放
  只翻字段值）
- 心跳 3 调参: 不上任何页面（surface=hidden 占位，手编文件）
- 分类图标: 前端内置 code→antd 图标固定映射（纯视觉，desc 仍后端权威）
- **surface 双角色模型**（用户设计）: ConfigField 对象字段（声明归属）+ 接口
  请求参数（页面自报身份），服务端按请求面过滤/校验，响应不回传 surface，
  前端零过滤逻辑
- meta 响应内嵌有序 categories（一页一请求拿全渲染所需）
- 全流程执行完毕才停，中途不请示

### 目标
1. 反思键可经控制台配置，保存落 `.ai_env`，插件 TTL 内自动生效（零插件改动）
2. 配置独立页级 TAB（`#/config`），服务端分类枚举驱动分组，前端原样显示 desc
3. `GET/PUT/DELETE /api/config*?surface=` 必填参数模型; readonly 服务端强制
4. 远程页连接配置（URL/TOKEN）写路径迁移通用接口，废除 `PUT /api/remote/config`
5. Apple 系统设置风 UI（桌面侧栏 + 卡片，窄屏适配，密度优先）

---

## §2 技术方案

### 2.1 后端（config_manager.py + config_route.py + routes/remote.py）

**新枚举（模块级，config_manager.py）**:

```python
class Surface(str, Enum):
    CONFIG = "config"    # 配置页渲染
    REMOTE = "remote"    # 远程页渲染
    HIDDEN = "hidden"    # 无页面（手编 .ai_env / 专用端点管理）

class ConfigCategory(str, Enum):
    TOOLS = "tools"            # 工具
    MODELS = "models"          # 模型
    PROXY = "proxy"            # 代理
    BEHAVIOR = "behavior"      # 行为
    DEVELOPER = "developer"    # 开发
    OTHER = "other"            # 其他（.ai_env 未声明键兜底）
    REMOTE = "remote"          # 远程（连接配置）
    REMOTE_TUNING = "remote_tuning"  # 远程调参
    SYSTEM = "system"          # 系统（心跳; 现无页面消费方）
```

- desc 经 `_CATEGORY_DESC: dict[ConfigCategory, str]` 映射（工具/模型/代理/行为/
  开发/其他/远程/远程调参/系统）; 顺序 = 枚举定义序（`list(ConfigCategory)`）
- ConfigCategory/Surface 均带 `_MISSING` 防御不需要——枚举值即 code

**ConfigField 字段替换**: 删 `hidden: bool`; 新增
`category: ConfigCategory = OTHER` / `surface: Surface = CONFIG` /
`readonly: bool = False`。

**ConfigMetaEntry（线上 DTO）**: 删 `hidden`; 新增 `category_code: str` /
`category_desc: str` / `readonly: bool`。

**新 DTO**:

```python
@dataclass
class CategoryView:
    code: str
    desc: str

@dataclass
class ConfigMetaView:
    categories: list[CategoryView]          # 该 surface 有条目的分类，枚举序
    entries: dict[str, ConfigMetaEntry]
```

**config_meta(surface: Surface) -> ConfigMetaView**: 汇总全部清单 → 过滤
`field.surface == surface` → 按 category 分组 → categories 只含有条目的分类
（枚举序）→ 未知 `.ai_env` 键兜底进 `config` 面（OTHER 分类，label=键名）。

**清单重构与分配总表**:

| 清单方法 | 键 | category | surface | readonly |
|---|---|---|---|---|
| required_configs | DEEPSEEK_API_KEY | models | config | - |
| | IDA_PRO_HOME | tools | config | - |
| extra_configs | DEEPSEEK_MODEL / DEEPSEEK_SMALL_MODEL(新声明) | models | config | - |
| | RESUME_ANALYSIS_ENABLED | behavior | config | - |
| | **REFLECT_NUDGE_ENABLED(新)** | behavior | config | - |
| | **REFLECT_NUDGE_INTERVAL_MIN(新, default 30)** | behavior | config | - |
| | JULIANG_TRADE_NO / JULIANG_API_KEY | proxy | config | - |
| | GITHUB_TOKEN | tools | config | - |
| | HF_ENDPOINT | models | config | - |
| | CONTROL_FRONTEND_DEV | developer | config | - |
| remote_link_configs（原 remote_tab_configs 拆分） | REMOTE_CONSOLE_URL / TOKEN | remote | remote | - |
| | REMOTE_CONSOLE_ENABLED | remote | remote | **true**（hint 注明只能经「切换远程」按钮） |
| node_side_configs（拆分） | CONTROL_API_KEY / RESIDENT / AUTOSTART | remote | **hidden** | - |
| tunable 配置拆三组: proxy_tunable_configs | 代理池 5 项 | proxy | **config** | - |
| remote_tunable_configs | 远程 6 项 | remote_tuning | remote | **true** |
| heartbeat_tunable_configs | 心跳 3 项 | system | **hidden** | - |

**新键声明**（Keys + extra_configs）:
- `REFLECT_NUDGE_ENABLED`: label=反思提醒开关, type=bool, hint 说明
  "默认开启; 0=关闭（反思纸条+反思唤醒两通道共用）"——与插件语义一致
  （未配置=启用，值 0/false=禁用）
- `REFLECT_NUDGE_INTERVAL_MIN`: label=反思提醒间隔（分钟）, type=text,
  default_value="30"（与插件 `REFLECT_NUDGE_DEFAULT_INTERVAL_MIN=30` 回退一致）

**tunables dataclass 读取器（remote_tunables()/heartbeat_tunables()/
proxy_tunables()）不动**——元数据声明与值读取正交。

**非目标**: `.ai_env` 模板（`_TEMPLATE`）不加反思键注释——反思开关默认开启
（未配置=启用），控制台已可配置，模板保持最小; 模板的存在意义只是首次引导
必要配置。

**路由（config_route.py）**:

```
GET /api/config/meta?surface=config|remote     ← 必填; 非法/缺省 422
    → ConfigMetaView（FastAPI Query Literal 校验）
PUT /api/config?surface=…  body {configs}      ← 必填
PUT /api/config/{key}?surface=…                ← 必填（无前端消费方，保持一致）
DELETE /api/config/{key}?surface=…             ← 必填（同上）
```

查询参数类型用 `Literal["config", "remote"]`（而非 Surface 枚举——枚举含
HIDDEN 会让 `surface=hidden` 通过校验）; handler 内转 `Surface(...)` 后走
ConfigManager。

**_guard_surface(keys, surface)** 逐键校验:
1. 声明键: `field.surface != surface` → 422（"配置 X 不属于 surface=Y 页面"）
2. 声明键 `readonly=true` → 422（"X 为只读配置，不能经配置接口写入"）
3. 未声明键: `surface == CONFIG` 放行（兜底同 OTHER 分类语义）; REMOTE 面
   拒绝（"远程页只能写已声明的远程配置"）

保留 `_guard_protected_keys`（ENABLED 专用文案守卫，先于通用校验执行——
报错信息保留"只能经「切换远程」按钮写入（先校验后置位）"）。

**废除**: `PUT /api/remote/config`（routes/remote.py 的 `update_config` handler
+ `RemoteConfigUpdate`/`ConfigUpdateResult` DTO）——唯一前端消费方 RemoteSection
同批迁移。**旧端点的写后热重载副作用保留**: 通用写边界的 `_after_write(keys)`
钩子对 `REMOTE_CONSOLE_URL/TOKEN` 触发 `RemoteLinkService.reload_config()`
（key 触发副作用——同 invalidate_deps_snapshot 既有模式，非定制代码）。

**不动**: `GET /api/config`（值全量，插件消费方）、`GET /api/config/{key}`、
`GET /api/config/required-status`、远程动作端点（switch/status/health/
node-config/autostart——带校验/副作用/跨节点转发，属"动作"域）。

### 2.2 前端

**types/index.ts**:
- `ConfigSurface = "config" | "remote"`
- `ConfigMetaItem`: 删 `hidden`; + `readonly: boolean` / `category_code: string` /
  `category_desc: string`
- + `ConfigCategoryView { code; desc }` / `ConfigMetaResponse { categories:
  ConfigCategoryView[]; entries: Record<string, ConfigMetaItem> }`

**api/client.ts**: `getConfigMeta(surface)` / `updateConfig(updates, surface)` /
`deleteConfig(key, surface)` 全部带必填 query 参数; 删 `updateRemoteConfig`。

**hooks/index.ts**: `useConfigMeta()` → `useConfigMeta(surface)`（返回
ConfigMetaResponse）; `useAllConfig` 不变（值读取）。

**新文件**:
- `utils/configGrouping.ts`（+ test）: 纯函数
  `groupEntries(entries, categories) -> Array<{code, desc, keys}>`——分组顺序
  严格 = categories 数组序; 某分类零条目剔除; 条目组内顺序 = 服务端
  required 优先 + label 字典序（沿用现有排序规则）
- `constants/configIcons.ts`: `code → antd icon` 固定映射
  （tools: ToolOutlined / models: RobotOutlined / proxy: GlobalOutlined /
  behavior: ThunderboltOutlined / developer: CodeOutlined / other: AppstoreOutlined /
  remote: CloudServerOutlined / remote_tuning: SyncOutlined / system: DashboardOutlined）
- `components/ConfigFieldRow.tsx`: 单条差异化渲染
  （password 小眼睛 / path 存在徽标 / bool Select(1,0) / text），readonly 态 =
  禁用控件 + 显示当前值或默认值 + "只读"Tag; PathCheckBadge 从 ConfigSection
  迁入本文件
- `sections/ConfigPage.tsx`: 配置页（App 第四 TAB `#/config`）
  - 桌面（≥lg）: 左侧分类导航（图标+desc，选中态圆角高亮块）+ 右侧当前分类
    Card（标题=desc 原样）+ 顶部 sticky 保存栏（dirty 提示 + 必要缺失 Alert）
  - 窄屏（<lg）: 顶部水平滚动分类胶囊条
  - 双列网格密度（沿用 Row/Col lg=12）

**App.tsx**: `PageKey + "config"`（`#/config` hash 路由 + Segmented 第四项）;
环境总览移除 ConfigSection 挂载 → 保留 readiness 配置状态徽标卡 + "去配置→"
链接（readiness CATEGORIES 不动）。

**RemoteSection.tsx 改造**:
- 卡片 1 连接配置区: URL/TOKEN 输入 + 保存改走 `api.updateConfig({...},
  "remote")`; 新增 ENABLED 只读行（值 + hint 引导「切换远程」按钮）; 切换按钮/
  健康度 Descriptions 不动
- 新增"远程调参"Card: `useConfigMeta("remote")` 取 remote_tuning 分类 6 条
  readonly 行（显示生效值: `.ai_env` 值或默认值），无保存按钮
- 节点管理卡片 3 不动（专用端点域）

**删除**: `sections/ConfigSection.tsx`（被 ConfigPage 取代）。

### 2.3 插件
零改动。反思键消费方 `getCachedConfig()`（30s TTL/SWR）自动拿到新值。

---

## §3 实现规范

### 改动范围表

| 文件 | 改动 |
|---|---|
| backend/services/config_manager.py | 枚举/DTO/ConfigField/清单重构/反思键/config_meta(surface) |
| backend/routes/config_route.py | meta surface 参数/PUT·DELETE 校验/_guard_surface |
| backend/routes/remote.py | 删 PUT /config handler + RemoteConfigUpdate |
| backend/tests/test_config_manager.py | 元数据断言更新 + 新契约用例 |
| backend/tests/test_control.py | E2E meta 新契约 + surface 校验 422 用例 + 旧端点 404 |
| backend/tests/test_api_guard.py | ENABLED 守卫用例参数更新（如覆盖） |
| frontend/src/types/index.ts | 契约类型重构 |
| frontend/src/api/client.ts | surface 参数化 + 删 updateRemoteConfig |
| frontend/src/hooks/index.ts | useConfigMeta(surface) |
| frontend/src/utils/configGrouping.ts (+test) | 新增纯函数 |
| frontend/src/constants/configIcons.ts | 新增图标映射 |
| frontend/src/components/ConfigFieldRow.tsx | 新增共享行渲染 |
| frontend/src/sections/ConfigPage.tsx | 新增配置页 |
| frontend/src/sections/RemoteSection.tsx | 连接区迁移 + 调参只读卡 |
| frontend/src/App.tsx | 第四 TAB + overview 摘要卡 |
| frontend/src/sections/ConfigSection.tsx | 删除 |
| frontend/src/api/client.test.ts | getConfigMeta 带参断言更新 |

### 编码规则
- Python: 强类型（规则 9）; 新 DTO 全 dataclass; pyright 六规则 0/0
- TS: strict 0 error; 禁 any
- `hidden` 字段引用清零（精准 pattern: `m.hidden` / `field.hidden` /
  `.hidden=` / `"hidden":` / `hidden=True/False`）——注意排除 css 类名等同名词
- 需求文档/进度随步骤更新; progress.md 记录每步验证点输出

---

## §3.1 实施步骤（每步 ≤200 行，验证点独立可判）

**步骤 1**. 后端枚举与 DTO 纯增量
- 文件: config_manager.py
- 内容: Surface/ConfigCategory 枚举 + `_CATEGORY_DESC` + CategoryView/
  ConfigMetaView dataclass + Keys 加两反思键（不改现有字段/清单——纯新增）
- 预估 ~90 行
- 验证: `compile` + pyright backend 0/0 + pytest test_config_manager 全绿
  （旧契约不受纯增量影响）
- 依赖: 无

**步骤 2**. ConfigField/ConfigMetaEntry 字段替换 + 六清单重构 + config_meta(surface)
- 文件: config_manager.py + config_route.py（GET /meta 最小适配: surface
  必填 Query 参数 + 返回 ConfigMetaView）
- 内容: 删 hidden 字段; +category/surface/readonly; required/extra 清单赋值
  （含反思键/DEEPSEEK_SMALL_MODEL）; remote_tab_configs 拆 remote_link_configs +
  node_side_configs; tunable_configs 拆三组; config_meta(surface) 新签名
- 预估 ~190 行
- 验证: compile + pyright backend 0/0（此时 pytest 元数据用例预期红——
  步骤 3 修; 本步验证点 = 类型面）
- 依赖: 1

**步骤 3**. test_config_manager 断言更新
- 文件: tests/test_config_manager.py
- 内容: hidden 断言 → surface/category/readonly 断言; tunable_configs()==14
  → 三组清单数量; 未知键兜底 → config 面 OTHER; 反思键存在; categories
  顺序断言
- 预估 ~70 行
- 验证: pytest tests/test_config_manager.py 全绿
- 依赖: 2

**步骤 4**. 写接口 surface 校验 + 废除远程专用写端点
- 文件: config_route.py + routes/remote.py
- 内容: _guard_surface（三分支 422）+ PUT 批量/单键/DELETE 加必填 surface;
  ENABLED 守卫保留先行; 删 update_config handler + RemoteConfigUpdate
- 预估 ~100 行
- 验证: compile + pyright backend 0/0
- 依赖: 2

**步骤 5**. E2E 用例更新
- 文件: tests/test_control.py + tests/test_api_guard.py + tests/test_remote_routes.py
  （旧 /config 热重载用例改走通用接口 surface=remote——reload 断言保留）
- 内容: meta 新契约（surface 必填/分类内嵌/hidden 键不返回）; 422 用例
  （缺参/错面/readonly/hidden 键/未声明键 remote 面拒绝）; 旧端点 404;
  ENABLED 专用文案
- 预估 ~100 行
- 验证: pytest test_control.py + test_api_guard.py + test_remote_routes.py 全绿
- 依赖: 3, 4

**步骤 6**. 前端契约同步
- 文件: types/index.ts + api/client.ts + hooks/index.ts + ConfigSection.tsx
  （最小适配: 删 m.hidden 过滤——服务端已过滤）+ **client.test.ts**
  （deleteConfig/updateConfig 断言同步 surface 参数——既有用例已覆盖两函数，
  不同步则 vitest 假红/假绿）
- 预估 ~140 行
- 验证: tsc 0 error + vitest 全绿（既有用例含契约断言）
- 依赖: 4（契约定型）

**步骤 7**. 共享渲染组件 + 分组纯函数
- 文件: components/ConfigFieldRow.tsx（含 PathCheckBadge 迁移）+
  utils/configGrouping.ts + utils/configGrouping.test.ts +
  constants/configIcons.ts（4 个新文件）
- 预估 ~200 行
- 验证: tsc 0 error + vitest（含新增 configGrouping 用例）全绿
- 依赖: 6

**步骤 8**. 配置页 + App 接线
- 文件: sections/ConfigPage.tsx（新）+ App.tsx + 删 sections/ConfigSection.tsx
- 内容: 第四 TAB `#/config`; 环境总览 ConfigSection 挂载 → readiness 状态
  摘要卡，**保留 `id="section-config"` 锚点**（constants/categories.ts 的
  锚点导航依赖它，readiness 五分类不动）
- 预估 ~200 行
- 验证: tsc 0 error + vitest 全绿 + dev 模式走查（四 TAB/分类切换/保存/
  窄屏）记录到 progress.md
- 依赖: 7

**步骤 9**. 远程页改造
- 文件: sections/RemoteSection.tsx
- 内容: 连接区 meta 驱动（URL/TOKEN 保存走通用接口 + ENABLED 只读行）+
  远程调参只读卡; 删 updateRemoteConfig 调用
- 预估 ~150 行
- 验证: tsc 0 error + vitest 全绿 + dev 走查（保存/只读态/调参卡）
- 依赖: 7

**步骤 10**. 前端测试收口
- 文件: api/client.test.ts（getConfigMeta 带参/updateConfig surface 断言）
- 预估 ~40 行
- 验证: vitest 全绿
- 依赖: 8, 9

**步骤 11**. 全量终验
- 文件: 无（验证步）
- 验证: pyright backend+mcp-servers 0/0; pytest 全家族（test_control/proxy_*/
  oop/remote_link/config_manager/model_lifecycle/integration/api_guard/
  remote_client/remote_routes/e2e_real/e2e_remote）全绿; vitest 全绿;
  `hidden` 残留 grep 清零; dev 走查全清单落盘 progress.md
- 依赖: 5, 8, 9, 10

---

## §4 验收标准

### 功能验收
1. 反思开关/间隔在配置页"行为"分类可配; 保存后 `.ai_env` 落盘值正确;
   插件语义匹配（未配置=开; 0=关; 间隔非法回退 30）
2. `#/config` 第四 TAB; 分类侧栏 desc = 后端 desc 原样; 分类顺序 = 服务端
   枚举序
3. 代理 5 调参在"代理"分类可改（改后消费者重读即生效）
4. `GET /api/config/meta` 无 surface → 422; surface=hidden → 422;
   hidden 键（心跳 3 + CONTROL_* 3）任何合法面不返回
5. 写校验全生效: 错面 422 / readonly 422 / hidden 键 422 / 未声明键仅
   config 面可写; ENABLED 422 文案含「切换远程」按钮指引
6. 远程页: URL/TOKEN 保存走 `PUT /api/config?surface=remote`（网络面板
   确认）; `PUT /api/remote/config` → 404; ENABLED 只读行; 远程调参 6 项
   只读显示生效值（未配置显示默认）
7. `.ai_env` 未知键出现在配置页"其他"分类（label=键名）

### 回归验收
- pyright backend + mcp-servers 0/0; 前端 tsc strict 0 error; vitest 全绿
- pytest 全家族全绿（含 e2e_real / e2e_remote）
- 插件 `getCachedConfig` 链路不受影响（`GET /api/config` 契约不变）
- readiness 五分类（constants/categories.ts）不受影响

### 架构验收
- 页面组成完全由 surface+category 声明驱动——前端无任何 `key === "XXX"`
  形式的配置项硬编码判断（图标映射除外）
- ConfigManager 仍为 `.ai_env` 唯一读写方; 动作端点域（switch/node-config/
  autostart）未被配置化侵蚀
- 本需求文档 + progress.md 完整记录执行轨迹

---

## §5 与现有需求文档的关系

- 承接 `2026-09-30-pyright-unknown-any-tier.md` 的类型基线: 本需求全部新代码
  在 pyright 六规则 + tsc strict 下 0 error（该战役已建立 CI 门禁，
  type-check.yml 将自动验证）
- 远程资源域深度改造（node-config 转发/自启）范围外——仅迁移 URL/TOKEN
  写路径; 若未来节点侧三键需要 UI 化，翻 `node_side_configs` 的 surface 即可
- 与 `2026-09-25-proxy-ip-manager.md` 的关系: 代理 tunables 元数据声明来源
  于该战役的 ProxyTunables 默认值（同源生成，不重复定义默认值）

---

## 执行进度（随步骤更新）

- [x] Phase 2 需求文档成稿
- [x] Phase 3 审计需求文档（3 轮: 2 修 + 1 纯，4 问题全修）
- [x] Phase 4 执行计划确认（架构影响图见 progress.md）
- [x] Phase 4.5 跳过（不触碰 agent prompt; 新文件均在既有目录模式内）
- [x] Phase 5 步骤 1-11 全部执行完毕（逐条记录见 progress.md）
- [x] Phase 6 实现审计（3 轮: 2 审+修 + 1 纯审计零问题; 证据链见 progress.md）

## 完成结论（2026-09-30）

全部 11 步执行完毕、三类验收全过: 功能（live 契约 9 项 + 反思键 roundtrip）/
回归（pyright 双 scope 0/0 + 后端 12 套件全绿含 e2e 双真链路 + 前端 tsc/vitest/
build）/架构（页面组成完全由 surface+category 声明驱动，前端零配置项硬编码）。
待用户: 视觉走查（dev server localhost:5173 或控制台 9776）。
