# OCR 模型进程内加载（消除 MLX 子进程）

日期: 2026-08-22
状态: ✅ 已完成（8 步 + 用户复核触发的并发架构返工，最终形态见下方"并发架构返工"）
前置: `2026-08-16-deps-layering-and-local-ocr.md`（当时选 spawn MLX 子进程方案——该文档的"内存释放确定性/加载慢需复用"两个理由经 2026-08-22 实测推翻）

## 并发架构返工（用户复核触发，2026-08-22 第二轮）

用户三条约束复核发现初版全串行不满足"使用并发"。返工过程三层发现（全部实测）:

1. **MLX Metal stream 是 thread-local**（libmlx.dylib C++ 层）: 模型在 A 线程 load、B 线程 generate → `RuntimeError: There is no Stream(gpu, N)`；多 MLX 线程并存时 stream 初始化非确定竞争（双线程 1/2 成功、三线程 2/3）。旧实现串行场景未崩纯因 asyncio.to_thread 恰好复用同池线程（潜伏炸弹）
2. **解法 = 进程级唯一 _MlxWorker 线程**: 所有 MLX 交互（load/模板/generate/unload）经单常驻线程 FIFO 执行，stream 一次初始化终身复用；unload→load 循环同线程实测稳定
3. **测试 patch 层次铁律**: 必须 patch 引擎 `_infer_impl`（worker 执行层）。patch 公开方法 `infer_serialized` 会让真推理绕过 worker 落到池线程 → 假崩（三版实现的"崩溃"全是此测试 bug，worker 方案初版即正确）

最终并发架构:
- 使用并发: extract 不持 lifecycle 锁——预处理（base64+PIL）并行重叠，generate 进 worker FIFO（GPU 串行是 MLX 物理上限）
- 三动作互斥: load/generate/unload 汇聚 worker FIFO——卸载排在在途推理后，加载与推理互斥
- 状态变更: _lifecycle_lock（acquire/close/force_release/reaper）独占
- 单飞/失败重载语义不变

最终测试: 单测 65/65（+2: 推理在途 acquire 复用不阻塞 / force_release 等推理完成）· 六套全绿 ·
生产 3 路并发 extract 0.30s 全成功（预处理重叠 + worker 串行），各自正确识别

## 第四轮补测（用户复核测试充分性，2026-08-22）

- 上轮验证缺陷（被用户"测试充分吗"问出）: 生产验证全部发生在 90s 心跳宽限窗口内——keeper TTL 16:38 到期退群后，16:55 手动拉起的控制台 16:57:07 按设计自杀（当前 opencode 插件早于心跳机制诞生不发心跳，keeper 是唯一心跳源）。教训: 涉宽限/超时的验证必须观察到窗口之外
- 补单测 3 个: hardware_summary 充足路径（monkeypatch psutil）/ 不足路径（ok=False + reason 含可用与需求值）/ get_model_assets loaded 三元语义（embedder=调用进程真实态而非硬编码; reranker 不再复用 embedder 标志）
- 补跑 e2e_real 6/6（上轮 models API 变更后漏跑）
- 生产: keeper 重启（72912）+ 控制台 72974 存活 7min+（超宽限验证）; OCR e2e 后 idle 自动卸载复验

## 第三轮返工（用户复核释放边界 + 模型板块重构，2026-08-22）

**释放边界审查（用户问"是否考虑到所有边界"）——发现 1 个真 bug**:
- force_release 在"加载完成→等待者置 READY"窗口抢到锁 → 等待者无条件置 READY → 引擎已空却显示 ready → acquire 快路径永不重载（永久损坏）。修复: 等待者仅在 state==STARTING 时置 READY。回归锚点: test_ocr_force_release_race_with_load（含竞态后自愈验证）
- 补测 MCP SIGKILL 兜底: 真子进程 acquire→kill→reaper 清引用→30s 窗口→自动卸载（并锚定"清引用后仍等满空闲窗口"的热复用语义）
- 设计语义（非 bug）: client 活着但不识图 → 不释放（lifespan 持有即使用中）

**模型板块重构（用户 4 项指令全部落地）**:
- 删类型标签（向量化/重排序/OCR——与用途行重复且导致长行溢出）; purpose 行升级为主视觉（主题蓝 #1677ff）
- 逐模型硬件行废弃（三模型 min_free_gb 同为 4.0 导致三行重复）→ 板块标题旁整体汇总行: "✓ 内存 19.3GB / 需 12GB"（总需求=已缓存模型 min_free_gb 之和，Tooltip 说明口径）
- 修 loaded 显示 bug: reranker 原复用 embedder 就绪标志（懒加载未加载却显示"已加载"）→ is_reranker_loaded() 真实态
- 进程页删 ocr_mlx 条目（in-process 后无独立进程; 引用计数并入 OCR 模型卡"运行中 · N 引用"）

**连带发现并修复（本轮最大意外收获）**:
- vite.config.ts `import { react }` 命名导入错误（IPC 化时引入）→ **前端自 8/17 起从未成功构建过**（一直靠 dev 模式运行，dist 停留老版本）→ 修复 default import + 重建 dist。此前 e2e 过测的是老 dist
- mlx-env 删除（699MB 磁盘回收）

测试: 单测 70/70（+2 释放边界）· test/control 44/44（断言随 UI 契约更新）· 集成 5/5 · TS 10/10 · tsc ✓

## 实施结果记录

- 测试: 单测 63/63（OCR 组 6 用例含并发串行化实测）· 集成 5/5 · TS 10/10 · e2e_real 5/5 · test/control 44/44 · tsc 零错
- 修复的执行期 bug: ① acquire STOPPING 死代码分支（持锁等持锁者变更——改为不可达防御断言）② force_release 丢 ollama 分支 ③ 发起者加载失败后状态停 starting（搭车者 cleanup 覆盖不到发起者——失败路径自清）
- 查缺补漏（IPC 化遗产测试第三批，与 OCR 无关一并修复）: test_control_backend.py 三个已退役机制测试类删除 + HF 离线 env 对齐; test_embed_client.py 全文件重写（embed_client 模块 IPC 化时已删）; test/control/ 从 17 failed → 44 passed
- 生产验证: 孤儿 7352 已杀（回收 1.3GB）+ .ocr-mlx.pid 删除; 新控制台 63449; acquire 2.2s → extract 0.74s 正确识别 → close → reaper 36s 自动卸载; footprint 3686.4 → 4915.2 → 3686.4 MB（加载前后分毫不差）
- 测试铁律（踩坑）: OcrService 测试禁用 fastapi.testclient.TestClient（每请求独立事件循环 → asyncio.Lock 跨循环误报 503）——必须同循环（asyncio.run 直调或 AsyncClient+ASGITransport）
- 依赖: mlx-vlm 进 detect_py_deps（platforms=darwin; linux 安装清单正确排除——mlx 无 linux wheel）

## §1 背景与目标

**来源**: 2026-08-22 实验复盘（mlx-env 与主 venv 实测）推翻了子进程方案的两个存在理由：

| 当年理由 | 2026-08-22 实测 |
|---|---|
| "进程内卸载后内存不归还 OS" | ❌ `mx.clear_cache()` 归还 92%（1.2GB 权重全清）；推理足迹稳态 380MB 两轮一致无泄漏 |
| "重新加载慢，需孤儿复用" | ❌ safetensors mmap + NVMe = 0.3s 加载、0.6s 推理（396 tok/s） |

子进程方案的税（pid 文件、孤儿收养、健康探测、随机端口、进程组管理、"孤儿无限空跑"缺口——7352 空跑 2 天占 1.3GB）全部可消除。

**用户拍板的方案约束**（全文约束，违反即返工）:
1. 模型加载到控制台进程内
2. 线程安全：同一时刻只允许一个 加载/推理/卸载 在跑；**三者共享同一把锁**
3. 并发请求等待（串行推理）
4. OOP，不要函数式
5. 边界条件防御
6. 全路径日志可排查
7. 逻辑抽象

**已接受的代价**（用户知情）:
- 推理足迹 ~380MB 常驻（首次 OCR 使用后）
- MLX 原生段错误会带走控制台（自愈闭环兜底）
- generate 无中断 API：推理不设硬中断，`max_tokens=4096` 上界（400tok/s 下 ≤20s）+ 超时日志

## §2 技术方案

### 架构（引擎/编排分离）

```
routes/ocr.py ──→ OcrService（编排层: 单锁 + 状态机 + 引用计数 + reaper）
                     ├─ _MlxEngine    （进程内 MLX: load/infer/unload，持 model+processor）
                     └─ _OllamaEngine （win/linux: Ollama HTTP，保持原样）
```

### 锁语义（用户约束 #2/#3 的精确实现）

单把 `asyncio.Lock` 串行化三类操作，**推理持锁**（并发 extract 排队 = 串行推理）:
- `acquire`: 持锁 → idle 则加载（`asyncio.to_thread` 跑同步 load，不卡事件循环）→ ready
- `extract`: 持锁 → 校验 ready → `to_thread` 推理（MLX 非线程安全，锁保证单线程触达）
- 卸载（reaper/force_release）: 持锁 → `del 模型 + mx.clear_cache()`（35ms，直接跑）

事件循环永不被 MLX 同步调用阻塞（health/前端轮询不受 OCR 影响）。

### 状态机（保留）

```
idle → starting → ready → stopping → idle
starting 并发 acquire 等同一 asyncio.Event（单飞不重复加载）
stopping 期间 acquire 等停止完成再重启
```

### 生命周期（保留语义，实现更换）

```
acquire(client_id) → 引用+1（无模型则加载）
extract            → 持锁推理（刷新活跃）
close(client_id)   → 引用-1
reaper 5s: clients 空 AND 空闲 >30s → unload（del + clear_cache）
MCP SIGKILL 兜底: psutil 检测 client 死亡 → 清引用（保留）
```

### 卸载实现（实测数据支撑）

```python
del self._model, self._processor
mx.clear_cache()      # 归还 1.2GB 权重页（92%）
gc.collect()
```

### 推理调用（mlx-vlm 0.6.13 实测 API）

```python
from mlx_vlm import load, generate
from mlx_vlm.prompt_utils import apply_chat_template
model, processor = load(snapshot_dir)                       # 0.3s
prompt = apply_chat_template(processor, model.config, text, num_images=1)
result = generate(model, processor, prompt, image, max_tokens=4096, verbose=False)
result.text                                                 # GenerationResult → .text
```

### 删除物

- `.ocr-mlx.pid` 全部读写（4 处）+ 生产文件 + 孤儿进程 7352
- MLX_ENV_PYTHON / mlx-env 检测与安装（model_assets 下载 worker 的 venv 分支）
- `_adopt_orphan/_wait_mlx_ready/_probe/_free_port/_subprocess 族` 全部子进程管理代码
- OcrStatus.mlx_env_ready → mlx_ready（语义: 主 venv 可 import mlx_vlm）

### 依赖变更

- `detect_py_deps.py` 加 `mlx-vlm`（platforms=("darwin",)，arm64 判定在 description 说明）——环境准备统一走依赖检测，不再有私建 venv 路径

## §3 实现规范

- 规则 9: 引擎类 + dataclass（OcrStatus/HolderInfo/GenerationStats），无裸 dict
- 引擎失败语义: MlxEngine.load 失败 → RuntimeError（带用户可读原因: 环境缺失/模型未缓存/底层异常）→ OcrService 记 error + 回 idle
- 惰性 import: mlx_vlm 仅在 MlxEngine 首次 load 时 import（非 mac 平台不炸模块加载）
- 日志（services.ocr）: 加载开始/完成（耗时+footprint 前后）、推理（耗时+tokens）、卸载（footprint 前后）、reaper 触发、并发等待、异常全路径
- footprint 口径: vmmap Physical footprint（与进程页同口径）；工具函数 2 处暂复制（process_registry/ocr_service），第 3 处出现时收口

### §3.1 实施步骤

```
1. 引擎层 services/ocr_engines.py
   - 文件: services/ocr_engines.py（新增）
   - 内容: _MlxEngine（惰性 import mlx_vlm / load / infer / unload，GenerationStats dataclass）
           + _OllamaEngine（HTTP，从 ocr_service 平移）
   - 预估行数: ~160
   - 验证点: compile + 真加载/推理/卸载冒烟（独立脚本调 MlxEngine 三方法，footprint 前后对比）
   - 依赖: 无

2. 编排层 ocr_service.py 重写
   - 文件: services/ocr_service.py（重写，用引擎）
   - 内容: OcrService 单锁编排 + 状态机 + 引用计数 + reaper + status/holders；
           删除全部子进程/pid 文件/孤儿代码；OcrStatus.mlx_ready 改名
   - 预估行数: ~230
   - 验证点: compile + TestClient 走 routes 真加载→推理→close→force_release 全链
   - 依赖: 1

3. 消费方适配
   - 文件: services/model_assets.py（mlx-env 检测/安装删，改 import 检测）
           services/detect_py_deps.py（+mlx-vlm 条目）
           services/process_registry.py（ocr_mlx 条目 in-process 化）
           routes/ocr.py + mcp-servers/ocr/server.py（注释清理）
   - 预估行数: ~120
   - 验证点: compile 全过 + /api/ocr/status 字段新版 + /api/processes ocr 条目正常
   - 依赖: 2

4. 前端适配
   - 文件: frontend/src/（mlx_env_ready → mlx_ready 字段、进程页 pid 空显示）
   - 预估行数: ~30
   - 验证点: tsc 零错误
   - 依赖: 3

5. 残留清零
   - 动作: grep .ocr-mlx.pid / mlx-env / _adopt_orphan / MLX_ENV_PYTHON 全仓零业务残留;
           test/control/test_frontend_e2e.py:190 注释更新（mlx-env 检测语义已变）
   - 验证点: grep 输出空（需求文档/测试预期除外）
   - 依赖: 3

6. 测试补全
   - 文件: tests/test_control.py（+OCR 组: mock engine 的状态机/并发单飞/引用计数/释放窗口 + 真 e2e: 真加载推理 footprint 断言 + 3 路并发 extract 串行化）
   - 预估行数: ~180
   - 验证点: 单测全绿（含新增 ≥8 用例）
   - 依赖: 2

7. 全量回归
   - 验证点: 单测/集成/TS/e2e_real/前端 pytest(test/control) 五套全绿
   - 依赖: 6

8. 生产切换
   - 动作: 杀孤儿 7352（回收 1.3GB）→ rm .ocr-mlx.pid → 重启控制台 → MCP 薄壳真链路 acquire→extract→close → 30s 后 unload footprint 验证
   - 验证点: control.log 见加载/推理/卸载三段日志; 控制台 footprint 回落
   - 依赖: 7
```

## §4 验收标准

**功能验收**:
- [x] 控制台进程内加载 GLM-OCR（无子进程、无 pid 文件、无端口）
- [x] acquire→extract→close MCP 真链路可用，识别正确
- [x] 并发 acquire 只加载一次；并发 extract 串行（总耗时 ≈ 单次和）
- [x] 引用归零 + 30s → unload，footprint 回落（权重 1.2GB 清）
- [x] force_release 立即卸载
- [x] 非 ready extract → 明确错误
- [x] win/linux Ollama 分支行为不变

**回归验收**:
- [x] 五套测试全绿
- [x] 生产控制台切换后: MCP OCR 检索、knowledge/events、前端全正常

**架构验收**:
- [x] 单锁语义（加载/推理/卸载共享）——并发测试证明
- [x] OOP（引擎/编排分离，dataclass，无裸 dict 传递）
- [x] 全路径日志（加载/推理/卸载/reaper/异常）
- [x] .ocr-mlx.pid、mlx-env、孤儿机制全仓零残留

## §5 与现有需求文档的关系

- `2026-08-16-deps-layering-and-local-ocr.md`: 其"spawn MLX 子进程 + 孤儿复用"方案被本文取代；该文档不再作为 OCR 架构的事实源
- `progress-2026-08-16-deps-ocr.md` 整改 25/27 的进程页/内存口径描述中 ocr_mlx 子进程相关部分以本文为准
