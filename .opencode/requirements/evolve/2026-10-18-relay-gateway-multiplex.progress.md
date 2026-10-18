# 进度: 2026-10-18-relay-gateway-multiplex

| 步骤 | 状态 | 说明 |
|------|------|------|
| 1. 测试先行（慢 stub + 并发测试） | ✅ | **红证据**：用例1 峰值=1（串行）；用例2 Ping 被阻塞 1218ms |
| 2. 修复 gateway 多路复用 | ✅ | 并发测试 4 passed；remote 回归 42 passed；pyright 0/0/0 |
| 3. 全量回归 | ✅ | `270 passed, 1 skipped`（266+4）；pyright 0/0/0 |
| 4. 真机复测（推送后） | ⬜ | 待用户更新并重启节点 |

## 证据

- 步骤 1 红（修复前）：
  - `test_relay_two_concurrent_no_queue`: `stub 并发峰值=1（期望 2——串行时=1）`
  - `test_ping_not_blocked_by_slow_request`: `协议 Ping 被阻塞 1218ms（期望 <1000）`
  - 用例 3/4 通过（防回归项）
- 测试修正记录（属步骤 1 的测试自纠）：
  - transport 懒启动 → `_force_relay` 先发一笔建立会话；
  - "强制落中继"需同时置脏 `entry.ep` **与** `entry.lan_ep`（两段式打洞 LAN 候选否则回环打通）；
  - `client.embed` 实际路径 `/embed`（stub key 修正）；
  - 顺修 `test_remote_e2e` 场景 2"名不副实"：加 `entry.lan_ep` 置脏 + `current_path == "relay"` 断言（修正后 3 passed）；
  - 顺修 `conftest.py` 两处钩子名（`_pytest_configure`→`pytest_configure` 等——原下划线前缀非有效钩子，slow marker 注册从未生效）。
- 步骤 2 绿：
  - 并发测试 `4 passed in 36.68s`；`test_remote_e2e/test_remote_relayd/test_remote_p2p_lan` `42 passed`；
  - pyright 全量 `0 errors, 0 warnings, 0 notes`。
- 遗留（既有行为，未扩大改动面，如实记录）：
  1. teardown 偶见 `Task was destroyed but it is pending`（`RelayConnection._pump_loop`）——`RemoteTransport.stop()` 未显式回收连接 pump；不影响测试结论，可后续独立小修。
  2. 全量首跑 1 次偶发：`test_remote_relayd::test_server_wrong_psk_rejected`（OSError）——单跑/连跑/全量重跑均不复现；该用例路径（relayd failban）与本批改动（gateway）无交集——留观。
