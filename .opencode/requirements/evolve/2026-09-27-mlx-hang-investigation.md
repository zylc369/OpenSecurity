# MLX 挂死成因调查档案（暂停态——等明确提示词继续）

> 状态: 调查暂停（用户指令）; 本文完整保留进度/证据/分析/假说/实验设计
> 关联: 2026-09-27-test77-hang-investigation.md（[77] 挂起档案——两者有交叉: MLX 挂死是 [77] 前置堆积的变体之一）
> 暂停时点: 2026-09-27

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

## 7. 调查恢复入口（用户发明确提示词时）

1. 优先执行 §5 实验 A（10 分钟出结论，决定方向）
2. 按结论走 B（修复）或假说 1 深挖（MLX issue 检索 / 每轮 Metal 资源记账脚本）
3. 与 [77] 档案 §5 路径联动（两问题可能同根）
4. 工具: `/tmp/heartbeat_inject.py` 心跳注入法（用法见 [77] 档案 §2.2）
