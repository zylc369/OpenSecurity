# 需求文档：TTS 本地合成双 worker 并行（worker 池化）

> 状态: Phase 2 草稿
> 来源: 2026-10-17 实机验收复盘（"停 = 段 N+1 处理时长 − 段 N 播放时长"；串行单 worker 是
> 处理时长的硬底）——用户批准 B/C/D，C/D 已完成，本批为 B。
> 配套: `2026-10-17-tts-prefetch-depth2-queue-ui.md`（C——深度 2 为并行供料，已完成）

---

## §1 背景与目标

### 1.1 背景

- 本地合成走单 worker 子进程（`TtsWorkerClient` 持单 `_proc`，stdio 一问一答），
  TtsService 侧 `_local_sem = threading.Semaphore(1)` 串行化整个本地域。
- 段间停顿的临界场景（26 字段播 8s 后接 91 字段处理 14.3s）在"处理 > 播放"下必停；
  串联单机吞吐无法解——**需要两段并行合成**（区分调度粒度：深度 2 已把请求提前
  送达，等待的是"能同时开工的第二个 worker"）。
- 内存可行性：CosyVoice3 8bit MLX 模型 ~1.3G/实例；MacMini M4 16G 节点当前
  bge-m3(4.3G)+reranker(2.1G)+OCR(1.2G)+CosyVoice(1.3G) ≈ 9G——双 worker 后
  ≈ 10.3G（真机验收监控，边界留余）。

### 1.2 目标

| # | 目标 | 验收口径 |
|---|------|---------|
| B1 | 本地合成域支持 2 段并行（双 worker 池） | 单测：并发两请求进入不同 worker（真并发非排队） |
| B2 | 单请求行为/协议全兼容 | 现有 tts 测试全过；`_worker.request` 接口不变 |
| B3 | 真机吞吐提升实证 | 节点部署后并发两段总耗时 ≈ max(A,B) 而非 A+B（≥1.33x 吞吐） |

### 1.3 非目标

- 不做动态池大小/自动伸缩（固定 2——内存与 GPU 的实测平衡点）
- 不改 worker 脚本协议（`scripts/tts_worker.py` 零改动——并发=多进程）
- 不做"段内拆分并行"（拼接韵律伪影风险）

---

## §2 技术方案（`services/tts_service.py`）

### 2.1 新类 `TtsWorkerPool`（文件内，紧随 `TtsWorkerClient` 之后）

```python
LOCAL_WORKER_POOL_SIZE = 2  # 本地并行 worker 数（内存/GPU 平衡点）

class TtsWorkerPool:
    """并行 worker 池: N 个独立 worker 进程 + 空闲取用（阻塞排队=背压）。

    接口与单 TtsWorkerClient 相同（request/alive/shutdown）——调用方与
    测试 mock 零感知（`svc._worker.request` patch 点不变）。
    """

    def __init__(self, size: int = LOCAL_WORKER_POOL_SIZE) -> None:
        self._clients = [TtsWorkerClient() for _ in range(size)]
        self._free: "queue.Queue[TtsWorkerClient]" = queue.Queue()
        for c in self._clients:
            self._free.put(c)

    def request(self, payload: "dict[str, Any]") -> WorkerResponse:
        client = self._free.get()          # 无空闲则阻塞（天然背压）
        try:
            return client.request(payload)
        finally:
            self._free.put(client)

    @property
    def alive(self) -> bool:
        return any(c.alive for c in self._clients)

    def shutdown(self) -> None:
        for c in self._clients:
            c.shutdown()
```

- 每个 `TtsWorkerClient` 的空闲释放看门狗独立生效（语义不变：闲者自清，
  下次请求冷启动自愈）。
- 单测可注入小 `size`/`_idle_check_interval_sec`（沿用现有注入点）。

### 2.2 TtsService 接线（两行 + 注释）

- `self._local_sem = threading.Semaphore(1)` → `threading.Semaphore(LOCAL_WORKER_POOL_SIZE)`
  （注释更新：本地域并发度=池大小；本地路径与 fallback 统一入口语义不变）。
- `self._worker = TtsWorkerClient()` → `TtsWorkerPool()`。
- `TtsWorkerClient.request` 的 docstring（"调用方持 TtsService 锁——串行天然成立"）
  更新为"单 client 内一问一答由池取用语义保证（同一时刻至多一个调用方）"。
- `_synth_local` / `_reset_for_tests` / watchdog 相关调用点零改动（池同名接口）。

### 2.3 并发安全与既有语义

- 两个合成线程各取一个 worker（独立 stdio 管道），互不交错；
- `_synth_qc_local` 的重试循环保持"单段内串行尝试"（重试不并行——质检/交付序敏感）；
- 远程 fallback 排队语义不变（sem 容量 2：最多 2 个 fallback 并行合成）。

---

## §3 实现规范

### 3.1 实施步骤

**步骤 1. TtsWorkerPool + 单测**
- 文件: `services/tts_service.py`（~35 行）、`tests/test_tts_worker_pool.py`（新）
- 预估行数: ~35 + 测试 ~80
- 验证点: 单测——① 两并发 `request` 进入两个不同 client（用"记录并发的桩 client"
  断言并发峰=2）；② 第三个请求在前两个返回前阻塞（排队）；③ `alive`/`shutdown`
  语义；④ 接口与 `TtsWorkerClient` 一致的 mock 兼容性（patch `pool.request` 生效）
- 依赖: 无

**步骤 2. TtsService 接线**
- 文件: `services/tts_service.py`（~5 行）
- 预估行数: 5
- 验证点: 现有 `test_tts_service/test_tts_qc_flow/test_tts_lock_split/test_tts_watchdog`
  全过；`_local_sem` 容量断言（若测试触及）；pyright 0
- 依赖: 步骤 1

**步骤 3. 并发行为单测（服务级）**
- 文件: `tests/test_tts_worker_pool.py`（追加）
- 预估行数: ~60
- 验证点: 两个并发 `svc.synthesize(...)`（mock 池下层 worker 带 0.2s 延迟）总耗时
  < 串行和 × 0.75（并发峰=2 的行为实证）
- 依赖: 步骤 2

**步骤 4. 真机吞吐验收（节点部署后，待办项）**
- 前置: 节点 `git pull` + 重启（用户侧）
- 方法: 主控并发两个 `/api/tts`（不同文本）——节点侧日志交叉（两 worker）+
  总耗时 ≈ max 而非 sum；同时观察节点内存（活动监视器/`vm_stat`）
- 验证点: 吞吐比 ≥ 1.33x；峰值内存 < 15G；**无内存压力告警**（swap 增长可见即回退决策点）
- 依赖: 步骤 2 + 节点部署

**步骤 5. 回归 + 记录**
- 验证点: 后端全量快集 + pyright 0/0/0
- 依赖: 全

### 3.2 改动文件清单

| 文件 | 类型 | 预估行数 | 步骤 |
|------|------|---------|------|
| `services/tts_service.py` | 修改 | ~40 | 1/2 |
| `tests/test_tts_worker_pool.py` | 新增 | ~140 | 1/3 |

### 3.3 编码规则

- 池类注释说明"为什么 2"（内存/GPU 平衡点与实测依据）与"接口即 TtsWorkerClient 超集"；
- 不改 `tts_worker.py`（协议稳定性是本批的显式约束）。

---

## §4 验收标准

### 4.1 功能验收

- [ ] 并发两请求真并行（单测：并发峰=2；服务级：总耗时 < 串行和 × 0.75）
- [ ] 单请求路径行为不变（现有 tts 测试全过）
- [ ] 空闲释放/看门狗语义保持（各 worker 独立）

### 4.2 回归验收

- [ ] 后端快集全绿；pyright 0/0/0
- [ ] 前端不受影响（无接口变化——`/api/tts` 契约不变）

### 4.3 架构验收

- [ ] 池接口 = `TtsWorkerClient` 同名超集（测试 mock 兼容，无消费方改动）
- [ ] 节点与主控共享代码（部署后两侧同时获得并行）

### 4.4 待办验收（节点部署依赖）

- [ ] 真机吞吐 ≥1.33x 与内存 <15G（节点 `git pull`+重启后补测）

---

## §5 与现有需求文档的关系

- 配套 C（`tts-prefetch-depth2-queue-ui`，已完成）：C 供料（请求提前到队列）+ B 并行
  才构成"停段治理"的完整闭环
- 与 `tts-remote-chain-trim` 无冲突（不同层）
- 与 `tts-lock-split`（本地域信号量语义）演进关系：容量 1→2，域划分不变
