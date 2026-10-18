# 进度: 2026-10-18-node-network-heal

| 步骤 | 状态 | 说明 |
|------|------|------|
| 1. 核心修复（活性检测+UDP重绑） | ✅ | compile OK；pyright 0/0/0；既有 remote 42 passed |
| 2. 测试（test_remote_gateway_heal.py） | ✅ | 3 passed（静默判死/不误杀/UDP 重绑幂等） |
| 3. 全量回归 + 提交 + 真机验收 | 🔄 | 全量 273 passed/1 skipped ✅；pyright 0/0/0 ✅；提交与真机验收进行中 |

## 证据

- 步骤 1: `remote_gateway.py` +6 处编辑（SIGNAL_DEAD_SEC 常量 / `_signal_steady` 顶部判死 + recv 刷新 last_rx / `_close_udp()` / 重建路径接入 / stop 收口）；compile OK；pyright 0/0/0；`test_remote_e2e`+`test_remote_relayd`+`test_remote_p2p_lan` 42 passed。
- 步骤 2: `test_remote_gateway_heal.py` 3 passed（1.26s）；回归全套（含并发）46 passed。
  - 过程记录: 测试自身"紧循环无真实 yield"导致 `wait_for` 定时器不触发（挂起）——fake recv 加 `sleep(0.01)` 修复（非业务代码问题）。
- 步骤 3(部分): `pytest tests/ -q` → **273 passed, 1 skipped**（270 基线 + 3 新增）。
- 真机验收（待）：节点 `update-restart` 后，MacMini 切热点 → ≤90s 内自动恢复注册（`/api/remote/status` 不再 node_offline）→ 切回 WiFi 稳定性确认。
