# TTS 前端多级预取（缓冲目标 2）+ 段间等待 UI 提示 —— 执行进度

需求文档: `2026-10-17-tts-prefetch-depth2-queue-ui.md`
状态: ✅ 全部完成（Phase 2-6）

## 步骤进度

- [x] 步骤 1. C：预取缓冲目标 2 + 首段请求发出即激活
- [x] 步骤 2. D：waiting 状态 + "等待下一段…" UI
- [x] 步骤 3. 回归：前端 90 passed（89 基线 + 1 新） + build ✓

## 验证点执行记录

- 步骤 1: `PREFETCH_DEPTH=2`；start() 内"fetchSeg(0) 后立即 playingStarted=true + pump()"；
  测试更新——"起播前即挂 seg0+seg1+seg2 不超前 seg3"（重写）+ "网络失败"（断言改 filter 同文本 2 次——
  立即预取与重试并发，calls 序为 [甲,乙,丙,甲]）
- 步骤 2: `waiting:boolean`（接口/INITIAL/onended 置位/起播清除）+ TtsSection Tag；
  测试新增"段间等待"（hook-env 加 holdText/release 制造未就绪窗口）；UI 例：
  `等待下一段…`
- 步骤 3: 90 passed（7 files）+ `npm run build` ✓
- 附带：hook-env 加 failText/failTextTimes（定向失败——并发预取下 failNextTimes 会被
  无关请求消耗；"坏段跳过"用例更新为新时序语义）

## Phase 记录

- [x] Phase 2 需求文档
- [x] Phase 3 审计（2 轮 + 纯审计）
- [x] Phase 4 执行计划（2 文件 + 测试，顺序 1→2→3）
- [x] Phase 4.5 Prompt 瘦身检查（不适用）
- [x] Phase 5 实施
- [x] Phase 6 实现审计（2 轮 + 纯审计；修复：测试断言 2 处时序语义更新 + hook-env 定向失败能力）
