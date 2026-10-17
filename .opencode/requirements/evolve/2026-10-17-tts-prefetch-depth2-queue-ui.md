# 需求文档：TTS 前端多级预取（缓冲目标 2）+ 段间等待 UI 提示

> 状态: Phase 2 草稿
> 来源: 2026-10-17 实机验收复盘（段间停顿时序重建：预取深度 1 在"短段接长段"时供不上）
> 配套: `2026-10-17-tts-parallel-workers.md`（B——本批的 C/D 是并行化的前端配套与体验件）

---

## §1 背景与目标

### 1.1 背景

1. **预取深度 1 的临界停顿**（实机时序实锤）：段 N+1 的"生成+传输"时长超过段 N
   的播放时长时（如 26 字段播 8s，后随 91 字段处理 14.3s），段间出现静默等待。
   现状 `PREFETCH_DEPTH = 1` 且"开播后才允许预取"（`playingStartedRef` 门控）——
   首段生成期（数秒）内零预取，全程任何时刻队列里最多 1 段未完成。
2. **等待期无 UI 反馈**：段间缓冲等待只有 console log（`缓冲等待 Xms`），
   界面仍显示"正在朗读"——用户不知道在等什么。

### 1.2 目标

| # | 目标 | 验收口径 |
|---|------|---------|
| C | 预取缓冲目标 1→2（含首段请求发出即激活预取） | 单测：起播前/后 pump 均挂出至 nextPlay+2 |
| D | 段间等待时 UI 显示"缓冲中"提示 | 单测：等待置位/就绪清除；build 通过 |

### 1.3 非目标

- 不改播放器窗口回收/接力语义（O(窗口) 内存纪律保持）
- 不做"起播前等两段就绪"（首段等待不加长——预取只是"后台先跑"）
- 后端并行属 B 批（独立文档）

---

## §2 技术方案

### 2.1 C：多级预取（`src/hooks/useTtsPlayer.ts`）

1. `PREFETCH_DEPTH = 1` → `2`；注释更新：多级预取的目的是"为并行 worker 供料 +
   吸收单次波动"；停播时最多浪费 2 段（abort 会取消在途 fetch；节点侧已生成的
   会留在节点缓存，不构成真实损失）。
2. `start()` 内激活时序调整——现状"开播后才允许预取"（`playingStartedRef`
   在 playSeg 首播处才置 true → 首段生成期零预取）改为"**首段请求发出即激活**"：
   ```ts
   fetchSeg(0, ac.signal).catch(() => { /* playSeg 侧统一处理 */ });
   nextFetchRef.current = 1;
   playingStartedRef.current = true;   // 新增: 立即激活（不再等首播）
   pump();                             // 新增: 立即挂出 seg1+seg2（缓冲目标 2）
   ```
   - `playSeg` 内的 `playingStartedRef.current = true` 保留（幂等）。
   - `cleanup()` 的 `playingStartedRef.current = false` 不变（stop 语义不变）。
   - pump 循环条件/500ms 保底定时器不变（只改深度常量与激活时机）。
3. `fetchSeg` 已按 `blobPromises` map 管理多段并发——无需改（两段并发 fetch 天然成立）。

### 2.2 D：段间等待 UI 提示

1. `PlayerState` 加 `waiting: boolean`（`INITIAL` 加 `waiting: false`）。
2. 置位：`audio.onended`（现状设 `waitStartRef` 处）同步
   `setState(s => ({...s, waiting: true}))`。
3. 清除：`playSeg` 起播区（现状 "seg 开始播放" 分支）置 `waiting: false`。
   - 就绪段无需等待时：置位→清除发生在同一批次（React 18 自动批处理）——
     界面不闪；真等待时保持到就绪。
4. UI（`src/sections/TtsSection.tsx` 播放卡标题行）：`status==="playing" &&
   waiting` 时在"正在朗读"旁渲染 `<Tag color="processing">等待下一段…</Tag>`。

---

## §3 实现规范

### 3.1 实施步骤

**步骤 1. C：深度 2 + 激活时序**
- 文件: `src/hooks/useTtsPlayer.ts`（~10 行）
- 预估行数: 10
- 验证点: 前端单测——起播前 `start()` 即发出 seg1+seg2 请求（fetch mock 计数 = 3
  含首段）；起播后维持"挂到 nextPlay+2"；停播 abort 取消在途
- 依赖: 无

**步骤 2. D：waiting 状态 + UI**
- 文件: `src/hooks/useTtsPlayer.ts`（~8 行）、`src/sections/TtsSection.tsx`（~8 行）
- 预估行数: ~16
- 验证点: 前端单测——段间等待时 `waiting=true`、下一段起播清除；build 通过
- 依赖: 无

**步骤 3. 回归**
- 验证点: 前端 `npm test`（89 基线 + 新增）+ `npm run build`；后端不受影响
- 依赖: 1/2

### 3.2 改动文件清单

| 文件 | 类型 | 预估行数 | 步骤 |
|------|------|---------|------|
| `src/hooks/useTtsPlayer.ts` | 修改 | ~18 | 1/2 |
| `src/sections/TtsSection.tsx` | 修改 | ~8 | 2 |
| 前端测试文件（hook 用例） | 修改/新增 | ~60 | 1/2 |

### 3.3 编码规则

- 注释同步：`PREFETCH_DEPTH` 附近的"本地合成为单 GPU 串行队列——多挂无收益"
  论断更新为"并行 worker 后多挂即供料；串行下损失极小且为并行前置件"
- 不引入新依赖；沿用现有 hook 测试基建（jsdom + FakeAudio）

---

## §4 验收标准

### 4.1 功能验收

- [ ] 起播前预取已挂出 seg1+seg2（单测断言请求序）
- [ ] 段间等待 `waiting` 状态置位/清除正确（单测）
- [ ] UI "等待下一段…" 提示在真实等待时可见（build + 使用确认）

### 4.2 回归验收

- [ ] 前端 `npm test` 全绿（89 基线 + 新增）；`npm run build` 通过
- [ ] 后端快集不受影响（无后端改动——跑一遍确认）

### 4.3 架构验收

- [ ] 不破坏窗口回收与"接力式预取"语义（内存 O(窗口)）
- [ ] 与 B（并行 worker）组合语义：深度 2 的请求即并行 worker 的供料

---

## §5 与现有需求文档的关系

- 本批 C/D 与 `2026-10-17-tts-parallel-workers.md`（B）配套：C 为 B 的前端供料，
  B 为 C 的价值放大器
- 不触碰 `2026-10-17-tts-lazy-segmentation.md` 的 feeder/游标协议
