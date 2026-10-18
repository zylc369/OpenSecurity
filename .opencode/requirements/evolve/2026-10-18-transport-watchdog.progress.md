# transport-watchdog 进度

## 步骤状态

| 步骤 | 状态 | 验证证据 |
|---|---|---|
| 0. 需求文档（含审计 2 轮修复 + 纯审计） | ✅ | `2026-10-18-transport-watchdog.md` 定稿；审计修复 3+1 处 |
| 1. 消息级跟踪日志（C） | ✅ | `_handle_job` 3 处日志 + 往返耗时基准；`test_message_tracking_logs` 绿 |
| 2. 看门狗核心（A）测试先行 | ✅ | 先红（TypeError 配置字段不存在）→ 实现 → 绿；`watchdog_sec`/`probe_wait_sec` 配置 + `_probe_conn` + 分段等待 |
| 3. TTS 超时收敛（B） | ✅ | `RemoteConsoleClient.TTS_TIMEOUT_SEC = 90.0`；`test_tts_timeout_converged` 绿 |
| 4. 全量回归 | ✅ | **278 passed, 1 skipped**（274+4）；pyright 0/0/0 |
| 5. 审计实现（Phase 6） | ✅ | 2 轮 diff 逐行审 + 对照需求文档逐项验证 = 零问题；纯审计轮通过 |
| 6. 真机验证 + 提交 | ✅ | 主控重启（PID 42673）；试听 HTTP 200 / 4.46s 正常；日志实证
`api.req 已发送: ...（id=12, 路径=中继, 等待响应）` + `api.resp 已收到: id=12（往返 437ms）` + TTS `id=11（往返 4449ms）` |

## 备注

- 重启主控时 stdout 重定向到 control.log（与 app logger 产生双写冗余行——不影响功能；
  后续自然重启改回 control-stdout.log 惯例）。

## 改动清单

- `services/remote_transport.py`:
  - `TransportConfig` +2 字段（`watchdog_sec=12.0`, `probe_wait_sec=5.0`）
  - `_handle_job`: 消息级日志（已发送/已收到/失败带 msg_id+耗时）+ 分段等待看门狗循环
  - `_probe_conn()` 新增（loop 内直发 ping 不重建）
- `services/remote_client.py`: `TTS_TIMEOUT_SEC` 600→90 + 注释更新
- `tests/test_remote_transport_watchdog.py` 新增（4 用例：假活快速失败/慢但健康不误杀/日志成对/超时收敛）

## 实施中遇到的问题与修复

1. **测试第 2/3 例挂起**（90s+）：重放脚本定位 → 测试侧 bug——`ApiResp` 构造缺 `mime` 参数
   （`TypeError` 被 task 吞掉 → "响应"永不发出 → 看门狗正确持续探测等待）。
   修复：补 `mime="application/json"`。**顺带确认实现行为正确**（探测健康 → 持续等待 = 预期）。
2. **`TTS_TIMEOUT_SEC` 是类内常量**（`RemoteConsoleClient.TTS_TIMEOUT_SEC`）非模块级——测试 import 方式修正。

## 待办

- [ ] Phase 6 审计（2 轮+纯审计）
- [ ] 真机验证：部署后正常试听，确认日志出现"api.req 已发送 / api.resp 已收到"（含 msg_id）
- [ ] review 修复批（如有）
- [ ] 提交
