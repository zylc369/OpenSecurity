# 进度: 2026-10-18-node-network-heal

| 步骤 | 状态 | 说明 |
|------|------|------|
| 1. 核心修复（活性检测+UDP重绑） | ✅ | compile OK；pyright 0/0/0；既有 remote 42 passed |
| 2. 测试（test_remote_gateway_heal.py） | ✅ | 3 passed（静默判死/不误杀/UDP 重绑幂等） |
| 3. 全量回归 + 提交 + 真机验收 | ✅ | 全量 274 passed/1 skipped；pyright 0/0/0；提交 07df2f7 + a2a8346；**真机验收通过**（详见证据） |

## 证据

- 步骤 1: `remote_gateway.py` +6 处编辑（SIGNAL_DEAD_SEC 常量 / `_signal_steady` 顶部判死 + recv 刷新 last_rx / `_close_udp()` / 重建路径接入 / stop 收口）；compile OK；pyright 0/0/0；`test_remote_e2e`+`test_remote_relayd`+`test_remote_p2p_lan` 42 passed。
- 步骤 2: `test_remote_gateway_heal.py` 3 passed（1.26s）；回归全套（含并发）46 passed。
  - 过程记录: 测试自身"紧循环无真实 yield"导致 `wait_for` 定时器不触发（挂起）——fake recv 加 `sleep(0.01)` 修复（非业务代码问题）。
- 步骤 3(部分): `pytest tests/ -q` → **273 passed, 1 skipped**（270 基线 + 3 新增）。
- 真机验收（**通过**，节点 `a2a8346`）——节点日志（remote-node.log）完整链条:
  ```
  19:15:28 信令断开（1.00s 后重连）: 信令静默超时（60s 无收包）——重建注册  ← 判死触发（修复核心行为）
  19:15:29 [Errno 51] Network is unreachable（换网中）
  …（退避 1→2→4→8→16→30s 持续重试；期间在热点网络连 relayd 失败: Errno 60/65）
  19:27:06 gateway 已注册（node=OpenSecurityServer）                      ← 切回 WiFi 后自动重新上线
  ```
  主控侧: `state=remote, recover_streak=5, fail_streak=0`（完全恢复）。
  对照: 修复前同类操作=永久 node_offline（需人工重启节点）。
- 环境记录（非 bug）: 用户手机热点网络（10.236.132.x）封禁到 relayd 的出海连接
  （Errno 60/65）——热点期间远程链路不可用属网络环境限制，换回 WiFi 立即成功。
