# 控制台前端「运行状态」页（顶栏 Tab + 心跳进程可视化）

日期: 2026-08-22
状态: 已实施完成（2026-08-22）

## §1 背景与目标

**来源痛点**: 首页（环境总览）塞满了静态环境数据（依赖/配置/模型缓存），而动态运行时信息（连接了几个 opencode、管理进程状态）藏在页尾无锚点导航。心跳机制（2026-08-22-heartbeat-no-users-file.md）上线后，"哪些 opencode 连着"只有后端内存表，前端不可见。

**目标**:
1. 新增「运行状态」页：显示连接的 opencode 进程（心跳数据）+ 控制台管理的进程（从首页挪入）
2. 入口 = 顶栏 Segmented Tab（「环境总览」/「运行状态」）+ hash 路由（`#/runtime`），旧 `#section-*` 锚点全兼容
3. 首页 section 6→5，聚焦环境就绪

**预期收益**:
- 运行时状态从"页尾无导航"提升为一级页面（可用性）
- opencode 连接数可视化——心跳机制、keeper 过渡态、自杀判定全部可观测（排障能力）
- 首页信息密度聚焦（上下文/认知负担）

## §2 技术方案

### 2.1 后端（3 处改动）

**A. `services/heartbeat.py`**——registry 加 snapshot + 模块级富化函数:

```python
# HeartbeatRegistry 加方法（锁内浅拷贝）
def snapshot(self) -> list[HeartbeatEntry]: ...

# 模块级 dataclass + 富化函数（psutil 在这一层; registry 保持纯内存）
@dataclass
class OpencodeProcessInfo:
    pid: int
    last_seen_sec_ago: float      # time.monotonic() - entry.last_seen
    alive: bool                   # psutil 进程是否存在（SIGKILL 后 60s sweep 窗口内为 False）
    cmdline: str | None           # " ".join(cmdline); AccessDenied → None
    cwd: str | None               # AccessDenied → None
    running_sec: float | None     # now - create_time; NoSuchProcess → None

def collect_opencode_processes() -> list[OpencodeProcessInfo]: ...
```

边界: `psutil.NoSuchProcess/ZombieProcess` → alive=False、cmdline/cwd/running_sec=None（心跳条目 60s sweep 窗口内的正常残留，前端显示"疑似退出"）; `AccessDenied` → alive=True、对应字段 None。

**B. `routes/heartbeat.py`**——加查询路由（heartbeat 语义内聚，不新建文件）:

```
GET /api/heartbeats → { "opencode": [ {pid, last_seen_sec_ago, alive, cmdline, cwd, running_sec}, ... ] }
```
（与 /api/processes 风格一致: 单键列表，不冗余 count——前端 length 即得）

**C. `routes/system.py`**——响应加 `start_time: float`（Unix 时间戳，`get_process_start_time(os.getpid())`，工具函数已存在于 services/process_lock.py）。前端页头摘要行用。

### 2.2 前端

**A. Tab 层（App.tsx）**:

```tsx
type PageKey = "overview" | "runtime";
// hash 解析: "#/runtime" → runtime; 其余（无 hash / #section-*）→ overview
function pageFromHash(): PageKey { return location.hash === "#/runtime" ? "runtime" : "overview"; }
// useState 初始化 + hashchange 监听同步（点旧书签 #section-models 自动回落 overview）
```

- Header 品牌右侧加 `<Segmented options={[{label:"环境总览",value:"overview"},{label:"运行状态",value:"runtime"}]}/>`，onChange: runtime → `location.hash = "#/runtime"`; overview → `history.replaceState(null, "", location.pathname + location.search)`（设 hash="" 会残留 `#`）
- 锚点胶囊行（sticky）仅 overview 渲染；runtime 页无页内导航（卡片少）
- 内容条件渲染: overview = 现有网格删 processes Col; runtime = 摘要行 + OpencodeSection + ProcessSection
- CATEGORIES 零改动（本就不含 processes）

**B. 新组件 `sections/OpencodeSection.tsx`**（模式照抄 ProcessSection: 自轮询 10s + 手动刷新）:

- 页头摘要行（Typography，非卡片）: 「控制台 PID {n} · 已运行 {时长} · boot {token}」——api.getSystem() + /api/health fetch 容错（照抄 App.tsx 现有 boot_token 轮询的 fetch 模式，避开 503 时 axios 抛错）
- 表格列: PID / 状态 / 最后心跳 / 运行时长 / 命令行（EllipsisCell）/ 工作目录（EllipsisCell）
- 状态判定: `!alive` → 红"疑似退出"（Tooltip: 心跳条目残留，60s 内自动清除）; `last_seen_sec_ago > 15` → 黄"心跳延迟"; 其余 → 绿"在线"
- 空态: 「暂无 opencode 连接——启动宽限（90s）后心跳表仍为空时，控制台将自动退出」Secondary 文案。注: 生产有 keeper 常驻心跳，空态实际不可见; 沙箱测试由 conftest 心跳线程供数据

**C. `sections/ProcessSection.tsx`**: 组件零改动，仅挂载点从首页网格挪到 runtime 页（标题微调"进程"→ 保持，描述已准确）。

**D. types + api client**: `OpencodeProcessInfo`/`HeartbeatsResponse` interface; `SystemInfo` 加 `start_time: number`; `api.getHeartbeats()`。

**E. 共享格式化工具**: `utils/format.ts` 提取 `relTime`/`fmtDuration`（现仅 ProcessSection 内私有; OpencodeSection 是第 2-3 处使用，按收口规则提取）。ProcessSection 改为引用（微改 ~6 行，"纯挪移"承诺仅指布局位置）。

### 2.3 兼容性

- 旧 URL `#section-docker` 等: hashchange → overview + 浏览器原生锚点滚动（`#section-*` 非 `#/runtime` 即 overview）✓
- 现有 e2e `rendered` fixture 开 root URL（无 hash）→ 默认 overview → 全部现有断言兼容
- /api/system 加字段为增量，无消费方破坏

## §3 实现规范

### 改动范围表

| 文件 | 改动 | 预估行数 |
|---|---|---|
| backend/services/heartbeat.py | snapshot() + OpencodeProcessInfo + collect_opencode_processes() | +75 |
| backend/routes/heartbeat.py | GET /api/heartbeats | +20 |
| backend/routes/system.py | start_time 字段 | +5 |
| backend/tests/test_control.py | 单测 4 个 | +90 |
| frontend/src/types/index.ts | 2 interface + 1 字段 | +20 |
| frontend/src/api/client.ts | getHeartbeats | +8 |
| frontend/src/utils/format.ts | 提取 relTime/fmtDuration | +30 |
| frontend/src/sections/OpencodeSection.tsx | 新建 | ~180 |
| frontend/src/sections/ProcessSection.tsx | 改引用共享 utils | ~6 |
| frontend/src/App.tsx | Tab 层 + 条件渲染 + 挪 Col | ~110 |
| test/control/conftest.py | 心跳单发→持续线程(daemon, 8s 间隔, teardown 停) | +25 |
| test/control/test_frontend.py | API 用例 1 个 | +25 |
| test/control/test_frontend_e2e.py | e2e 3 个 + 修正 | +70 |

### §3.1 实施步骤

```
1. 后端: HeartbeatRegistry.snapshot() + OpencodeProcessInfo + collect_opencode_processes()
   - 文件: services/heartbeat.py
   - 预估行数: ~75
   - 验证点: compile 语法过; python -c 直调 collect_opencode_processes()——真 pid(自进程) 富化出 cmdline、假 pid(999999) 降级 alive=False 字段 None
   - 依赖: 无

2. 后端: GET /api/heartbeats + /api/system start_time
   - 文件: routes/heartbeat.py, routes/system.py
   - 预估行数: ~25
   - 验证点: compile 过; 沙箱起控制台 curl /api/heartbeats 返回 {"opencode":[...],"count":N} 且 /api/system 含 start_time
   - 依赖: 1

3. 后端单测: snapshot 纯净性(不污染注册表)/富化降级/路由响应契约/system start_time
   - 文件: tests/test_control.py
   - 预估行数: ~90
   - 验证点: tests/test_control.py 全绿(70+4)
   - 依赖: 2

4. 前端类型层: types + api client
   - 文件: types/index.ts, api/client.ts
   - 预估行数: ~28
   - 验证点: npx tsc --noEmit 零错误
   - 依赖: 无(与后端并行)

5. 前端: utils/format.ts 提取 relTime/fmtDuration + ProcessSection 改引用
   - 文件: utils/format.ts(新), sections/ProcessSection.tsx(删私有实现改 import)
   - 预估行数: ~40
   - 验证点: tsc --noEmit 零错误; ProcessSection 无行为变化(纯等价替换)
   - 依赖: 无
6. 前端: OpencodeSection.tsx 新组件(自轮询 + 摘要行 + 表格 + 状态判定)
   - 文件: sections/OpencodeSection.tsx(新)
   - 预估行数: ~180
   - 验证点: tsc --noEmit 零错误
   - 依赖: 4, 5

7. 前端: App.tsx Tab 层(pageFromHash/hashchange/Segmented/条件渲染/挪 ProcessSection)
   - 文件: App.tsx
   - 预估行数: ~110
   - 验证点: tsc --noEmit 零错误 + npm run build 成功(产出新 dist)
   - 依赖: 6

8. 测试: conftest 心跳改持续线程(修既有脆弱性: 现只发一次心跳, 60s 超时移除→表空自杀, 全靠 44 用例 <90s 跑完兜底, CI 慢机必翻车; 持续心跳同时为 /api/heartbeats e2e 断言供真数据——fixture pid 的 alive=True) + test_frontend.py API 用例 + test_frontend_e2e.py 运行状态页用例(Tab 切换/#/runtime 直达/心跳表渲染/首页无 processes)
   - 文件: test/control/conftest.py, test/control/test_frontend.py, test/control/test_frontend_e2e.py
   - 预估行数: ~120
   - 验证点: pytest test/control/ 全绿(44+4); 单文件全量耗时可超 90s 而沙箱控制台不死
   - 依赖: 7

9. 全量回归 + 生产切换: test_control/集成/TS 全绿 → dist 重建已含(步骤6) → 重启生产控制台 → 浏览器端验证 Tab/心跳卡/旧锚点
   - 验证点: 四套测试全绿; 生产 /api/heartbeats 200 且列表含 keeper 心跳; Tab 页可达
   - 依赖: 8
```

### 编码规则

- Python: 规则 9 强类型(dataclass; 禁裸 dict 传递——路由响应 asdict 序列化是合法边界)
- psutil 异常处理: NoSuchProcess/ZombieProcess/AccessDenied 全 catch，对应字段降级 None
- TS: 组件自轮询模式照抄 ProcessSection(setInterval 10s + cleanup); 禁止引入 react-router(为一个 Tab 不值)
- 日志: 富化异常 warning 一条(不刷屏——同 pid 下次轮询还会失败属正常残留窗口)

## §4 验收标准

**功能验收**:
- [ ] 顶栏 Segmented 两项，切换「运行状态」URL 变 `#/runtime`，刷新保持
- [ ] 运行状态页: 摘要行(控制台 PID/运行时长/boot) + opencode 心跳表(keeper 心跳可见，状态"在线") + 管理进程表
- [ ] 假 pid 心跳条目: 红"疑似退出"，60s 后消失
- [ ] 首页: 无 processes 卡片，锚点行不变(5 项)
- [ ] 旧书签 `#section-models`: 落 overview 并滚动到位

**回归验收**:
- [ ] tests/test_control.py 全绿(含新增 4)
- [ ] pytest test/control/ 全绿(含新增; 现有 44 不破坏)
- [ ] 集成 5/5, TS 10/10, tsc 零错误, npm run build 成功
- [ ] conftest 心跳线程: e2e 全量(含渲染等待)超 90s 沙箱控制台仍存活
- [ ] e2e_real 不涉改动可不重跑; 若 /api/system 消费方异常则重跑

**架构验收**:
- [ ] registry 保持纯内存(psutil 只在 collect_opencode_processes); 路由薄
- [ ] ProcessSection 组件零改动纯挪移
- [ ] 无 react-router 等新依赖

## §5 与现有需求文档的关系

- **2026-08-22-heartbeat-no-users-file.md**: 本需求是心跳机制的可视化消费方——心跳表首次暴露给前端。 keeper 过渡态在空态文案中向用户解释
- **2026-08-22-ocr-in-process.md**: 无直接依赖; ProcessSection 的 OCR 引用计数展示随本需求整体挪页(组件本身零改动)


## 实施结果记录（2026-08-22）

**全部 9 步完成**。测试: 单测 77/77（+4 心跳/system）· test/control 49/49（+5: API 1 + e2e 4）· 集成 5/5 · TS 10/10 · e2e_real 6/6 · tsc/build ✓

**审计轮修复（2 轮 + 纯审计通过）**:
1. 轮 1: 补"疑似退出"红标 e2e（假 pid 999999 注入 → 前端状态分支端到端）
2. 轮 2: **功能遗漏——重启按钮原在锚点行内，runtime 页卸载锚点行后失去重启入口**。修复: 挪 Header 右侧（全局操作两页通用）; "重新扫描"属环境域留在锚点行

**实施中即时纠正**:
- snapshot() 初版复用 HeartbeatEntry 装 age 值（语义污染）→ 改为 last_seen 保持 monotonic 语义的浅拷贝，age 计算归位富化层
- conftest 心跳线程嵌套函数内闭包 httpx.Client 改每跳新建连接（原 with 块退出后连接池关闭）
- e2e test_runtime_direct_url 初版函数内新开 sync_playwright 与 module 级 rendered fixture 事件循环冲突（单跑过/全量挂的假稳定）→ 复用共享 page + goto
- e2e 共享 page 状态泄漏（前序用例切 #/runtime 后 hash 残留）→ 两处用例卫生（切换后恢复 overview / 防御性 goto 重置）

**生产验证**: 控制台 80528; keeper(72912) 心跳经 /api/heartbeats 富化可见（cmdline/cwd/running 2643s）; vite 热载（生产 dev 模式形态）Playwright 实测 Tab 切换/心跳表/首页瘦身全过; dist 同步重建（e2e 用）

**关键决策**: registry 纯内存（psutil 只在富化层）/ 路由薄（asdict 序列化）/ 无 react-router（hash 手写解析 12 行）/ 心跳表随进程重启归零属预期（内存态，keeper 下一跳自动重注册）


## 迭代 2（用户首用反馈，2026-08-22 晚）

用户重启 opencode 后首次使用运行状态页的 4 项反馈全部落地:

1. **两列信息密度**: 运行状态页 2 列网格（xl 12/12，与环境总览同布局语言），opencode 卡与进程卡并排
2. **死列清除**: 进程表"引用计数/最后活跃"为 OCR 专属字段——OCR 转进程内加载后无进程再填（console/vite 从不设置）→ 前后端全链删除（ProcessInfo dataclass 3 字段 + 前端 HolderInfo interface + 2 列 + holders 展开），grep 零残留; OCR 引用可视化保留在模型板块（"运行中 · N 引用"）
3. **页级统一刷新**: runtime 页顶部"刷新"按钮（refreshToken 递增信号 → 两卡 + 摘要行同时重拉）; 逐卡刷新按钮移除（用户明确不要逐块点）
4. **keeper 退役**: 用户重启 opencode → 新插件原生心跳（pid 3528 注册）→ 心跳过渡 keeper（bun pid 72912，16:5x 为填补旧插件不发心跳的空档而临时拉起）验证新心跳在场后 kill 退役。心跳机制完整生命周期就此闭环: 文件标记 → keeper 过渡 → 原生心跳自持

测试: test/control 52/52（+3: 统一刷新请求捕获/死列删除断言/两列并排几何断言）· 单测 77/77 · tsc/build ✓ · 生产 Playwright 验证（2 列/统一刷新/死列删除/opencode 3528 在线/零 pageerror）
