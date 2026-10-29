# OCR 引用计数移除——纯空闲超时生命周期（懒加载 + 10 分钟空闲卸载）

日期: 2026-08-22
状态: 已实施完成（2026-08-22）

## §1 背景与目标

**来源痛点**（用户复核提出，完全成立）: 引用计数是 OCR 独立子进程时代"多客户端共享进程的安全释放"机制。in-process 之后：引用=会话数，opencode 开着就 ≥1 → **释放条件"引用归零"永不满足** → 1.2GB 驻留数小时（用户实测 observed）。控制台本身已是全局服务者（心跳机制管进程级存亡），推理互斥由 lifecycle 锁 + worker FIFO 保证（与引用无关）——引用计数退化为历史包袱。

**目标**:
1. 生命周期简化为: **extract 懒加载**（首图自动加载 1.6s）+ **纯空闲 600s 自动卸载**（用户确认 10 分钟）
2. 删除引用计数全链: acquire/close 端点、`_clients` 表、死客户端 psutil 兜底、HolderInfo
3. 前端 OCR 卡显示: `空闲时间：<已空闲>/[10 分钟]`，悬浮显示详情（用户明确要求）
4. 不再预热: 会话开始不加载（不用识图 1 字节不占）

**预期收益**: 语义诚实（引用=1 永远是用户自己，无辨识价值 → 空闲时长才是真信息）; 代码简化（ocr_service 预计 -100 行）; 内存按需（10 分钟不用即归还 1.2GB）。

## §2 技术方案

### 2.1 ocr_service.py 重构（核心）

**删**: `_clients` dict / `acquire()` / `close()` / `holders()` / `HolderInfo` / `_client_id()` / `_client_alive()` / reaper 的死客户端清理分支。

**extract 懒加载**（原 acquire 的加载逻辑并入）:
```
extract(b64, prompt):
    刷 last_activity_at
    ollama 分支不变（available 检查 + infer）
    if state != READY:  await _ensure_ready()   # 懒加载（单飞: 并发首图等同一 ready_event）
    预处理并发 → generate worker 串行 → 刷 last_activity_at
```
`_ensure_ready()`（持锁）: IDLE → 加载（STARTING→READY 窗口的 STOPPING/竞态防御原样保留——抢锁者从 force_release/reaper 变为 force_release/reaper，逻辑不变）; STARTING → 搭车等事件; READY → 直接返回。

**reaper 纯空闲**: `state==READY and now-last_activity > IDLE_RELEASE_SEC → 卸载`。无引用条件。
**`IDLE_RELEASE_SEC = 30 → 600`**。
**force_release 保留**（前端停止按钮; 删 `self._clients.clear()`）。
**OcrStatus**: 删 `clients` 字段。

### 2.2 routes/ocr.py

删 `/acquire`、`/close`、`AcquireRequest`。保留 `/extract`（懒加载语义）、`/status`、`/release`。消费方仅剩自己的 MCP 壳（同步改）+ 前端 status——旧壳调 acquire 得 404（壳按 warning 处理，用户重启 opencode 后完全干净，已确认可接受）。

### 2.3 MCP 壳（mcp-servers/ocr/server.py）

lifespan 简化为仅建/销 httpx client（删 acquire/close/psutil）。extract 工具不变（控制台懒加载对壳透明）。模块注释更新。

### 2.4 model_assets.py + 前端

- `ModelAssetStatus.active_clients` 删除; OCR 加 `idle_sec: float | None`（已空闲秒数; 未加载 None）与 `idle_timeout_sec: int | None`（=600）
- types/index.ts: `ModelAsset.active_clients` → `idle_sec`/`idle_timeout_sec`
- ModelsSection OCR 卡: loaded 时显示 `空闲 <fmtDuration(idle_sec)> / 10 分钟`（Typography + Tooltip 详情: "最近识图 X 前 · 空闲满 10 分钟自动释放内存 · 下次识图自动重新加载（约 1.6s）"）; idle_sec 接近阈值时颜色渐变（>8 分钟橙色提示）不必做——保持简单

### 2.5 测试重写面

- test_control.py 14 个 ocr 单测: 引用语义的 5 个重写（状态机/单飞→懒加载语义/空闲释放→纯空闲/client 死亡→删/竞态→force_release vs 懒加载窗口）; 并发 extract/推理在途互斥/加载失败传播/坏输入/竞争窗口/worker 稳定性 8 个改引用面（acquire 调用改 extract 或 _ensure_ready）
- e2e_real ocr 场景: 壳 lifespan acquire→删, 改"extract 懒加载真加载 → 识图 → force_release 卸载"（不等 600s; 空闲超时由单测覆盖）
- test_frontend.py test_api_models: active_clients 断言 → idle_sec/idle_timeout_sec

## §3 实现规范

### 改动范围表

| 文件 | 改动 | 行数 |
|---|---|---|
| backend/services/ocr_service.py | 删引用计数 + extract 懒加载 + reaper 纯空闲 + 600s | 净 -80 |
| backend/routes/ocr.py | 删 acquire/close | -35 |
| .opencode/mcp-servers/ocr/server.py | lifespan 简化 | -35 |
| backend/services/model_assets.py | active_clients → idle_sec/idle_timeout_sec | ±15 |
| frontend types + ModelsSection.tsx | OCR 卡空闲显示 | ±30 |
| backend/tests/test_control.py | 14 用例重写 | 净 ±60 |
| tests/test_e2e_real.py | ocr 场景更新 | ±20 |
| test/control/test_frontend.py | 断言更新 | ±5 |

### §3.1 实施步骤

```
1. ocr_service.py 重构: 删引用计数 + extract 懒加载(_ensure_ready 单飞) + reaper 纯空闲 + IDLE 600s + OcrStatus 删 clients
   - 验证点: compile 过; python 直调 extract 流程受阻于路由未改——先语法+逻辑走查, 步骤 2 后沙箱端到端
   - 依赖: 无
2. routes/ocr.py 删端点 + model_assets 字段替换
   - 验证点: compile; 沙箱控制台 curl: POST /extract 触发懒加载(未 acquire) → 200; GET /status 无 clients 键; /api/models OCR 条目含 idle_sec
   - 依赖: 1
3. MCP 壳 lifespan 简化
   - 验证点: compile; 壳真进程冒烟(临时脚本 spawn 壳 → 调 extract → 退出无报错)
   - 依赖: 2
4. 单测重写(14 用例: 5 重写 + 8 改引用面 + 1 竞态改触发方式)
   - 验证点: test_control.py 全绿(数量 77 左右, 懒加载语义全覆盖: 单飞/空闲释放/竞态防御/失败传播)
   - 依赖: 1,2
5. 前端: types + ModelsSection OCR 卡空闲时间显示
   - 验证点: tsc + npm run build
   - 依赖: 2(字段名对齐)
6. e2e_real ocr 场景 + test_frontend.py 断言更新
   - 验证点: e2e_real 全绿; pytest test/control/ 全绿
   - 依赖: 3,4,5
7. 全量回归 + 生产切换 + 文档
   - 验证点: 四套全绿; 生产 extract 懒加载实测; /api/models OCR 卡空闲字段; 需求文档收尾
   - 依赖: 6
```

### 编码规则

- 懒加载路径的 STOPPING/竞态防御**原样保留**（抢锁者 force_release/reaper 语义不变）
- extract 两处刷 last_activity_at（进入 + 完成）——推理中不算空闲
- 删功能零残留: grep `acquire|close|clients|holders|HolderInfo` 在 ocr 域零残留（壳/e2e 同步删）

## §4 验收标准

**功能**:
- [ ] 未 acquire 直接 extract → 自动加载并识图（懒加载 + 并发单飞）
- [ ] 识图后 600s 无活动 → 自动卸载（footprint 回落）; 再 extract → 重新加载
- [ ] OCR 卡: `空闲 <时长> / 10 分钟` + 悬浮详情
- [ ] /api/ocr/status 无 clients; /api/models OCR 无 active_clients 有 idle_sec
- [ ] 停止按钮（force_release）仍工作

**回归**: 单测全绿（懒加载/空闲/竞态/失败传播全覆盖）· e2e_real 6/6 · test/control 全绿 · 集成 5/5 · TS 10/10 · tsc/build ✓

**架构**: ocr 域引用计数零残留; 依赖方向不变

## §5 与现有文档关系

- 2026-08-22-ocr-in-process.md: OCR in-process 的第三轮演进——引用计数是该文档设计的生命周期，本需求以"纯空闲超时"取代之（用户复盘发现的语义退化）
- 2026-08-22-console-runtime-tab.md 迭代 2: 死列清除是本次的先声（进程页引用列已删, 本次删数据源本体）


## 实施结果记录（2026-08-22）

**7 步全部完成**。测试: 单测 77/77（14 个 OCR 用例全部重写为懒加载语义）· test/control 52/52 · 集成 5/5 · TS 10/10 · e2e_real 6/6（OCR 场景升级: 懒加载识图 → release 卸载 → 再识图自愈重载）· tsc/build ✓ · 生产 Playwright 实测（OCR 卡"空闲 X / 10 分钟"+ 引用文案零残留）

**代码量**: ocr_service.py 334→267 行（净 -67）; 壳 lifespan -35 行; 删 2 端点（acquire/close）+ HolderInfo + psutil 死客户端兜底全套

**实施中测试侧纠正（6+2 个测试 bug，业务代码零返工）**:
- 新语义下 extract 走完整链路: 坏 b64 输入（"x"/"ok"）在旧 acquire 测试无害、新 extract 测试到 preprocess 必炸 → 改真图
- "LIFE-2"被模型识别为"LIFE2"（连字符识别能力边界）→ 测试文本避开连字符
- 推理在途断言语义重设: extract 复用含推理排队（20s），改验证 status/idle_sec 读路径 <0.1s
- reaper 测试手动置 ready 需手动启动 reaper（生产 ready 必经 extract→_ensure_ready，无此问题——测试专用路径）
- 竞态测试发起者结果容错（成功或防御报错均可——锚定终态无假 READY）
- e2e_real 初版引用未定义变量 CONTROL_URL → 改用文件内 post() 基础设施

**兼容性实测**: 当前会话旧壳（3814）对新控制台 extract 正常工作（端点未变）; 旧壳退出调 close 得 404 静默（无异常抛出）; 用户重启 opencode 后壳代码完全更新

**设计决策**:
- IDLE_RELEASE_SEC=600（用户确认 10 分钟）; REAPER_INTERVAL=5s 不变
- 引擎层竞争窗口防御文案更新（"需先 acquire"→"推理窗口内被卸载，请重试"）
- force_release 保留（前端停止按钮）; ollama 分支语义不变（available 检查）

## 迭代（用户 UI 反馈，2026-08-22）

OCR 空闲倒计时从标题行 Tag 挪至独立行（用途行之后，secondary 12px + 悬浮详情保留）——挤标题行导致第一行超出卡片边框。标题行 OCR 与其他模型统一显示短"已加载" Tag。Playwright 实测: 独立行 y 分离 + 卡片横向溢出 0px。


## 测试充分性复盘（用户复核，2026-08-22）

用户问"测试充分吗"→ 自查发现 2 个缺口:

1. **空闲倒计时是死数字（真缺陷）**: useModels 只在有下载任务时轮询——倒计时为打开页面时的静态快照，不走动; reaper 卸载后卡片停留在"已加载·空闲 9 分"状态失真。修复: 轮询档位化（下载 2s / OCR 加载 10s / 静态停），档位变化才重设计时器（timerMsRef），卸载翻转靠下一轮轮询自然到达。此前只做了静态断言（行存在+零溢出）没测时间行为——教训: 动态数据（倒计时/倒计翻转）必须测"随时间变化"而非只测"初始渲染"
2. **行为断言未沉淀**: 独立行/零溢出此前用临时脚本验证过但未进回归套件 → 沉淀 test_ocr_idle_countdown_live（懒加载→空闲行→走动→release 翻转，35s 真模型端到端）

补测:
- 旧壳兼容性从推理变实证: POST close/acquire → 404 实测确认（壳不 raise 不检查状态码，静默无害）
- e2e 定位陷阱修复: .ant-card 双层匹配（外层板块卡含全部子卡文本）→ filter has_text 匹配两层，first=外层会让"翻转"断言必然假败——取 .last 真内层卡 + 加防走错锚点断言（"BGE-M3" not in）

最终: test/control 53/53（+1 行为锚点）· 生产走动实测（空闲 1s→11s，10s 轮询生效）· tsc/build ✓
