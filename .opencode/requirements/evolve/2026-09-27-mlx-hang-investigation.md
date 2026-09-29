# MLX 挂死成因调查档案（已结案）

> 状态: **已结案（2026-09-29）**——假说 2 成立并修复，实验 A/B 完整裁决
> RSS 慢泄漏深挖（实验 C/D，2026-09-29）见 §9
> 关联: 2026-09-27-test77-hang-investigation.md（[77] 挂起档案——MLX 挂死是
> [77] 前置堆积的变体之一，本结案对其有缓解意义）
> 调查期: 2026-09-27 立案 → 暂停 → 2026-09-29 恢复并结案

---

## 1. 问题定义

同一进程内高频 load/unload GLM-OCR 真模型（测试套件秒级连续 ~10+ 轮全量循环）之后，下一次模型加载中的 `mx.eval(model.parameters())`（mlx_vlm/utils.py:1167，将 mmap 权重物化到 GPU buffer）**永久挂死**——GPU 命令无完成回调，线程卡在 Metal C 层。

## 2. 铁证（sys._current_frames() 心跳线程抓取）

```
model-worker-glm-ocr 线程栈（挂死时刻）:
  threading run → model_lifecycle._run（worker FIFO 取任务）→ mlx_vlm load_model
  → mx.eval(model.parameters())  ← 永久卡死（无超时、无异常、无日志）
连带: 3 个推理池线程 event.wait()（等加载完成事件——永不到来）
      MainThread asyncio select（等全部完成）→ 全进程挂死
```

## 3. 已确凿的事实

| # | 事实 | 依据 |
|---|------|------|
| 1 | **不是并发导致**——所有 load/unload/infer 经同名 worker（"glm-ocr"）的 FIFO 单线程物理串行 | 架构保证（ModelWorkerRegistry 按名共享）+ 挂死时刻心跳快照仅一个线程在 mx.eval |
| 2 | 少量循环稳定 | ocr_engines.py 历史实测注释（"unload→load 循环实测同线程稳定"——当年为个位数循环） |
| 3 | 大量循环后概率性挂死 | 本轮实测：全量测试套件（~10 轮循环）后挂；单测/小组合不挂 |
| 4 | 挂点在 GPU 物化（mx.eval），非加载 I/O / 非 Python 锁 | 心跳栈 |
| 5 | 挂死时进程内存充足（78% free）、CPU 近零（GPU 等待不烧 CPU） | heartbeat / ps |
| 6 | SIGALRM / faulthandler 均无法打断（全卡 C 层） | 实测（setitimer 180s 到期不触发） |

## 4. 两个候选机制（假说，未证伪）

### 假说 1：MLX/Metal 库级资源泄漏
每轮正确 unload（`del 权重 + mx.clear_cache() + gc.collect()`）后，Metal 层仍有资源缓慢累积（command queue 引用 / 驱动侧 buffer 记账），最终 `mx.eval` 的 GPU 命令无完成回调。
- 归属: MLX 库 / Apple GPU 驱动
- 生产风险: 低但非零（OCR 空闲卸载 + 远程降级/恢复真实触发 unload→load 循环——但频率天级非秒级）

### 假说 2：测试代码缺陷（未保证释放）
`OcrService._reset_for_tests()` 丢弃旧实例时**不保证先 force_release**——部分测试路径漏卸载，旧模型权重靠 GC 慢释放，Metal buffer 堆积直至挂死。
- 归属: **我们的测试基建**（生产单例不 reset，无此路径）
- 若成立则生产无此问题

**诚实声明**：挂死点在 MLX 的 C 层，Python 层工具看不到 Metal 内部状态——两假说当前均无法直接证实，需实验区分。

## 5. 区分实验（已设计未执行——等裁决）

### 实验 A（隔离假说 1，~10 分钟）
脱离测试套件的最小脚本：单线程严格 `load→（确认 unload 完成）→load` ×50，观察第几轮挂。
- 挂 → 假说 1 成立（库级，即使正确释放也累积）
- 50 轮不挂 → 假说 1 基本排除，指向假说 2

### 实验 B（验证假说 2，~15 分钟）
修 `_reset_for_tests`（reset 前对旧实例先 force_release）+ 全量跑测试。
- 不再挂 → 假说 2 成立（修复即收尾，且可能同时缓解 [77]——MLX 挂死是 [77] 前置堆积变体）

## 6. 120s 超时兜底机制（已实施保留——本节回答"它解决什么问题"）

**代码位置**: `services/model_lifecycle.py` `ManagedModel.LOAD_WAIT_TIMEOUT_SEC = 120.0`；`ensure_loaded()` 与 `release()` 的 `event.wait(timeout=...)` 两处。

**解决什么**:
1. **挂死→可见异常**: 无论成因是假说 1 还是 2，一旦底层运行时（MLX Metal / torch MPS）挂死，等待加载的线程在 120s 后收到 `RuntimeError("[模型名] 模型加载等待超时——底层运行时挂死（Metal/MPS 疑似死锁）")`，带模型名可定位——替代"永久挂起零信息"
2. **生产防御价值（真实场景）**: 远程降级触发本地预热、远程恢复触发卸载、OCR 空闲卸载后再加载——这些生产路径都会执行 load；若生产环境出现 Metal 挂死（假说 1 的低概率），120s 后请求方拿到明确错误（可重试/可告警），控制台进程不死、其他模型不受影响
3. **测试价值**: 挂死场景从"测试进程永久卡死（需外部 kill）"变为"该测试失败 + 错误信息含模型名"

**明确不解决**: 成因本身（资源泄漏/堆积照旧发生）；它是结果层防御，不能替代成因修复（若假说 2 成立，正确修法是 reset 前保证释放）。

**验证**: `test_load_hang_timeout` 单测（load_fn 永不完成 → 1s 注入超时 → 断言异常语义）——test_model_lifecycle 14/14 含此项。

## 7. 结案记录（2026-09-29，实验 A/B 执行完毕）

### 实验 A 结果（假说 1 排除）

最小脚本严格循环 load→确认 unload→load ×50（心跳线程观测、挂死自证
退出机制）: **50 轮全部完成未挂**。附带观测: 每轮 unload 后 RSS 慢泄漏
~2MB/轮（50 轮 +94MB）——资源缓慢累积存在但**不足以致挂**; 致挂需要
GB 级堆积（与假说 2 的整份权重泄漏形态吻合）。脚本:
`/tmp/.../mlx_exp_a.py`（结构: 心跳 15s 采样 + 同位置 180s 判死 + 
faulthandler 全栈 + exit 42）。

### 实验 B 结果（假说 2 成立 + 修复验证）

**缺陷实锤**: `OcrService._reset_for_tests` 直接 `cls._instance = None`
丢弃旧实例——loaded 实例的 MLX 权重（~1GB）靠 GC 慢释放; 测试用例
惯用法 `_reset_for_tests() or OcrService()` 每例新建，全量套件 ~10 轮
reset → Metal buffer GB 级堆积 → `mx.eval` 概率性永久挂死。

**修复**（services/ocr_service.py）: reset 内置释放屏障——
1. `release_sync()`（排队卸载，推理在途则 FIFO 等待）
2. 仅 MLX 后端轮询 `status().state == "idle"`（30s 上限，超时抛
   RuntimeError 指向挂死兜底; ollama 后台无进程内权重且 status 恒
   ready，跳过轮询防误报）
3. 返回 None 保持 `reset() or OcrService()` 每次新建干净实例的语义

**验证**: 全量 test_control **87/87 不挂**（历史挂死场景）。
**生产结论**: 生产单例从不 reset——此路径仅测试基建触发，**生产无此
问题**（假说 2 归属判定正确）。

### 修复过程的两个回归教训（已在实施中修正）

1. 屏障初版返回旧实例 → `or OcrService()` 短路复用旧实例 → 测试串扰
   两红（force_release 互斥 / 坏输入防御）→ 改回返回 None 后全绿
2. `import time` 疏漏 → NameError 两红 → 补 import

### 120s 超时兜底的去留

**保留**——防御对象独立于本成因（任何 Metal/MPS 层挂死，含未来未知的
库级问题——实验 A 的慢泄漏提示库并非完美）; 与本修复是互补关系
（成因修复 + 结果层防御）。

## 8. 历史章节（立案期原文，供追溯）

---

## 9. RSS 慢泄漏深挖（实验 C/D，2026-09-29）

背景: 实验 A 附带观测"每轮 unload 后 RSS +~2MB"，本次专项复现与归因。

### 9.1 实验 C（复现 + 量化，50 轮）

方法: 最小脚本 50 轮 `warm_up_sync()` → `release_sync()` → `gc.collect()`，
每轮采样进程 RSS 与 Metal 三指标（active/cache/peak），终态
`gc.collect() + mx.clear_cache()` 后再测。

实测（RSS）: 首轮卸载后 718.9MB → 第 50 轮 1125.0MB，**斜率 8.29MB/轮**
（早期 ~20-40MB/轮更快，中后期 ~5MB/轮）。终态 clear_cache 后 1125.0MB
**不回落**——真泄漏（非可清缓存）。GPU 侧 active/cache 恒 0（干净）；
**peak 单调上升 1247 → 2494MB**（分配峰值逐轮变大）。50 轮不挂。

### 9.2 实验 D（归因，tracemalloc + 对象计数）

方法: 20 轮循环，第 3 轮与第 13 轮间对比 tracemalloc 快照（traceback 聚合）
+ `gc.get_objects()` 类型计数。

结果: Python 层增长仅 KB 级（top 项 ~52KB；对象计数 tuple +453 等）——
远无法解释 8MB/轮。**增长在 C 扩展 / 非 Python heap 侧**（MLX/Metal
C++ 层内部分配——tracemalloc 盲区），与 peak 单调上升吻合。

### 9.3 结论与生产影响

- 该慢泄漏为**库级**（MLX/Metal C++ 侧），应用层无修复手段（卸载路径已含
  release + gc + clear_cache 全量释放）。
- 生产影响评估: 加载/卸载频率天级（空闲卸载/远程切换），量级 ~8MB/轮
  → 月级累计 ~百 MB 级; 有 120s 挂死兜底（§6）与进程重启兜底——
  **维持"留档关注"**，不新增代码防御。
- 若继续深挖: 用 Instruments / malloc_history 对 C 侧分配追踪（未做）。

### 9.4 观测脚本结构（可重建）

- **实验 C**: 心跳/看门狗线程（同 §10 工具形态，防挂死）；主循环
  `warm_up_sync()` → `release_sync()` → `gc.collect()` → 采样
  `psutil.RSS` + `mx.metal.get_active_memory / get_cache_memory /
  get_peak_memory`；终态 gc + clear_cache 复测；输出 CSV
  `(轮次,RSS,active,cache,peak,load_s,release_s)` 与末行斜率。
- **实验 D**: 同循环；`tracemalloc.start(15)`，第 3/13 轮 `take_snapshot()`
  对比 `compare_to(..., "traceback")[:15]`；`Counter(type(o).__name__ for o
  in gc.get_objects())` 差值取 top。
