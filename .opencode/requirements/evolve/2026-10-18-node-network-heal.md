# 需求文档：节点换网自愈（信令活性检测 + UDP 重绑）

> 状态: Phase 2 草稿
> 来源: 2026-10-18 双热点实验——MacMini 运行中切热点后 `节点不可达: node_offline`（注册链路未自愈）；代码级诊断定位两处缺口

---

## §1 背景与目标

### 1.1 背景（实测 + 代码诊断）

1. MacMini 运行中切换网络（WiFi → 手机热点）后：主控报
   `远程不可达: RemoteUnavailable: 远程 P2P 调用失败: 节点不可达: node_offline`；
   手机热点可见 MacMini 已连接；**切回 WiFi 即恢复**——即"注册链路在换网后未自愈"。
2. 代码级两处缺口：
   - **缺口 1**：`_signal_steady` 维持循环**不验收心跳往返**——协议上 relayd 对
     `heartbeat` 回 `heartbeat_ack`（server.py L209-212 / protocol.md L75-76），
     但实现只"发"不"验"；换网后旧连接变死连接：`recv(timeout=1.0)` 永远超时
     → `continue`、心跳 `send` 写本地缓冲不报错——**循环静默空转，注册永不重建**
     → relayd 侧判 offline。
   - **缺口 2**：`_ensure_udp()` 幂等（`已有 socket 即 return`）——换网后
     旧 UDP socket 绑定失效**不会被重建**。

### 1.2 目标

| # | 目标 | 验收口径 |
|---|------|---------|
| G1 | **信令活性检测**：N 秒内无任何收包 → 判连接死亡 → 走既有重建路径 | 单测：静默 → 进入重建（可观测） |
| G2 | **重建路径重置 UDP socket**（绑定新网络）+ STUN 重探 | 单测：重建后 UDP 为新对象 |
| G3 | **真机验收**：MacMini 切热点 → ≤90s 内自动恢复注册（重新在线） | 切网实验；且切回 WiFi 也稳定 |
| G4 | **不误杀**：正常运行时收包持续刷新活性，无多余重建 | 回归全绿 + 真机长稳观察 |

### 1.3 非目标

- 不改协议、不改客户端（主控侧）
- 不做"OS 网络事件监听"（用"静默超时"通用机制覆盖所有换网形态）
- 打洞可行性实验（本修复完成后另行执行，不在本需求范围）
- 不做"注册失败时的多 relayd 容灾"（单 relayd 现状不变）

---

## §2 技术方案

### 2.1 活性检测（`_signal_steady`）

- 新增常量：`SIGNAL_DEAD_SEC = 2 * HEARTBEAT_SEC`（60.0）。
- 循环内维护 `last_rx`（初值=进入循环时刻；**每成功 recv 到任何消息即刷新**
  ——含 `heartbeat_ack` 与未知消息）。
- 每轮顶部检查：`if now - last_rx > SIGNAL_DEAD_SEC: raise ConnectionError(...)`
  → 异常冒泡至 `_register_loop` 的 except → `_close_client()` + 退避重连（既有）。
- 发送异常（socket 已被 OS 关闭等）**自然冒泡**（既有行为不变）。

### 2.2 UDP 重绑（`_register_loop` 重建路径 + `stop()`）

- 新增 `_close_udp()`：关闭 `self._udp.transport` 并置 None（幂等；与
  `_close_client()` 对称）。
- **重建路径**：`_register_loop` 的 except 块中，`await self._close_client()` 后
  追加 `self._close_udp()`——下一轮 `_ensure_udp()` 即在**新网络**上重建 socket。
- `stop()` 改用 `_close_udp()`（收口，替代内联 close）。

### 2.3 行为说明（预期副作用）

- 重建时 UDP 换端口 → 旧打洞/直连会话失效——**这正是"网络环境成疑"的正确响应**
  （换网后旧 NAT 映射本就失效；客户端 transport 会自动重建会话）。
- 总恢复窗口：静默判定 ≤60s + 退避（1~30s）→ 目标 ≤90s 内重新在线。
- 正常场景（持续收包）：零行为变化。

---

## §3 实现规范

### 3.0 改动范围表

| 文件 | 类型 | 改动 |
|------|------|------|
| `services/remote_gateway.py` | 修改 | 常量 + 活性检测 + `_close_udp()` + 重建/stop 接入 |
| `tests/test_remote_gateway_heal.py` | 新增 | 静默判死 / UDP 重绑 / 不误杀 |

### 3.1 实施步骤拆分

1. **核心修复**（`services/remote_gateway.py`）
   - 预估: +60 行
   - 前置核查: `_stun_probe` / `SignalClient.recv` / `send` 的超时完备性
     （任一子步骤无限阻塞会架空活性检测——死网络下每轮须能回到循环顶部检查）；
     `stop()` 原文核对后接入 `_close_udp()`
   - 验证点: compile + pyright 0/0/0 + 既有 remote 测试全绿
     （`test_remote_e2e` / `test_remote_relayd` / `test_remote_p2p_lan`）
   - 依赖: 无
2. **测试**（`tests/test_remote_gateway_heal.py`）
   - 预估: +140 行
   - 验证点: ①静默 → 判死 → 重建（**静默途径：真 RelayServer + patch 对
     heartbeat 不回 ack（或裸哑服务端）——实施时择一**；压缩 `SIGNAL_DEAD_SEC`
     （monkeypatch）驱动）②重建后 UDP 对象变更（`id()` 不同）③正常 ack 流在
     阈值内不触发重建
   - 依赖: 1
3. **全量回归 + 真机验收**
   - 验证点: remote 全套 + 后端快集 + pyright；真机：MacMini 切热点 ≤90s 恢复
   - 依赖: 2

---

## §4 验收标准

### 功能验收

- [ ] 信令静默 ≥ 阈值 → 判定死亡并进入重建（单测留证）
- [ ] 重建后 UDP socket 为重绑的新对象（单测留证）
- [ ] 正常收包（含 heartbeat_ack）不触发判死（单测留证）
- [ ] 真机：MacMini 切热点后 ≤90s 自动恢复（`/api/remote/status` 不再 node_offline）

### 回归验收

- [ ] `test_remote_e2e` / `test_remote_relayd` / `test_remote_p2p_lan` /
      `test_remote_gateway_concurrency` 全绿
- [ ] 后端快集全绿 + pyright 0/0/0
- [ ] 正常运行时注册稳定（无多余重建——真机观察日志无重复"已注册"）

### 架构验收

- [ ] 改动收口 `remote_gateway.py`；`_close_udp`/`_close_client` 对称
- [ ] 常量集中（不散落魔法值）

---

## §5 与现有需求文档的关系

- **独立**：修复节点侧自愈；不依赖/不改动远程链路既有协议。
- **前置使能**：修复完成后的"双热点打洞实验"（直连攻坚）依赖本修复（换网不掉线）。
