# [77] 测试挂起调查档案（已结案）

> 状态: **已结案**（2026-09-27 晚）——根因 = restart execv bug 的多线程冻结形态; 详见 §9
> 复验与诊断注入拆除（2026-09-29）见 §10
> 关联: 2026-09-26-backend-oop-refactor.md / progress 同名文件

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

**工具**（代码与用法归档于 §10）：daemon 线程每 5s 把全线程 Python 栈写入 `/tmp/hb_stacks.txt`。不持锁、不受 C 层阻塞影响、无需特权。

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
4. 工具：心跳注入脚本（代码与两处用法见 §10）

## 6. 相关文件快照（暂停时点）

- 挂起形态：test_control 79 测试，前 77 ✓ 后在 [77] 挂（exit=124）
- [77] 当前为**进程内直跑**形态（曾改子进程隔离后又被要求还原直跑）
- 其余测试族全绿：model_lifecycle 14 + oop_singletons 6 + remote 系列 31 + proxy 60

---

## 7. 新证据（2026-09-27 追加: 子进程隔离版也挂）

**实验**: [77] 改为 `subprocess.run([sys.executable, "-c", code], timeout=180)` 子进程隔离执行（断言原样）。
**结果**: 仍然挂起（76 ✓ 后卡死，exit=124）。

**心跳取证（决定性）**:
- 主进程（测试进程）最后心跳块 08:52:29 后**完全停摆**（含心跳线程本身）= 进程级 GIL 冻结
- MainThread 栈: `subprocess.run → communicate → _communicate → selectors.select`
- 其余全部线程在正常等待点（queue.get/event.wait/accept）——无持锁死等
- stack-heartbeat 线程最后帧: `time.sleep(5)` 返回后的 `_heartbeat` 入口——**sleep 返回后无法获取 GIL 执行写文件**

**结论更新（排除与锁定）**:
- ❌ 排除: TestClient(anyio portal) 形态假设——子进程隔离无 TestClient 仍挂
- ✅ 锁定方向: **macOS 多线程 Python 进程的 fork/spawn 竞态**——测试进程此时持有 ~20 个线程（reaper×10/event-store/knowledge-store/ipc-accept/tqdm/uvicorn 测试实例×2），spawn [77] 子进程时 fork 与某线程的 malloc/GIL 状态碰撞，子进程或父进程在 exec 前后死锁
- 关联佐证: SIGALRM 失效（C 层）、faulthandler 失效（GIL 不可获取）、心跳线程 sleep 返回后冻结——全部指向 GIL/malloc 级冻结而非 Python 层死锁

**恢复调查的下一步建议（更新）**:
1. 最小复现: 多线程进程（20 线程各自 sleep）+ 循环 spawn python3 -c 子进程——看能否复现冻结（15 分钟）
2. 若复现: 这是 Python 3.13 macOS 平台级 bug 候选（fork+threads），绕法=子进程 spawn 用 posix_spawn（subprocess 默认应已用）或 process 重构
3. 若不复现: 二分测试线程组合定位碰撞源

## 8. 当前处置（结案前）

[77] 已恢复为子进程隔离形态（断言原样）——但该形态也会触发挂起。全量回归时需**跳过 [77]**（标记 skip）——单独直跑该测试通过（干净环境）。根因调查按 §7 建议路径，等用户明确提示词。

---

## 9. 结案（2026-09-27 晚）

### 9.1 根因：restart execv bug 的多线程冻结形态（统一理论）

restart 测试经**模块级旧实例**（`services/restart.py` 残留的 `console_restarter = ConsoleRestarter()`，
OOP 批次 D 遗漏项）武装了真 `Timer(1.5s)` → 触发真 `perform()` → `os.execv(sys.argv[0])`。
测试进程此时持有 ~20 个线程（10× reaper + stores + ipc-accept + tqdm + …）。
execv 在多线程进程中做镜像替换/fd 关闭，与任意线程的 malloc/GIL 状态碰撞，两种结局：

1. **execv 成功** → 套件重跑（progress 档案记录的 ×2/×3/×4 重跑现象，最坏 387s）
2. **execv 中途冻结** → 整进程 GIL 冻结——即本档案全部"玄学"观测

### 9.2 该理论统一解释此前所有无法闭环的证据

| 历史观测 | 统一解释 |
|---|---|
| 全量跑 3/3 挂在 [77] 附近 | restart 测试在 [77] 前几个位置，Timer 固定 +1.5s 触发; 全量跑到此线程最多 → 碰撞概率最大 |
| 单独直跑 [77] 通过 | 不含 restart 测试 → 无 Timer → 无 execv |
| 少量前置 + [77] 通过 | 前置未覆盖 restart 测试 |
| 卡点"不固定"（73/76/77） | 冻结是否发生是概率性的; 冻结瞬间主线程的执行点决定卡在哪 |
| 铁证 B: 主线程 httpx recv 永不返回 | Timer 触发时主线程恰在 [77] 的 HTTP 等待中，execv 冻结 → 响应永不到达 |
| §7: 子进程隔离版也挂 | 同因; 冻结瞬间主线程在 subprocess.communicate |
| SIGALRM/faulthandler 到期不触发、心跳线程 sleep 返回后无法写文件 | execv 冻结是 C 层/malloc 级，Python signal handler 无 GIL 可调度——与 §7 "GIL 冻结"结论吻合，仅归因修正（非 spawn 竞态，是 execv 竞态） |

严谨度: 修复后行为一致（3/3 挂 → 3/3 过）+ 机制上无矛盾解释全部证据的强推断; 未做破坏性复现实验（故意还原 bug 跑到冻结——无必要，修复已验证）。

### 9.3 挂起消失后立即抓到的真实 bug（曾被挂起掩盖）

[77] 恢复执行后第一轮就暴露**两处生产接口漂移**（OOP 重构遗漏消费方更新，
`POST /api/knowledge/memory/entry` 与 `POST /api/events/*` 写端点一直是 AttributeError/500）:
- `routes/knowledge.py:70` `submit_entry` → `submit`
- `routes/events.py:73,83` `submit_entry` → `submit`
- 静态核对全部路由→服务方法调用（正则比对 41 文件），无其他漂移

### 9.4 处置

- restart bug 修复: 删模块级实例导出 + 路由改 `get_instance()` + restart 测试改类级 patch perform（progress 档案有完整记录）
- [77] 恢复全量直跑（子进程隔离形态保留——防 TestClient 循环互锁，这是独立且真实的防御）; TC_FULL_RUN 守卫删除，环境变量零残留
- 验证: 无守卫全量 3/3 通过（70.03/69.06/69.30s），80/80
- §2.2 深挖点（httpx uds timeout 库缺陷嫌疑、Thread-1 泄漏）随结案关闭——其观测均产生于 execv 污染环境，如后续独立复现再立新档

---

## 10. 复验与诊断注入拆除（2026-09-29）

### 10.1 复验结论（[77] 无复发）

结案（§9）后全量套件持续演进（79 → 93 测试），数十轮全量顺序跑零挂起；
2026-09-29 单日 6 轮 93/93（每轮含 restart 测试 + 本档案 [77] 测试 + OCR
全族），原触发场景（全量顺序跑）反复通过。MLX 挂死结案消灭了"前置堆积"
变体（见 2026-09-27-mlx-hang-investigation.md）。本档确认无独立复发迹象，
维持结案。

### 10.2 拆除诊断注入（[77] 调查期的临时措施）

[77] 调查期装入"子进程心跳注入"并随 commit 266489f 固化进
`tests/test_control.py` 的 `ControlProcess.start()`：每个 E2E 控制台子进程
启动命令为 `exec(open('/tmp/heartbeat_inject.py'))` + runpy 两段式。诊断
终了后该注入成为纯负担——依赖 /tmp 常驻文件（被系统清理时全部 E2E 测试
崩）、每子进程一持久写栈线程、累积 `/tmp/hb_stacks.txt` 13.5MB。

**拆除**：`ControlProcess.start()` 恢复原始形态
`[sys.executable, str(BACKEND_DIR / "server.py")]`；删除 /tmp 两文件
（heartbeat_inject.py / hb_stacks.txt）。终验：全量 93/93 且
hb_stacks.txt 零重建。

### 10.3 心跳注入脚本（归档——C 层挂起唯一有效取证工具）

适用场景: 进程疑似卡在 C 层系统调用（SIGALRM/faulthandler 到期不触发、
sample 采样只见 kevent/活锁假象）时，用本脚本注入全线程 Python 栈心跳。
不持锁、不受 C 层阻塞影响、无需特权。

```python
"""心跳线程注入: 每 5s dump 全线程 Python 栈（sys._current_frames 不受 C 层阻塞影响）。"""
import threading, sys, traceback, time, os

def _heartbeat():
    while True:
        time.sleep(5)
        try:
            with open("/tmp/hb_stacks.txt", "a") as f:
                f.write(f"\n===== {time.strftime('%H:%M:%S')} pid={os.getpid()} =====\n")
                frames = sys._current_frames()
                names = {t.ident: t.name for t in threading.enumerate()}
                for tid, frame in frames.items():
                    f.write(f"--- {names.get(tid, f'tid-{tid}')} ---\n")
                    f.write("".join(traceback.format_stack(frame))[-1500:])
        except Exception:
            pass

threading.Thread(target=_heartbeat, daemon=True, name="stack-heartbeat").start()
```

用法（将上文件存为 hb.py；输出路径 /tmp/hb_stacks.txt 可按需改）:
- 主进程注入: `python -c "exec(open('hb.py').read())\n<目标启动代码>"`
  ——`\n` 须是**真实换行**（shell 双引号不解析反斜杠转义；在 Python
  字符串里构建同样命令时写 `\n`，Python 会转义为真实换行；写成 `\\n` 则是字面反斜杠+n，内层 python 报 SyntaxError）
- 子进程注入: 启动命令前段拼 `exec(open('hb.py').read())\n` 再接目标
  （即本次拆除的 `ControlProcess` 两段式形态；换行同注意事项）
- 读取: `/tmp/hb_stacks.txt` 按 `===== HH:MM:SS pid=N =====` 分块；每线程
  整段栈保留末尾 1500 字符（最内层帧优先）
