# TTS 串行流水线（前端发送策略 + 节点单 worker）

## §1 背景与目标

**来源**: 试听"首段 12.9s"问题复盘（2026-10-19，默认文案 3 段：35/46/17 字）。

**事件**: 前端分段器切 3 段并发请求；节点 2 worker 下 3 笔抢 2 工位——
段 3 排队 6.4s、并行两笔 GPU 争用（17 字被拖到 9.8s）——首段感知被排队/争用放大。

**痛点**:
1. **在途并发过多**（现有预取深度 2 → 首段发出后立即在途 3 笔）：硬件只有 2 worker（且争用严重），"多备料"变成"抢工位"。
2. **到达序不可控**：多笔同时发出，谁先拿到 worker 由竞争决定（实测 35/17 先过 46）。
3. **并发放大 GPU 争用**：并行请求互相拖慢（rtf 0.7 → 1.3）。

**目标**（按用户确认的模型）:
1. 切分首段 → 立即请求
2. 切分第 2 段 → **+1s** 请求
3. 切分第 3 段起 → **等任意一段返回后**提交下一段（在途维持 ≤2）
4. 节点 TTS 并发 worker **2 → 1**（合成串行，消除争用）

**预期收益**:
- 首段永远第一个被处理（时序明确，无竞争乱序）
- 零 GPU 争用：每段以最快速度（rtf≈0.7）生成
- 生成快于播放（rtf<1）→ 串行流水线不断档
- 内存占用减半（worker 2→1）

## §2 技术方案

### 改动 1: 节点 worker 2 → 1（`services/tts_service.py`）

```python
LOCAL_WORKER_POOL_SIZE = 2 → 1
```

单点常量：`TtsWorkerPool(size=...)` 与 `self._local_sem = threading.Semaphore(...)` 均引用它；
`warm_all` 按 `len(self._clients)` 自动覆盖（注释已承诺"池大小变化时自动覆盖新容量"）。
`_local_sem` 容量随之变为 1（合成全局串行）。

### 改动 2: 前端发送策略（`frontend/src/hooks/useTtsPlayer.ts`）

**保留**（不动）: `ensureSegment`（feeder 游标）、`fetchSeg`（缓存/重试/blobPromise 去重）、
`playSeg`（播放/窗口回收/错误处理）、`stoppedRef`/`abortRef` 停止语义。

**替换**（发送调度）: 现有"预取深度 2 + 播放推进续泵 + 500ms 兜底轮询"→
"初始 2 笔（seg0 立即 + seg1 +1s）+ 返回驱动补段（在途 ≤2）"。

```ts
const INFLIGHT_MAX = 2;
const SECOND_SEG_DELAY_MS = 1000;
const inflightRef = useRef(0);   // 在途请求数（React 闭包安全——禁用局部变量）

const pumpNext = () => {   // 有额度且 feeder 未耗尽 → 发下一段
  if (stoppedRef.current || inflightRef.current >= INFLIGHT_MAX) return;
  const idx = nextFetchRef.current;
  if (ensureSegment(idx) === undefined) return;  // feeder 耗尽
  nextFetchRef.current += 1;
  inflightRef.current += 1;
  console.log(`[tts] seg${idx} 预取发出（在途 ${inflightRef.current}）`);
  fetchSeg(idx, ac.signal)
    .catch(() => { /* 失败仍补段(跳过坏段, 与现有"跳过继续"一致); 错误由 playSeg 统一处理 */ })
    .finally(() => { inflightRef.current -= 1; pumpNext(); });   // 返回驱动补段
};

// start() 内:
nextFetchRef.current = 0;
fetchSeg(0, ac.signal).catch(...).finally(() => { inflightRef.current -= 1; pumpNext(); }); // 首段立即
nextFetchRef.current = 1;
setTimeout(() => { if (!stoppedRef.current) { inflightRef.current += 1; fetchSeg(1, ...)
  .catch(() => {}).finally(() => { inflightRef.current -= 1; pumpNext(); }); } }, SECOND_SEG_DELAY_MS);
```

**语义核对**（用户模型）:
- 第 1 段：`fetchSeg(0)` 立即
- 第 2 段：+1s 发出
- 第 3 段起：初始两笔任一笔 `.finally` → `pumpNext()` 补下一段（在途始终 ≤2）
- `playSeg` 不再调用续泵（移除播放驱动）；500ms `setInterval` 兜底移除

**边缘**:
- stop：`stoppedRef` 拦截 `pumpNext`；`AbortController` 中断在途
- feeder 耗尽：`ensureSegment` 返回 undefined → 停止补段
- 单段重试：`fetchSeg` 内部重试完统一 `.finally`（只算一次在途）

## §3 实现规范

### §3.1 实施步骤

**步骤 1. 节点 worker 2→1**
- 文件: `services/tts_service.py`（1 行常量 + 注释更新）
- 预估行数: +2 / -2
- 验证点: 语法+pyright；`grep` 确认无其他硬编码 2；tts 相关全量测试通过
- 依赖: 无

**步骤 2. 前端发送策略改造（测试先行）**
- 文件: `frontend/src/hooks/useTtsPlayer.ts`（发送调度段替换）
- 预估行数: +40 / -25
- 验证点: 更新/新增 `useTtsPlayer.test.ts`（fake timers）:
  - ① 首段立即发出；② seg1 在 +1000ms 发出；③ 任一笔返回后补下一段；④ 在途 ≤2；⑤ stop 后不再补段；⑥ feeder 耗尽停止
  - `npx vitest run` + `npx tsc --noEmit`
- 依赖: 无

**步骤 3. 全量回归**
- 后端 `pytest tests/ -q`；前端 `vitest run`；pyright/tsc
- 预估行数: 0

**步骤 4. 真机验证 + 提交**
- 节点/主控重启 → 试听默认文案 → 对比首段耗时与日志（段处理顺序 = 段序）
- 预估行数: 0

## §4 验收标准

**功能验收**:
1. 节点仅 1 个 worker（日志"本地预热完成: worker 1/1"）
2. 发送序列日志: seg0 立即、seg1 +1s、seg2+ 随返回补发；在途 ≤2
3. 节点处理顺序 = 段序（1→2→3）
4. 首段完成时间 ≤ 单笔合成时间 + 传输（无排队放大）

**回归验收**:
- 后端全量测试通过（含 tts worker pool/warm/质检）
- 前端全量测试通过（含分段器/播放器既有用例）
- 停止/重试/缓存/窗口回收行为不变

**架构验收**:
- 无新增文件（除测试）
- 发送调度集中在 `start()`（不扩散）

## §5 与现有需求文档的关系

- 与 `2026-10-18-segmenter-v2.md`（分段器）互补：分段规则不变，只改发送/并发。
- 与 `2026-10-18-transport-watchdog.md`（传输看门狗）无关。
