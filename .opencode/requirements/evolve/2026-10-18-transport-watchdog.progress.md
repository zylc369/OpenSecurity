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

## review 修复批（提交 fab5319 后外部审查发现，全部修复）

| # | 发现（severity） | 修复 |
|---|---|---|
| F1 | 看门狗探测的是 `self._conn` 而非"请求所在连接"——假阴性（探到健康新会话→请求等满超时）/假阳性（探到死新会话→误杀健康请求） | `_probe_conn(conn)` 传请求连接；新增回归用例 `test_watchdog_probes_request_conn_not_current`（反向验证：还原=红 10s 超时，修复=绿 ~1.5s"看门狗"） |
| F2 | 探测窗口内到达的响应被丢弃（探测失败后直接 raise，不复查 fut） | 失败分支前复查 `fut.done()` → 优先交付；新增用例 `test_watchdog_delivers_response_arriving_in_probe_window` |
| F4 | 日志通道被心跳占满（512 条中 510 条是 `/api/remote/health`，~4.2MB/天） | `_QUIET_LOG_PATHS`——健康探测路径不记"已发送/已收到"（失败仍记） |
| F5a | 3 个用例标 slow 会被日常跳过（实际仅秒级） | 移除 slow 标记（日常回归可守） |
| F5b | 本文件"待办"段与表格矛盾 | 本节更新 |
| F3 | TTS 90s 冷启动余量缺实测 | 见下"冷启动实测" |

**验证**：全量 **280 passed, 1 skipped**；pyright 0/0/0；F1 反向验证红→绿。

**记录（改动外，未修，独立问题）**：
- `_get_json`/`_put_json` 丢弃 timeout 参数（`probe_health` 3s 变 30s）——review 改动外观察。
- `audit_middleware` 把 WAV 二进制 body 原样写日志（control.log 出现 NUL 字节，grep 需 `-a`）——先于本提交存在。
- `_upgrade_loop` teardown 的 "Task was destroyed but it is pending"（测试环境杂音）。

## 冷启动实测（F3，通过）

节点 `update-restart`（a2a8346→1a15bd0，冷启动）后立刻试听第一笔：

- 主控侧：HTTP 200、**总耗时 5.63s**（远程往返 5628ms）
- 节点侧：`模型加载完成(+预加载) 5.3s` → `本地预热完成: worker 2/2 + 质检链路`（23:55:02）→ 首笔合成 `生成 3678ms`（rtf 0.711）

**结论**：当前部署链路（update-restart 自带预加载）下冷启动最坏 ~6s，**90s 上限有 15 倍余量**
（对照 review 提供的暖态历史最坏 31.2s，90s 仍有 ~3 倍）。冷态超 90s 需"无预加载 + 首次装依赖"
的极端路径，此时主控 fallback 本地（功能可用），节点侧继续完成（白耗）——留观。
