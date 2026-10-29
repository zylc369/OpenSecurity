# Transport 在途请求看门狗 + 消息级跟踪日志 + 超时收敛

## §1 背景与目标

**来源**: 远程 TTS "600 秒卡顿"复盘（2026-10-18）。

**事件**: 用户点击试听 → 3 笔请求发出后**节点侧零痕迹**（用字数指纹验证）→ 恰好其间隔发生 transport 会话重建（19:49:27-29）→ 请求无人过问，**挂满 600 秒**（`TTS_TIMEOUT_SEC`）→ 才 fallback 本地合成 → 端到端 **11.4 分钟**。

**痛点**（三条，对应三个改动）:
1. **可见性缺失**: 消息"发出→到达→响应"三段链路无 INFO 级跟踪日志——故障时无法定位丢失区间（只能靠间接推断）。→ **C: 消息级跟踪日志**
2. **故障检测缺失**: 请求挂起期间无任何机制检测"连接/请求是否出了问题"，唯一出口是超时定时器。→ **A: 在途看门狗**（等待期间周期探测连接，异常即中止）
3. **超时失衡**: TTS 超时 600s 为"慢链路大文件"设计，对"故障链路"放大成灾难。→ **B: 600s → 90s**

**预期收益**:
- 故障可见性: 消息丢失区间可一眼定位（主控发送↔节点接收↔响应返回 三段日志对齐）
- 故障收敛: 最长等待从 **600s → ~17s**（12s 看门狗 + 5s 探测）触发 fallback
- 兜底上限: 600s → 90s（1 行）

## §2 技术方案

### 改动 C: 消息级跟踪日志（`services/remote_transport.py`）

`_handle_job` 内:
- 发送成功后: `logger.info("api.req 已发送: %s %s（id=%d, 路径=%s, 等待响应）", ...)`
- 收到响应后: `logger.info("api.resp 已收到: id=%d（往返 %.0fms）", ...)`
- 异常路径: `logger.warning("api.req 失败: id=%d %r", msg_id, e)`（在现有 except 内，让"请求失败: "空消息问题不再出现——异常类型进日志）

### 改动 A: 在途看门狗（同文件）

`TransportConfig` 新增:
```python
watchdog_sec: float = 12.0   # 在途请求看门狗间隔（无响应超此秒数触发连接探测）
probe_wait_sec: float = 5.0  # 看门狗探测等待（ping 响应超时）
```

`_handle_job` 等待逻辑改造（分段等待 + 探测）:
```python
total = job.timeout_sec or api_timeout_sec
t_wait0 = time.monotonic()          # 计时基准: 发送完成后
while True:
    remaining = total - (time.monotonic() - t_wait0)
    if remaining <= 0:
        raise ConnectionError("请求超时（等待 %.0fs 无响应）" % total)   # 带消息!
    try:
        return await asyncio.wait_for(asyncio.shield(fut), timeout=min(watchdog_sec, remaining))
    except asyncio.TimeoutError:
        if fut.done():
            return fut.result()      # 恰好完成（边界）
        if not await self._probe_conn():     # 看门狗判定
            logger.warning("看门狗: id=%d 等待 %.0fs 无响应且连接探测失败", ...)
            raise ConnectionError("连接无响应（看门狗探测失败）")
        # 连接健康（慢响应）→ 继续等剩余时间
```
`shield` 保证 fut 不被分段超时取消；循环总预算 = 原超时值（不改变慢链路语义）。异常类型用**带消息的 ConnectionError**（走既有 except → `_drop_session()`；且消除"请求失败: "空消息——空消息源于无参 `asyncio.TimeoutError`）。`_submit` 外层 `req_timeout+15` 无需调整（失败路径提前返回错误）。

新增 `_probe_conn() -> bool`（loop 内直发 ping，不递归 `_handle_job`；与现有 `probe()` 的区别: `probe()` 走 `_submit` 跨线程 + 可触发会话重建，`_probe_conn` 只用当前 `self._conn` 直发、绝不重建——探测的是"现有连接是否活着"）:
```python
async def _probe_conn(self) -> bool:
    conn = self._conn
    if conn is None or conn.broken: return False
    from services.remote_wire import PingMsg
    loop = asyncio.get_running_loop()
    pid = self._next_id; self._next_id += 1
    fut: "asyncio.Future[remote_wire.WireMsg]" = loop.create_future()
    self._pending[pid] = fut
    try:
        await conn.send_msg(PingMsg(msg_id=pid))
        await asyncio.wait_for(fut, timeout=self._cfg.probe_wait_sec)
        return True
    except (ConnectionError, OSError, asyncio.TimeoutError, CryptoError):
        return False
    finally:
        self._pending.pop(pid, None)
```
探测失败 → `_handle_job` 抛 `ConnectionError` → 现有 except → `_drop_session()` + `TransportError` → 上层 fallback/下笔重建。**行为语义: "等待中的请求发现连接异常 → 立即中止"**。

### 改动 B: TTS 超时收敛（`services/remote_client.py`）

`TTS_TIMEOUT_SEC = 600.0 → 90.0`（保留"慢链路放宽"语义但收敛上限；音频合成正常 <30s，90s 留 3 倍余量）。

## §3 实现规范

### §3.1 实施步骤

**步骤 1. 消息级跟踪日志（C）**
- 文件: `services/remote_transport.py`（`_handle_job` 内 3 处日志）
- 预估行数: +18 / -2
- 验证点: 语法+pyright；新增单测用 `caplog` 断言"已发送/已收到"两条 INFO 在正常请求中各出现一次
- 依赖: 无

**步骤 2. 看门狗核心（A）——测试先行**
- 文件: `services/remote_transport.py`（TransportConfig 2 字段 + `_probe_conn` + `_handle_job` 等待改造）
- 预估行数: +55 / -8
- 验证点: 新增 `tests/test_remote_transport_watchdog.py`:
  - ① "假活"场景（stub 服务器收请求不回响应）: 请求在 `~watchdog_sec + probe_wait_sec` 内失败（远小于总超时）；**断言异常消息非空**（含"看门狗"或"无响应"字样——防"请求失败: "空消息回归）
  - ② 健康慢响应场景: 看门狗探测通过 → 请求最终成功（**不误杀**）
  - ③ 回归: 既有 600s 语义测试（大文件分片）不受影响
  - 先写测试跑出红，再实现跑出绿
- 依赖: 步骤 1（日志断言可复用）

**步骤 3. TTS 超时收敛（B）**
- 文件: `services/remote_client.py`（1 行）+ 对应测试断言
- 预估行数: +1 / -1
- 验证点: 常量值断言 + 相关测试回归
- 依赖: 无（独立）

**步骤 4. 全量回归 + 审查 + 提交**
- 全量 `pytest` + `pyright` + 真机验证（正常试听延时无回归）
- 预估行数: 0
- 依赖: 1+2+3

## §4 验收标准

**功能验收**:
1. 正常请求: 每笔 `api.req 已发送` / `api.resp 已收到` 成对出现（含 msg_id 与往返耗时）
2. 假活连接: 请求在 ~17s 内失败并 fallback（对照事件中 600s）
3. 慢但健康的连接: 长耗时请求（>12s）不被误杀，正常完成
4. `TTS_TIMEOUT_SEC == 90.0`

**回归验收**:
- 全量测试通过（基线 274 passed / 1 skipped）
- 打洞升级/会话重建/中继回退路径不受影响（多路复用/自愈测试全绿）
- 真机试听延时无回归

**架构验收**:
- 无新增文件（除测试）; 依赖方向不违反
- 探测复用现有 `_pending` 机制（不引入第二套等待体系）

**行为变化说明（预期，非缺陷）**:
- 看门狗使"故障链路"上的请求更快失败（~17s vs 600s）→ `remote_link.note_request_failure` 调用更早、失败计数更快累积 → DEGRADED 降级更快到达。这是正确方向（链路真坏时应尽快降级/本地兜底），非回归。
- 正常链路（含 >12s 慢响应）不受影响（探测通过则继续等待）。

## §5 与现有需求文档的关系

- **独立新增**，不修改既有文档。
- 与 `2026-10-18-node-network-heal.md`（节点侧重连自愈）互补: 本篇解决**主控侧在途请求的故障感知**；两者共同构成"链路任一段故障都不静默等待"。
- 与 `2026-10-18-relay-gateway-multiplex.md`（多路复用）无重叠: 后者解决并发派发，本篇解决在途请求健康。
