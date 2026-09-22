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
- 追加: 异常日志测试 E1-E5 全过（真实 snippet.ts 直调：EISDIR×2/非法路径/非项目缺失静默/项目缺失 [ERROR]）✓
- 追加: si-copy2 副本保真性逐字节校验通过（与真身仅差导入路径改写+暴露行）✓
- 追加: C1-C7 全过并连续两轮幂等——含 9 项目 agent 健康扫描零 [ERROR]、项目 agent 缺失报警；测试自身两个 bug（字节切片错位、套件不幂等）已修 ✓

## 重启后运行时验证（23:18 重启）

- 认知契约自检：一致（23:18:26 / 23:19:05 两次插件加载）✓
- xxx 噪音：重启后 0 条（最后一条 23:04:06 属旧进程）✓
- build 会话：`.../build.md 不存在，跳过占位符展开`（无 [ERROR]）✓
- evolve 展开路径：`检测到 buwai-extension-id` + 无 not-found ✓
- **运行时报警实验**：临时改名 `fresh-eyes.md` → 触发 `[ERROR] inspectAgentFile: 项目 Agent 文件缺失`（23:21:15.882）+ 会话跳过行 → 立即恢复（校验和一致、git clean）✓
- 副产物（已披露）：自检会话 `ses_f364b0893ffeYbBhEV0BY7UucZ` + 任务目录 `20260922_232115_36d3_fresh-eyes`
