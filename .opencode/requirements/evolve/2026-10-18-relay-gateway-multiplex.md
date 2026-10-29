# 需求文档：中继会话入口多路复用（gateway relay 循环并发化）

> 状态: Phase 2 草稿
> 来源: 2026-10-18 节点 11.8s/15.2s 复盘（远程日志接口自查）——中继会话循环逐请求串行；并发场景在 remote 测试矩阵中 0 覆盖

---

## §1 背景与目标

### 1.1 背景

1. **串行机制（实测）**：`remote_gateway._relay_session_loop` 在唯一读取循环内
   `await self._forward_api(msg)`——TTS 等慢请求把循环阻塞至全链结束；后续请求
   （含 Ping）排队。三处实测：后一笔的"请求进入" = 前一笔"本地合成完成" + 15~40ms；
   两笔同毫秒到达主控的请求（09:02:58.644×2、10:00:11.505×2）被串行处理，且
   两轮处理顺序相反（09:03：81字先/17字后；10:00：17字先/81字后）——**顺序不可控**。
2. **路径不对称**：UDP 直连路径为每包 `create_task`（并发）；中继路径为遗漏
   （而协议 `msg_id` 已支持乱序多路复用——缺的只是服务端入口的执行模型）。
3. **测试断档（不可接受项）**：全部 remote 测试为单请求正确性用例；
   `grep 并发/concurrent/Thread/gather` 在 remote 测试中命中数 = 0——
   "同一会话两笔并发"场景（预取机制引入后的真实流量）无任何测试层覆盖。
4. **受害者画像**：AP 隔离环境下打洞必失败 → 永久走中继 → 串行恒生效；
   预取（PREFETCH_DEPTH=2）完全失效；等待时长取决于"排位运气"。

### 1.2 目标

| # | 目标 | 验收口径 |
|---|------|---------|
| G1 | 中继入口**完整多路复用**：读取循环只做 read/解码/派发；**所有消息类型**处理进独立 task（非按类型打补丁） | 并发测试：修复前红（复现串行）→ 修复后绿 |
| G2 | **并发测试先行入库**（relay 路径两笔并发 / TTS 期间 Ping 不阻塞 / 异常隔离 / 断连清理） | 测试文件 + "红→绿"证据链入库 |
| G3 | 完备性配套：处理并发上限（资源保护）/ 任务跟踪与断连清理 / 发送路径并发原子性 | 代码审查 + 测试覆盖 |
| G4 | 真机复测：两笔并发 wall ≈ max（不再 2×） | 主控侧实验复跑 |

### 1.3 非目标

- **不改协议、不改客户端**（`msg_id` 已支持乱序多路复用；主控接收侧 `_on_msg`
  为同步投递无需改动）
- **不做业务级背压**（"调用后内部能并发几条是内部的事"——由下游 backend/TTS
  信号量自管；gateway 只保证"不串行 + 资源保护"）
- UDP 直连路径行为不变（已是每包 task 并发——本次仅将其消息语义结构对齐到
  统一入口，防双维护分叉）

---

## §2 技术方案

### 2.1 `_relay_session_loop` 重构（`services/remote_gateway.py`）

**读取循环（只做派发，永不 await 业务处理）**：

```python
async def _relay_session_loop(self, conn, session) -> None:
    frame_reader = TcpFrameReader()
    tasks: set[asyncio.Task[None]] = set()
    try:
        while True:
            chunk = await conn._reader.read(4096)
            if not chunk:
                break
            for payload in frame_reader.feed(chunk):
                msg = remote_wire.decode(session.decrypt_seq(payload))
                task = asyncio.get_running_loop().create_task(
                    self._serve_relay_msg(conn, session, msg))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
    except (ConnectionError, OSError, CryptoError, asyncio.IncompleteReadError):
        pass  # 对端断开——正常终态
    finally:
        for task in list(tasks):
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
```

**单消息处理（独立任务，全类型统一入口）**：

```python
_RELAY_INFLIGHT_MAX = 32  # 资源保护线（防 task/httpx 无界；业务并发由下游决定）

# __init__ 增加（Semaphore 3.10+ 构造不绑 loop）:
#   self._relay_inflight = asyncio.Semaphore(_RELAY_INFLIGHT_MAX)

async def _serve_relay_msg(self, conn, session, msg) -> None:
    """中继会话单消息处理（读取循环之外的独立任务——全类型多路复用）。"""
    try:
        async with self._relay_inflight:  # Semaphore(_RELAY_INFLIGHT_MAX)
            await self._handle_session_msg(
                lambda m: self._relay_send(conn, session, m), msg)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 —— 单条异常不杀会话（与 UDP 路径 _safe_handle 对称）
        logger.exception("中继会话单消息处理异常（会话继续）")
```

**消息语义单点（UDP 与中继统一，非双维护）**：

```python
async def _handle_session_msg(
        self, send: "Callable[[remote_wire.WireMsg], Awaitable[None]]",
        msg: "remote_wire.WireMsg") -> None:
    """会话消息语义单点（UDP 每包任务与中继每消息任务共用——新增消息类型只改此处）。"""
    if isinstance(msg, remote_wire.PingMsg):
        await send(remote_wire.PongMsg(msg_id=msg.msg_id, ts=time.time()))
    elif isinstance(msg, remote_wire.ApiReq):
        await send(await self._forward_api(msg))
    else:
        logger.debug("会话未知消息: %s", type(msg).__name__)
```

- 中继调用：`_handle_session_msg(lambda m: self._relay_send(conn, session, m), msg)`
- UDP 调用：`_session_dispatch` 改为薄包装 `await self._handle_session_msg(session.send_msg, msg)`
  （**行为完全不变**——仅结构对齐，防"新消息类型两处改"的分叉温床）

**发送并发原子性**（多任务并发调用 `_relay_send`）：
- `session.encrypt_seq(...)` 为同步函数（单事件循环内原子）；
- `conn._writer.write(...)` 单次调用（同步缓冲，无 await 间隙）；
- `await conn._writer.drain()` 支持多任务并发等待。
- 以上为代码事实；由测试覆盖"两笔响应体各完整、无交错"。

**生命周期**：会话循环退出（对端断开/异常/stop）→ `finally` 取消全部在途任务——
响应已无处可发，丢弃；`_forward_api` 的在途 httpx 请求随 task 取消。

**对称性核对（已查）**：UDP 路径 `datagram_received` → 每包 `create_task`（已并发）；
主控 `_on_msg` 按 `msg_id` 同步投递（无阻塞）——改后两条路径语义一致。

### 2.2 测试（先行：修复前必须红）

**新增 `tests/test_remote_gateway_concurrency.py`**（复用 `test_remote_e2e.py` 的
本机三组件栈：RelayServer + RemoteGateway + HTTP stub——不依赖真机）：

| # | 用例 | 断言（修复后） | 修复前形态 |
|---|------|--------------|-----------|
| 1 | **relay 路径两笔并发**（慢 stub：延迟 1.5s + 记录并发峰值；网关 ep 指向不可达强制落中继） | stub 并发峰值 = 2；两笔 wall **< 2.5s** | 红：峰值 = 1、wall > 2.8s（≈3.0~3.4s） |
| 2 | **慢请求进行中探测**：`probe_health`（生产心跳路径）+ `transport.probe`（协议 Ping）各发一次 | 两者往返均 **< 1s** | 红：均等待慢请求完成（>1.5s） |
| 3 | **异常隔离**：一笔触发 stub 500/异常 | 会话继续可用（随后一笔成功） | —（防回归） |
| 4 | **断连清理**：客户端断开后立即新建连接 | 新会话立即可用并发请求成功（无残留阻塞） | —（防回归） |

**脚手架增强**：现有 `_start_http_stub`（tests/test_remote_relayd.py）扩展
"响应延迟 + 并发计数"，或新增专用慢 stub（放 `tests/remote_testkit.py`）。

### 2.3 验收证据链（红→绿）

```
步骤1 写测试 → 单独运行 → 1、2 用例失败（1 的失败形态=串行：峰值1/wall≈2×）
步骤2 实施修复 → 再运行 → 4 用例全绿
步骤3 全量回归（pytest + pyright 0/0/0）
步骤4 推送 → 用户"更新并重启"节点 → 主控侧并发实验复跑（wall≈max）+ 首听实测
```

---

## §3 实现规范

### 3.0 改动范围表

| 文件 | 类型 | 改动 |
|------|------|------|
| `services/remote_gateway.py` | 修改 | `_relay_session_loop` 派发化 + `_serve_relay_msg` + `_handle_session_msg`（语义单点）+ `_session_dispatch` 对齐 + `__init__` 信号量 + 常量 |
| `tests/test_remote_gateway_concurrency.py` | 新增 | 并发测试 4 用例（先红后绿） |
| `tests/remote_testkit.py` 或 `tests/test_remote_relayd.py` | 小改 | 慢 stub（延迟 + 并发计数） |

### 3.1 实施步骤拆分

1. **测试先行：慢 stub 增强 + 并发测试**
   - 文件: `tests/remote_testkit.py`（stub 增强）；`tests/test_remote_gateway_concurrency.py`（新建）
   - 预估行数: +180
   - 验证点: 单独运行新测试 → **用例 1、2 失败，且失败形态 = 串行**（stub 峰值 1、wall≈2×；pong 等待）——**红**（保存输出为证据）
   - 依赖: 无
2. **修复 gateway 多路复用**
   - 文件: `services/remote_gateway.py`
   - 预估行数: +90
   - 验证点: 新测试 4 用例**全绿**；`test_remote_e2e` / `test_remote_relayd` / `test_remote_p2p_lan` 全绿（含 UDP 语义对齐回归）
   - 依赖: 1
3. **全量回归**
   - 文件: 无
   - 预估行数: 0
   - 验证点: `pytest tests/ -q` 全绿 + pyright 0/0/0
   - 依赖: 2
4. **真机复测（推送后）**
   - 文件: 无
   - 预估行数: 0
   - 验证点: 用户"更新并重启"节点后——主控侧并发实验 wall≈max；节点日志两次"请求进入"间隔 < 1s（不再 15~40ms-跟随串行链）
   - 依赖: 3

---

## §4 验收标准

### 功能验收

- [ ] relay 路径两笔并发：stub 并发峰值 = 2、wall < 时间阈值（修复前红证据留档）
- [ ] TTS 慢请求期间 Ping 往返 < 1s
- [ ] 异常隔离：单消息异常不杀会话（后续消息正常）
- [ ] 发送无交错：两笔响应体各自完整
- [ ] 断连清理：会话退出后在途任务全部收尾

### 回归验收

- [ ] 既有 remote 测试全绿（e2e/relayd/p2p_lan/link/routes/client/crypto）
- [ ] 全量 `pytest tests/ -q` 全绿；pyright 0/0/0
- [ ] 行为不变项：单请求场景、UDP 直连路径、协议线格式

### 架构验收

- [ ] "读取循环只派发"——以后新增消息类型自动获得并发（无按类型补丁）
- [ ] 强类型（`set[asyncio.Task[None]]` 等）+ 常量收口
- [ ] 两端/双路径语义对称（UDP 每包 task ↔ 中继每消息 task）

---

## §5 与现有需求文档的关系

- **修复**：`2026-10-18-remote-log-query.md` 自查暴露的真实 bug（其接口是本复盘的关键工具）。
- **延续**：`2026-10-17-p2p-direct-upgrade.md`（中继路径为其组成部分；本需求修其并发语义）。
- **配套**：预取机制（`2026-10-17-tts-prefetch-depth2-queue-ui.md`）的"并行合成"价值依赖本修复才能在 relay 环境真实生效。
