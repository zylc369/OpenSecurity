# 进度: 2026-10-18-relay-gateway-multiplex

| 步骤 | 状态 | 说明 |
|------|------|------|
| 1. 测试先行（慢 stub + 并发测试） | ✅ | **红证据**：用例1 峰值=1（串行）；用例2 Ping 被阻塞 1218ms |
| 2. 修复 gateway 多路复用 | ✅ | 并发测试 4 passed；remote 回归 42 passed；pyright 0/0/0 |
| 3. 全量回归 | ✅ | `270 passed, 1 skipped`（266+4）；pyright 0/0/0 |
| 4. 真机复测（推送后） | ✅ | 节点自动更新至 `6a08623`（update-restart 4s 重启）；两笔"请求进入"**同一毫秒** + 双 worker 并行；wall 4.97~5.06s（修复前 5.30s）；单笔 3.21s 无回归 |

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
- 步骤 4 真机复测（节点 `6a08623`，自动触发 update-restart）：
  - 多路复用铁证：两笔"请求进入" `10:33:17,198` **同一毫秒**（修复前=后笔跟随前笔"本地合成完成"+15~40ms）；双 worker 并行处理（3456ms / 3510ms 同时开跑）；
  - wall：4.97~5.06s（修复前同场景 5.30s）；A≈B（同刻完成、无排队链）；
  - 单笔对照 3.21s（≈修复前 A 笔 3.19s——无回归）；
  - 新观察（如实）：并发时单笔 worker 1.9s→3.45s（节点 GPU 共享争用）——并行的收益 = 公平/顺序确定，非总时长减半；
  - 后续可选（未做，需产品决策）："首段优先"调度——首段独占先出声（~3.2s）、预取段在首段开跑后跟进；与入口多路复用不冲突，可叠加。
