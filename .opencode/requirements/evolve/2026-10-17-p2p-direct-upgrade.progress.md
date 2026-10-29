# P2P 直连修复批 —— 执行进度

需求文档: `2026-10-17-p2p-direct-upgrade.md`（295 行，Phase 3 审计通过）
状态: ✅ 全部完成（Phase 2-6）

## 架构影响图（11 文件）

```
[新] services/remote_netutil.py  probe_lan_ip()
        │ import
        ├──────────────► services/remote_transport.py（2/5/6 步）
        │                     │ 上报/候选/升级/属性
        │                     ├─► services/remote_client.py ─► services/remote_link.py
        │                     │        (transport_path/direct_last_error)   (RemoteLinkStatus+2 字段)
        │                     │                                               │
        │                     │                                routes/remote.py（无改，dataclass 序列化）
        │                     │                                               └─► 前端 types/index.ts + RemoteSection.tsx
        │                     └─► services/remote_wire.py（LookupResp.gw_lan / SignalRegister|UpdateEp.lan_ep）
        │
        └──────────────► services/remote_gateway.py（注册/刷新带 lan_ep）
                              │
                              └─► services/remote_relayd/registry.py（NodeEntry.lan_ep）
                                       └─► services/remote_relayd/server.py（handle_msg/_lookup）

测试: [新] tests/test_remote_p2p_lan.py（分步累计 ~120 行）
```

依赖顺序: 1 → 3 → 2 → 4 → 5 → 6 → 7 → 8（1/3 可先行；2 依赖 1；4/5 依赖 3；6 依赖 2+5；7 依赖 6）

## 步骤进度

- [x] 步骤 1. remote_netutil.py + 单测（pyright 0；3 passed）
- [x] 步骤 2. client 地址上报修复（resolve_udp_ep；+3 测试）
- [x] 步骤 3. 协议扩展（wire + registry + relayd；+4 测试）
- [x] 步骤 4. gateway 上报 lan_ep（_lan_ep；+1 测试）
- [x] 步骤 5. client 打洞两段式候选（build_punch_candidates；+1 测试）
- [x] 步骤 6. 后台直连升级 + 只读属性（+1 e2e 测试，真升级链路验证）
- [x] 步骤 7. 状态贯通（后端 + 前端；status 响应断言 + build 通过）
- [x] 步骤 8. 回归 + 记录（后端 239 passed / 前端 89 passed / pyright 0）

## 验证点执行记录

- 步骤 1: `pytest tests/test_remote_p2p_lan.py -q` → 3 passed；pyright 0（修 reportAny 1 处：getsockname Any→cast）
- 步骤 2: +3 测试（通配替换/有效保留/探测失败保持）；现有 remote 套件 36 passed
- 步骤 3: +4 测试（registry roundtrip/wire encode/gw_lan 双态/_lookup 应答）；53 passed（修测试桩：RelayServer(psk)/get_extra_info）
- 步骤 4: +1 测试（_lan_ep 三态）；11 passed
- 步骤 5: +1 测试（候选顺序/过滤/去重）；**回归发现并更新既有测试**：test_transport_request_direct_and_relay 的"强制中继"需同步打掉 lan_ep（LAN 候选真实打通=修复生效的证据）
- 步骤 6: +1 e2e 测试（真实中继→失败记录→自动升级直连→升级后可用）；13 passed
- 步骤 7: +1 测试（/api/remote/status 含 path/direct_last_error）；14 passed；pyright 0（修 reportAny：r.json() Any→cast）；前端 tsc/build 通过
- 步骤 8: 后端全量快集 239 passed, 1 skipped；前端 89 passed (7 files)

## Phase 记录

- [x] Phase 2 需求文档（2026-10-17-p2p-direct-upgrade.md）
- [x] Phase 3 审计（2 轮 + 纯审计；修复 8 处：初稿 6 + 边界 1 + 命名统一 1）
- [x] Phase 4 执行计划（架构影响图 + 顺序）
- [x] Phase 4.5 Prompt 瘦身检查（不适用：本批不涉及 agent prompt）
- [x] Phase 5 实施（步骤 1-8）
- [x] Phase 6 实现审计（2 轮 + 纯审计）
  - 第 1 轮：1 处修复（_upgrade_loop cleanup 移入 try——异常防护）
  - 第 2 轮/纯审计：零问题（接口一致性：RemoteLinkStatus 唯一构造点已更新、消费闭环完整）
  - 最终：14 passed / pyright 0 / 回归 239+1skip / 前端 89

