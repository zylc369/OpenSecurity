# 需求文档：P2P 直连修复批（地址上报 / LAN 候选 / 后台升级 / 链路可见）

> 状态: Phase 2 草稿 → Phase 3 审计中
> 来源: 2026-10-17 远程链路 12s 复盘（双端日志 + 抓包闭环定位：打洞 100% 失败落中继）
> 阅读前置: `services/remote_relayd/protocol.md`（协议规范）、本仓库 remote_* 系列模块

---

## §1 背景与目标

### 1.1 背景

远程合成链路实测首段 12.3s / 每段 12.8s，定位出三类缺陷（链路传输层部分）：

1. **client 端 UDP 地址上报恒为 `0.0.0.0`**：`DirectConnector.connect` 用
   `transport.get_extra_info("sockname")` 取本机地址，但 socket 绑定 `("0.0.0.0", 0)`
   ——macOS 恒返回 `0.0.0.0`，上报给 relayd 的 `udp_ep` 无效，gateway 互射打空。
   （日志实锤：节点侧 `打洞互射开始 → 0.0.0.0:59082`）
2. **gateway 无 LAN 候选**：gateway 注册的 `ep` 是 STUN 公网映射——同 LAN 的 client
   打它需 NAT hairpin（家用路由器多数不支持）；双向都缺"局域网地址候选"，
   同 LAN 场景打洞必然失败。
3. **打洞失败后无自愈**：中继会话一旦建立即长期复用（`_ensure_session` 重建才重试直连），
   链路状态（直连/中继）与失败原因不可见（需翻日志）。

### 1.2 目标

| # | 目标 | 验收口径 |
|---|------|---------|
| G1 | client 上报"真实可达地址"（LAN IP 探测替换 0.0.0.0） | 单测：sockname=0.0.0.0 时上报探测值 |
| G2 | 双端 LAN 候选交换（gateway 上报 lan_ep，lookup 返回 gw_lan） | 单测：registry 存取 + LookupResp 含 gw_lan |
| G3 | 中继态后台自动升级直连（10s 间隔，失败不碰中继会话） | 单测：升级成功切换 / 失败保中继 + 记录原因 |
| G4 | 链路可见：`/api/remote/status` 与前端显示"直连/中继 + 上次失败原因" | 单测：status 含 path；前端 build 过 |

### 1.3 非目标（明确不做）

- STUN 公网映射探测（client 侧）——跨网场景打洞，后续需求
- 打洞候选"并行互射"——本轮为"LAN 优先两段式"（简单可测）
- 真机打洞验收——依赖测试环境网络可达（当前环境 AP 阻断，标注待办）

---

## §2 技术方案

### 2.1 本机 LAN IP 探测（新文件 `services/remote_netutil.py`）

```python
def probe_lan_ip() -> str | None:
    """探测默认出站接口的 IPv4 地址（UDP connect 技巧——不实际发包）。"""
```
- 实现：`socket.socket(AF_INET, SOCK_DGRAM)` → `connect(("8.8.8.8", 53))` →
  `getsockname()[0]`；`OSError` → `None`。socket 用 `with`/`finally` 关闭。
- 用途：client（`remote_transport`）与 gateway（`remote_gateway`）共用。
  归属 `services/`（两模块平级引用，无循环依赖）。
- **强类型**：返回 `str | None`，不抛异常。

### 2.2 client 地址上报修复（`services/remote_transport.py`）

`DirectConnector.connect` 内（现 L142 `local = proto.local_addr()`）：

```python
local = proto.local_addr()
if not local[0] or local[0] in ("0.0.0.0", "::"):
    probed = probe_lan_ip()          # remote_netutil
    if probed:
        local = (probed, local[1])
```
- 上报 `LookupMsg(udp_ep=local)` 逻辑不变（值已修正）。
- 探测失败时保持原值（relayd 有 TCP 源地址兜底，行为不劣化）。
- 注释更新：`_ClientUdpProtocol.local_addr` 的"回环/锥形 NAT 下即本地址"假设
  替换为"绑定 0.0.0.0 时恒返回 0.0.0.0，需调用方探测替换"。

### 2.3 协议扩展：LAN 候选（`remote_wire.py` + relayd + gateway）

**字段设计**（全部可选带默认值——新旧版本互通；旧端显式取字段，忽略未知字段）：

| 消息 | 新字段 | 方向 | 说明 |
|------|--------|------|------|
| `SignalRegister` | `lan_ep: tuple[str,int] \| None = None` | gateway→relayd | 注册时自报 LAN 端点 |
| `SignalUpdateEp` | `lan_ep: tuple[str,int] \| None = None` | gateway→relayd | STUN 刷新时顺带刷新 LAN |
| `LookupResp` | `gw_lan: tuple[str,int] = ("", 0)` | relayd→client | 返回 gateway 的 LAN 端点 |

**编码/解析改动点**：
- `wire.encode`：`register` 分支带 `lan_ep`（None 省略字段）；`update_ep` 同。
- `wire.decode`：`endpoints`（LookupResp）分支增加 `gw_lan` 解析（照 `gw` 模式，
  缺省 `("", 0)`）。
- `remote_relayd/registry.py`：`NodeEntry` 加 `lan_ep: tuple[str,int] | None = None`；
  `register(node, writer, session, lan_ep=None)`；`update_ep(node, ep, lan_ep=None)`
  ——**lan_ep 为 None 时不覆盖旧值**。
- `remote_relayd/server.py` `handle_msg`：`register`/`update_ep` 分支用 `_parse_ep`
  解析 `msg.get("lan_ep")`（非法 → None）；`_lookup` 的 `endpoints` 应答带
  `"gw_lan": [entry.lan_ep[0], entry.lan_ep[1]] if entry.lan_ep else ["", 0]`。
- `services/remote_gateway.py`：
  - `_register_loop`：`SignalRegister(node, ver=1, lan_ep=...)`
    ——**lan_ep 的端口用固定 UDP socket 端口**（`udp_local_addr` 的 port；
    注册前 `_ensure_udp` 已先行——现状即如此，顺序依赖已满足）——格式
    `lan_ep=(probe_lan_ip(), self.udp_local_addr[1])`（探测失败 → None）。
  - `_signal_steady` 的 `SignalUpdateEp`：附 `lan_ep=同上`（60s 随 STUN 刷新）。
- **兼容性**：旧 relayd 忽略新字段（`msg.get` 显式取值）；旧 client 收到 `gw_lan`
  忽略（decode 显式取已知字段）。**relayd 升级非强制**（不升级则 G2 仅单向：
  client 上报 LAN 有效，gw_lan 缺失走原公网路径）。

### 2.4 client 打洞候选（`services/remote_transport.py`）

`DirectConnector.connect` 内（现 L160 附近）：

```python
gw_ep = resp.gw
gw_lan = resp.gw_lan
candidates: list[tuple[str, int]] = []
for ep in (gw_lan, gw_ep):
    if ep[0] and ep[1] > 0 and ep not in candidates:
        candidates.append(ep)
```
- HTTP 管道分支不受影响（仅 P2P）。
- **候选校验**：`candidates` 为空（gw_lan 与 gw 均无效）→ 抛既有
  `TransportError("endpoints 响应畸形")`；仅 gw_lan 有效时可正常打洞
  （校验从"只看 gw"改为"看候选集合"）。
- **两段式互射**：按 `candidates` 顺序——对每个候选发 `punch_burst` 个 punch 包，
  等待 gateway 握手应答至分段时间片（`punch_timeout / len(candidates)`）；
  收到应答（洞通）即进入 Noise 握手；全部超时 → 抛
  `TransportError("打洞超时（5.0s）")`（保留既有错误文案结构）。
- **行为兼容**：老 relayd（无 gw_lan）→ candidates=[gw] → 与现状一致
  （除 2.2 修复后上报值变真）。

### 2.5 后台直连升级（`services/remote_transport.py`）

新增状态与任务（`RemoteTransport`）：

```python
self._upgrade_task: asyncio.Task | None = None   # loop 线程内
self._direct_last_error: str = ""                 # 跨线程只读属性
self._retired: list[tuple[conn, float]] = []      # (退役连接, 关闭 deadline)
```

- `start()` 后创建 `_upgrade_loop`：
  - 每 10s 检查：`self._conn` 为 `RelayConnection` 且未 broken → `_try_direct_upgrade()`。
  - `_try_direct_upgrade`：
    1. `async with self._session_lock:` 内先复查（重建/升级并发防护）；
    2. 构造 `DirectConnector` **独立建连**（新 UDP socket，不触碰现有 `_conn`）；
    3. 成功 → `old = self._conn; self._conn = new; new.start_pump()`；
       旧连接加入 `_retired`（deadline = now + 90s（3×api_timeout）），
       loop 内周期任务清理（到期 `aclose`）；在途请求（响应 handler 与 conn 无关）
       自然完成；
    4. 失败 → `self._direct_last_error = str(e)`，下轮 10s 重试。
- `_ensure_session` 联动：其"直连失败（落中继）"分支**同步写入**
  `self._direct_last_error`（用户最先在会话建立路径看到失败原因）；
  **成功建立直连后清空**。重建路径逻辑不变（直连优先），升级任务只负责
  "中继态 → 尝试升级直连"，两者在 `_session_lock` 内互斥、不重复建连。
- 间隔可注入：`TransportConfig` 加 `direct_upgrade_interval_sec: float = 10.0`
  （单测传短值以免真等；生产默认 10.0——用户拍板的恢复速度）。
- `_retired` 清理时机：`_upgrade_loop` 每轮开头先清理到期项（deadline 已过 →
  `aclose`）。
- 只读属性（worker 线程访问——单变量原子读）：
  - `current_path -> str | None`："direct" / "relay" / None（`isinstance` 判定）；
    HTTP 管道下返回 None。
  - `direct_last_error -> str`：最近一次直连尝试失败原因。
- `stop()`：取消 `_upgrade_task`（`CancelledError` 静默）；尽力 close 所有
  `_retired` 连接（try/except 逐个），再清空集合。
- **占空比注意**：失败场景 10s 周期 × 单次尝试最多 5s 超时（后台，不阻塞前台请求）。

### 2.6 链路可见（贯通 5 处）

| 层 | 文件 | 改动 |
|----|------|------|
| transport | `remote_transport.py` | 2.5 的两个只读属性 |
| client | `remote_client.py` | `transport_path() -> str` / `direct_last_error() -> str`（transport 为 None 时返回 ""） |
| 状态机 | `remote_link.py` | `RemoteLinkStatus` 加 `path: str = ""`、`direct_last_error: str = ""`；`status()` 内取 client（try/except → ""） |
| 前端类型 | `frontend/src/types/index.ts` | `RemoteStatus` 加 `path?: string; direct_last_error?: string` |
| 前端 UI | `frontend/src/sections/RemoteSection.tsx` | Descriptions 加 `Item label="传输链路"`：direct→"直连（P2P 打洞）" / relay→"中继（relay 转发）" / 其他→"—"；`direct_last_error` 非空时以小字提示（Typography.Text type="secondary"） |

---

## §3 实现规范

### 3.1 实施步骤

**步骤 1. 新建 `remote_netutil.py` + 单测**
- 文件: `services/remote_netutil.py`（新 ~40 行）、`tests/test_remote_p2p_lan.py`（新）
- 预估行数: ~80
- 验证点: `probe_lan_ip` 单测（mock socket 成功返回 IP / OSError 返回 None）通过；pyright 0 错误
- 依赖: 无

**步骤 2. client 地址上报修复**
- 文件: `services/remote_transport.py`（~15 行改动）
- 预估行数: 15
- 验证点: 单测——mock `_ClientUdpProtocol.local_addr` 返回 `("0.0.0.0", 5000)` +
  mock `probe_lan_ip` 返回 `"192.168.3.194"` → 断言 LookupMsg.udp_ep 为
  `("192.168.3.194", 5000)`；现有 remote 测试全过
- 依赖: 步骤 1

**步骤 3. 协议扩展：wire + registry + relayd**
- 文件: `services/remote_wire.py`（encode 2 分支 + decode endpoints 分支；~25 行）、
  `services/remote_relayd/registry.py`（NodeEntry/register/update_ep；~20 行）、
  `services/remote_relayd/server.py`（handle_msg 2 分支 + _lookup；~15 行）
- 预估行数: ~60
- 验证点: 单测——registry lan_ep 存取/None 不覆盖；wire encode 含/省略 lan_ep；
  decode endpoints 含/缺 gw_lan 两种；relayd lookup 应答含 gw_lan（复用现有
  `test_server_register_lookup_and_punch_hint` 的测试基建）；现有 relayd 测试全过
- 依赖: 无（可与步骤 1-2 并行）

**步骤 4. gateway 上报 lan_ep**
- 文件: `services/remote_gateway.py`（~20 行）
- 预估行数: 20
- 验证点: 单测——mock `probe_lan_ip`，断言注册消息带 lan_ep（含端口取自
  udp_local_addr）；探测失败 → lan_ep=None；现有 gateway 测试全过
- 依赖: 步骤 3

**步骤 5. client 打洞两段式候选**
- 文件: `services/remote_transport.py`（~30 行）
- 预估行数: 30
- 验证点: 单测——候选构造（=无 gw_lan 时 [gw]；含 gw_lan 时 [gw_lan, gw]；重复去重）；现有测试全过
- 依赖: 步骤 3

**步骤 6. 后台直连升级 + 只读属性**
- 文件: `services/remote_transport.py`（~80 行）
- 预估行数: 80
- 验证点: 单测 3 例——升级成功（假 DirectConnector 返回直连 → `current_path=="direct"`、旧连接延迟关闭）；失败（`direct_last_error` 非空、conn 保持中继）；节流（失败后下一轮尝试间隔 ≥10s，用假时钟/短参数）；
  现有 `test_remote_client.py`/`test_remote_e2e.py` 全过
- 依赖: 步骤 2/5

**步骤 7. 状态贯通（后端 + 前端）**
- 文件: `services/remote_client.py`（~15 行）、`services/remote_link.py`（~15 行）、
  `frontend/src/types/index.ts`（~2 行）、`frontend/src/sections/RemoteSection.tsx`（~15 行）
- 预估行数: ~50
- 验证点: `test_remote_routes.py` 或新增断言——`/api/remote/status` 响应含
  `path`/`direct_last_error` 字段；`npm run build` 通过
- 依赖: 步骤 6

**步骤 8. 回归 + 记录**
- 文件: 无代码；跑全量快集 + pyright + 前端测试；更新 progress 记录
- 验证点: `pytest tests -m "not slow"` 全绿；`cd backend && pyright` 0/0/0；
  前端 build/test 通过
- 依赖: 全部

### 3.2 改动文件清单

| 文件 | 类型 | 预估行数 | 步骤 |
|------|------|---------|------|
| `services/remote_netutil.py` | 新增 | ~40 | 1 |
| `tests/test_remote_p2p_lan.py` | 新增 | ~120（分步累计） | 1-7 |
| `services/remote_transport.py` | 修改 | ~125 | 2/5/6 |
| `services/remote_wire.py` | 修改 | ~25 | 3 |
| `services/remote_relayd/registry.py` | 修改 | ~20 | 3 |
| `services/remote_relayd/server.py` | 修改 | ~15 | 3 |
| `services/remote_gateway.py` | 修改 | ~20 | 4 |
| `services/remote_client.py` | 修改 | ~15 | 7 |
| `services/remote_link.py` | 修改 | ~15 | 7 |
| `frontend/src/types/index.ts` | 修改 | ~2 | 7 |
| `frontend/src/sections/RemoteSection.tsx` | 修改 | ~15 | 7 |

### 3.3 编码规则（本批特有）

- 强类型：新字段全部带类型注解与默认值；禁裸 dict 传递（wire/registry 属既有
  dataclass 边界）
- 兼容：所有协议字段可选（None/缺省不改变现有行为）；relayd 不升级不阻塞
- 注释：更新 `local_addr` 的过时假设注释；`_upgrade_loop` 注明"只试直连、
  不碰中继会话"约束
- 日志：升级成功/失败记 INFO/WARNING（含原因）；路径切换记 INFO

---

## §4 验收标准

### 4.1 功能验收

- [ ] 步骤 1-7 各自单测通过（`pytest tests/test_remote_p2p_lan.py -q` 全绿）
- [ ] `GET /api/remote/status` 响应含 `path`（direct/relay/""）与 `direct_last_error`
- [ ] 前端"远程资源"卡显示"传输链路：直连/中继"（build 通过 + 界面人工确认）
- [ ] 打洞两段式：无 gw_lan 的旧 relayd 场景行为与现状一致（回归）

### 4.2 回归验收

- [ ] `pytest tests -m "not slow"` 全绿（基线：225 项级）
- [ ] `cd backend && pyright` → 0 errors
- [ ] 前端 build / 测试通过（前端基线：89 项级）

### 4.3 架构验收

- [ ] `remote_netutil.py` 归属 `services/`（client/gateway 共用），无循环依赖
- [ ] 协议字段向后兼容（新旧组合矩阵：新 client×旧 relayd、旧 client×新 relayd 均不劣化）
- [ ] 强类型（无裸 dict 新接口）

### 4.4 待办验收（环境依赖，单独标记）

- [ ] **真机打洞成功**（需"主控→节点"网络可达——当前环境 AP 阻断；环境恢复后补测）
- [ ] relayd 重部署（部署新 registry/lookup 后 G2 双向完整生效）

---

## §5 与现有需求文档的关系

- 独立新篇（P2P 传输层修复），与 `2026-10-17-tts-lock-split.md`、
  `2026-10-17-tts-lazy-segmentation.md` 无交集
- 依赖关系：无（本批为传输层基础设施）
- 后续预留：STUN 公网映射探测（跨网打洞）、打洞并行互射（如两段式实测吞吐不足）
