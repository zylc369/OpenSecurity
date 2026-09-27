# [77] 测试挂起调查档案（暂停态——等明确提示词继续）

> 状态: 调查暂停（用户指令）; 本文完整保留进度/证据/分析过程，供后续继续
> 关联: 2026-09-26-backend-oop-refactor.md / progress 同名文件
> 暂停时点: 2026-09-27

---

## 1. 问题定义

`tests/test_control.py` 全量顺序跑（79 测试）在 `[77] knowledge/events 路由`（TestClient(create_app()) + fake 注入形态，进程内直跑）**永久挂起**（8 分钟零进展，不报错不退出）。单独跑该测试、少量前置+该测试、二分脚本（subprocess 内跑前缀+目标）全部通过。

## 2. 调试时间线（按序，含所有关键证据）

### 2.1 第一阶段：常规排查（未定位）

- 卡点不固定：见过第 73/76/77 个测试（顺序被我中途调整过一次，已还原）
- macOS `sample` 采样：主线程有时在 `kevent`（等 IO），有时 99.7% 跑 Python 字节码（活锁假象）
- `SIGALRM` 看门狗（`signal.setitimer` 180s）：**到期不触发** → 证明主线程卡在 C 层系统调用（Python signal handler 只在字节码间隙调度）
- `faulthandler.dump_traceback_later(300)`：**到期不打印** → 同上佐证
- lsof：进程持有 PIPE fd ×2（fd 4/47）、mlx.metallib fd ×3

### 2.2 第二阶段：`sys._current_frames()` 心跳线程（决定性工具）

**工具**（`/tmp/heartbeat_inject.py`，仍在）：daemon 线程每 5s 把全线程 Python 栈写入 `/tmp/hb_stacks.txt`。不持锁、不受 C 层阻塞影响、无需特权。

**铁证 A（第一轮心跳，卡点在 OCR 测试）**：
```
model-worker-glm-ocr:  mlx_vlm/utils.py:1167 load_model → mx.eval(model.parameters())  ← 永久卡死
asyncio_0/1/2（推理池线程）: model_lifecycle event.wait()  ← 等永不到来的加载完成事件
MainThread: test_ocr_extract_serialized 的 asyncio.run → select  ← 等全部完成
```
→ **修复 1**：ManagedModel 加载等待加 120s 超时兜底（挂死转可见 RuntimeError）+ 单测 test_load_hang_timeout。

**铁证 B（第二轮心跳，加了子进程心跳注入后，卡点在 [77]）**：
```
MainThread（测试进程）: httpx 同步 _sock.recv  ← 等一个 HTTP 响应，永不返回
  （栈为 httpcore/http11 _receive_response_headers → sync.py read → sock.recv）
测试进程的 server.py 子进程: MainThread=uvicorn loop select（空闲等待）、
  model-worker-bge-m3=queue.get（空闲）、asyncio_0=work_queue.get（空闲）→ 子进程完全空闲
测试进程线程清单: 10× model-reaper-glm-ocr（每 OcrService 实例一个，泄漏但不挂）
  Thread-1 (_unix_accept_loop)（测试进程 IPC 桥存活）
测试日志伴随: 反复出现 "IPC serve: 上游 TCP 不可达（frontend_ports 未注册端口？），关闭连接"
```

### 2.3 第三阶段：基于铁证 B 的追查（未闭合）

- 主线程在等 uds HTTP 响应；服务端侧子进程空闲（没收到请求或没处理）
- 怀疑链：E2E 的 `cp.client`（httpx uds transport）→ 连到**测试进程泄漏的 IPC 桥**（Thread-1）而非子进程的 IPC → 桥的 `_connect_upstream()` 查**本进程** `FrontendPortRegistry.tcp_port()` → None/失效 → 桥 close 连接 → **但 httpx 客户端 recv 不返回 EOF 而是永久挂**
- 深挖点（未完成）：
  1. httpx 对 uds 阻塞 socket 的 read timeout 是否真正落到 socket 层（栈显示 `sock.recv(max_bytes)` 阻塞模式，timeout 参数疑似未 settimeout）——**库级缺陷嫌疑**
  2. 测试进程为何有存活的 `_unix_accept_loop`（uds 测试 finally 有 cleanup——泄漏源头未定位）
  3. E2E uds 请求到底连到哪个进程的 socket（测试进程 vs 子进程——两者共用 DATA_DIR 下的同一 socket 文件路径，bind 互斥但测试进程泄漏的 accept 线程 + 子进程 bind 的竞态未理清）

## 3. 已排除的假设

| 假设 | 排除依据 |
|------|---------|
| 并发加载竞争 | 所有 load/unload/infer 经同名 worker FIFO 单线程串行 |
| ProxyPool 坏单例（曾以为是根因） | 修复 `__new__` 漏调 `_init_once` 后 [77] 直跑仍挂 3/3；之前"4 轮通过"实为该测试被误删 |
| knowledge/events 测试本身逻辑 | 单跑/子进程跑全过；断言无问题 |
| 内存耗尽 | heartbeat 显示 78% free |
| SIGALRM 可打断的 Python 层死循环 | setitimer 到期不触发 |

## 4. 已落地的修复（随本调查）

1. `ManagedModel` 加载/release 等待 120s 超时兜底（`LOAD_WAIT_TIMEOUT_SEC` 类常量）——针对铁证 A 的 MLX 挂死；生产防御价值真实（远程降级/恢复会真实触发 unload→load 循环）
2. `test_load_hang_timeout` 单测（14/14）
3. 顶部预热 `graphiti_core` + `server`（修过一个真实子问题：多线程延迟 import 互锁，使卡点从 76 后移到 77）
4. SIGALRM 看门狗保留在 main()（对 Python 层慢测试有兜底价值；对此类 C 层挂起无效——已知局限）

## 5. 恢复调查的建议路径（按性价比排序）

1. **验证 httpx uds timeout 缺陷**（30 分钟）：最小脚本——uds server accept 后不响应，httpx Client(uds=..., timeout=2) 发请求，观察是否 2s 超时还是永久挂。若复现 → 库级确认，绕法：E2E client 换手写 socket + select 超时，或请求层 watchdog
2. **定位 Thread-1 泄漏源**（1 小时）：逐个 ipc/uds 测试后检查 `threading.enumerate()`；泄漏修复后 [77] 直跑可能直接通过（桥 upstream 失效的触发条件消失）
3. **若 1+2 后仍挂**：心跳复跑抓最新栈，对比本档案铁证 B
4. 工具已就位：`/tmp/heartbeat_inject.py`（主进程/子进程注入法均已在档案中记录用法）

## 6. 相关文件快照（暂停时点）

- 挂起形态：test_control 79 测试，前 77 ✓ 后在 [77] 挂（exit=124）
- [77] 当前为**进程内直跑**形态（曾改子进程隔离后又被要求还原直跑）
- 其余测试族全绿：model_lifecycle 14 + oop_singletons 6 + remote 系列 31 + proxy 60
