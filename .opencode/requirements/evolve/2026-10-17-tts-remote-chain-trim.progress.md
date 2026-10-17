# 远程 TTS 链路精简批 —— 执行进度

需求文档: `2026-10-17-tts-remote-chain-trim.md`（Phase 3 审计通过）
状态: Phase 5 实施中

## 架构影响图（6 文件）

```
routes/tts.py（TtsRequest+no_cache）
    └─► services/tts_service.py（P2 删远程质检块; P3 synthesize+no_cache 缓存跳过）
            ▲                        ▲
services/remote_link.py      services/remote_client.py
（_warm_remote_tts            （tts_synth+no_cache → payload）
  → no_cache=True）                    │
                                       └─► [P2P/HTTP payload] → 节点 backend（同代码）
services/remote_gateway.py（P4: STUN 日志 %r——独立一行）

测试: [新] tests/test_tts_no_cache.py（payload/nocache 缓存跳过）
```

依赖顺序: 1 → 2 → 3 → 4（相互独立，顺序执行）

## 步骤进度

- [x] 步骤 1. P2 质检去重（tts_service.py）——23 passed（无依赖测试）
- [x] 步骤 2. P3 no_cache 贯通（4 文件 + test_tts_no_cache 4 例）——15 passed
- [x] 步骤 3. P4 STUN 日志——1 行（%r）
- [x] 步骤 4. 回归——243 passed, 1 skipped；pyright 0/0/0

## 验证点执行记录

- 步骤 1: `pytest test_tts_service/qc_flow/lock_split/qc -q` → 23 passed；`_qc_check` 仅本地路径引用（grep 确认）
- 步骤 2: 15 passed（3+12）；**接口变更传导修复**：3 处测试桩同步加 no_cache（relayd/lock_split/link）
- 步骤 3: 1 行；remote_relayd 套件通过
- 步骤 4: 后端全量 243 passed（239 基线 + 4 新）；pyright 0
- Phase 6 审计修复 3 项：
  1. 远程分支 no_cache 透传缺失（P2/P3 交汇缺口）→ 补透传 + 新增测试
  2. 接口变更下游桩（3 处）→ 同步
  3. **跨文件单例泄漏**（warmup 测试注入实例属性未清理，遮蔽类级 monkeypatch）→ 治本（两测试 finally 复位）+ 防御（新测试先复位单例）

## Phase 记录

- [x] Phase 2 需求文档（2026-10-17-tts-remote-chain-trim.md）
- [x] Phase 3 审计（2 轮 + 纯审计；修复 2 处：日志语义说明 + 测试更新预案）
- [x] Phase 4 执行计划（架构影响图——6 文件，相互独立顺序执行）
- [x] Phase 4.5 Prompt 瘦身检查（不适用）
- [x] Phase 5 实施（步骤 1-4）
- [x] Phase 6 实现审计（2 轮 + 纯审计；修复 3 项如上；最终 243 passed / pyright 0）
