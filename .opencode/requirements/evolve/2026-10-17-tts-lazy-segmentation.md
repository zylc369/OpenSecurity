# TTS 惰性分段改造（对齐真实听书场景）—— 需求文档

> 2026-10-17 | 状态: 待确认 | 原则: **交互/行为/逻辑与真实听书一致**（不是"
> 模拟"）——选一个起点 → 向后连续朗读；读书读到哪算哪, 不存在"全书总账"

## §1 背景与目标

**现状问题**（两条独立）：
1. `start()` 时对全文做一次性分段——播放首响**结构上依赖全文计算完成**（791 万字 ≈620ms；更大文本线性放大；"换起点"要重切全文）
2. 播放器持有"全局账本"（总段数 / 总时长 / 总进度条）——**通用播放器惯性带来的自加需求**，与真实听书场景不符

**目标模型**（真实读书场景）：
- **选起点 → 向后连续读**；分支只有：暂停/继续、换起点重读（"起始字符"输入框 + 正文选中文字右键朗读——**本任务一次性完成，不分期**）
- 分段器只回答一个问题："下一段是什么"——**"总数"概念不存在**
- 删除全局账本：依赖全量的显示全部移除或降级为增量语义

**收益**：首响只依赖局部（扫到第一段末尾）；内存 O(播放窗口)；依赖方向修正（播放不再依赖全文）；后端零改动。

## §2 技术方案

### §2.1 分段器：游标式产出接口（`src/utils/segmentText.ts`）

```ts
export interface SegmentFeeder {
  /** 产出下一段（null=文本结束）。惰性：只扫描到本段末尾。 */
  next(): string | null;
  /** 已产出段数（增量语义，供"已读 N 段"类显示）。 */
  readonly producedCount: number;
}
export function createSegmentFeeder(
  text: string, target?: number, hardMax?: number,
  firstTargets?: readonly number[]): SegmentFeeder;
```

- **实现原则（等价性保障）**：与全量版**共享全部子步骤**——把 `splitSentences` 的字符级规则抽为
  `scanSentence(text, pos): { sent: string; nextPos: number }`，feeder 与 `splitSentences` 共用；
  贪心合并 / 预检收段 / cutFirstComma / 超长切分同样抽共享。段序列一致性由共享实现保证（等价性测试兜底）。
- 原 `segmentText()` 保留（测试基准 + 需要全量的场景）。
- ramp 档位：feeder 内部维护"已产段数"驱动 firstTargets（与全量版一致）。

### §2.2 播放器（`src/hooks/useTtsPlayer.ts`）

- `segsRef: string[]` → `feederRef: SegmentFeeder` + `producedRef: Map<number, string>`
  （播放窗口：预取取出的段落表；已播完段删除——内存 O(窗口)）
- 预取协议不变（播放驱动、深度 1）：播 segN 时确保 produced 含 segN+1（无则 `next()`）
- `next()` 返回 null = 文本结束 → 末段播完按自然播完落态（沿用现有 idle 语义）
- 状态简化：
  - 删：`segTotal`、`totalSec`、`computeTotalOf`
  - 保留：`segIndex`（已读段数-1）、`segProgress`、`elapsedSec`、`buffered`、`firstSegMs`、`avgGenMs`、`segSource`/`firstSegSource`
- `start()`：不再全量分段；直接构造 feeder（自 `startIdx` 起）

### §2.3 UI（`src/sections/TtsSection.tsx`）

| 项 | 现状 | 改后 |
|---|---|---|
| 段计数 | `第 {n} / {total} 段` | `已读 {n} 段` |
| 总时长 | `总时长 ≈NN:NN`（全量估算） | **删除** |
| 进度条 | 全条总进度 | 当前段内进度（仅显示，不拖动） |
| 首段生成 / 平均生成 / 已缓冲 / 已播时长 | — | 保留 |

- 起点交互（**一次性完成，不分期**）：
  ① "起始字符"输入框（已有）
  ② PC Web：正文选中文字 → 右键弹出"从选中处朗读" → 从选中起点开始朗读
     （直到完成/暂停/停止）——配套正文阅读视图，见 §2.5
- 文案兜底："正在朗读"区不出现任何 `M`（总数）类数字（grep 验证）

### §2.5 正文阅读视图 + 选中文字朗读（一次性的组成部分）

**载体**：TTS 测试台新增"正文阅读视图"区（可滚动）——数据源：当前 txt 内容或"自定义文字"。

**渲染策略（791 万字不可全量 DOM）**：窗口化渲染——按块懒渲染视口附近内容
（块 + IntersectionObserver 触底续渲；块与字符偏移对齐，每块元素带 data-offset），
滚动流畅、DOM 节点数受控。

**选中→朗读**：`window.getSelection()` 取选区 → 选区起点在全文中的字符偏移
（= 所属块 data-offset + 块内偏移）→ 右键 contextmenu 弹出菜单（"从选中处朗读"）
→ 调 `player.start(全文, { ..., startIdx: 偏移 })`。
- 右键菜单仅在"有非空选中"时出现朗读项（无选中不干扰原生菜单）
- 朗读中再次选词朗读 = 以新起点重新起播（沿用"新 start 停旧"单实例语义）

### §2.6 后端

零改动（每段仍为普通 POST /api/tts；来源标识/预热/质检修复已就位）。

## §3 实现规范

### §3.1 实施步骤

```
步骤 1. scanSentence 抽取 + createSegmentFeeder 实现
  - 文件: src/utils/segmentText.ts（新增 ~120 行，改 splitSentences 复用 ~30 行）
  - 验证点: 等价性单测——既有全部测试文本下, feeder 全量拉取 === segmentText() 输出
  - 依赖: 无

步骤 2. feeder 独立单测（惰性 + 边界）
  - 文件: src/utils/segmentText.feeder.test.ts（新增 ~110 行）
  - 验证点: ①791 万字文本 next() 第 1 次调用 <5ms（不扫全文）②空文本/超短/
    超长句/预检复现串/尾段并回 与全量版逐段一致 ③producedCount 递增正确
  - 依赖: 1

步骤 3. 播放器切换（feeder 消费 + 状态简化）
  - 文件: src/hooks/useTtsPlayer.ts（改 ~120 行）
  - 验证点: hook 既有测试同步通过; 新增"段序不重不漏"用例（预取窗口拉满后
    与全量版段序一致）; 预取/接力/自然播完/坏段跳过回归
  - 依赖: 1

步骤 4. UI 简化 + 测试同步
  - 文件: src/sections/TtsSection.tsx + hook-env/测试（改 ~140 行）
  - 验证点: tsc/vitest/build 全绿; 播放卡 grep 无 totalSec/segTotal/总时长残留
  - 依赖: 3

步骤 5. 正文阅读视图（窗口化渲染）
  - 文件: src/sections/TtsSection.tsx（新增视图区, ~180 行）
  - 验证点: 791 万字载入后 DOM 节点数受控（滚动不卡）; 块 data-offset 与
    全文偏移对得上（抽查 3 处）; 空文本占位正常
  - 依赖: 4

步骤 6. 选中文字 → 右键 → 朗读
  - 文件: src/sections/TtsSection.tsx（~80 行）
  - 验证点: 选中文字右键出现"从选中处朗读" → 点击从该偏移起播;
    无选中右键不弹; 播放中再次选词朗读=新旧切换正常
  - 依赖: 5

步骤 7. 全量回归 + 真机验证 + 收口
  - 验证点: 前端全部测试绿 + tsc + build; 真机 791 万字：点击试听立即起播/
    选词朗读/连续播放/换起点/暂停继续/停止全正常; 提交 + CI 绿
  - 依赖: 6
```

## §4 验收标准

- **功能**：起始点向后连续读；暂停/继续/停止；换起点重播（输入框 + 正文选词右键朗读）；
  段序与全量版完全一致；全链路无"总数/总时长"依赖
- **回归**：前端全部测试绿（同步后）+ build；CI 双绿；后端零改动不受影响
- **架构**：feeder 纯函数可测；播放内存 O(窗口)；正文视图窗口化渲染（DOM 受控）；
  791 万字场景 next() 首调 <5ms（实测断言）

## §5 与现有文档的关系

- 承接本会话讨论结论（"真实读书场景"原则；总段数/总时长=全局账本，删除）
- 与已落地项（来源标识 / 远程预热 / 质检修复）无冲突
- **锁拆分**（后端：本地推理容量 1 队列 + 远程独立 + 缓存细粒度锁）另立需求文档，待排期
