# 进度：自检噪音修复（2026-09-22）

需求文档: `2026-09-22-selfcheck-noise-fixes.md`

## 步骤状态

| 步骤 | 状态 | 要点 |
|---|---|---|
| 1. evolve prompt 示例去武装 | ✅ 完成 | L47/L215 `xxx`→`片段名`；agents/ 零残留；生产正则 0 匹配 |
| 2. snippet.ts inspectAgentFile + 语法常量 | ✅ 完成 | 四类文件三字段实测 + 缓存失效全对；旧函数已删 |
| 3. security-analysis.ts 消费方 + 三分支 | ✅ 完成 | import 更新；三分支落地；harness 5/5 PASS |
| 4. crypto-analysis.md 补 probe-first | ✅ 完成 | 与 binary 集合一致；全 agent 解析成功；展开 ≈308 行 |
| 5. Phase 6 实现审计 | ✅ 完成 | 2 轮 + 纯审计零问题；调用点单一；旧文案零残留 |
| 6. inspectAgentFile 异常日志（用户追加） | ✅ 完成 | 非 ENOENT 异常 → `[ERROR]`；文件缺失按"是否项目 agent"区分：项目缺失 `[ERROR]`、非项目（内置 build/plan 等）静默 |

## 验证记录

- Step 1: `grep "buwai-rule:xxx" agents/` 零残留；bun 生产正则 0 匹配、PREFIX 快筛 true（空操作）✓
- Step 2: inspectAgentFile 五组实测（build 缺失 / fresh-eyes 无 id 无占位 / web-analysis 有 id 有占位 / fixture v1-v2 缓存失效）✓
- Step 3: `bun import` OK；harness C1-C5 全 PASS（首轮 C4 FAIL 系测试自身 byte/char 切片 bug，已修测试非产品）✓
- Step 4: crypto vs binary 占位符集合 diff 一致；全 agent 解析仿真 0 失败；crypto 140 行、展开 ≈308 行 ✓
- Phase 6: `hasBuwaiExtensionId` 插件/agent 零残留；`buwai-rule` 字面量仅在 snippet.ts 常量；旧 ERROR 文案零残留；verifyMirrors=[]；git diff 逐行复核 ✓
- 追加: 异常日志测试 E1 EISDIR / E2 null 字节路径 → 均产出 `[ERROR] inspectAgentFile 异常`（含 code+message）；E3 ENOENT 无新增日志 ✓；C1-C5 回归全过 ✓
