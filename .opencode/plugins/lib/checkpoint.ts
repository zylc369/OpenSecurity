import {
  CHECKPOINT_TOOL_INTERVAL,
  CHECKPOINT_TIME_INTERVAL_MS,
  ENV_KEY_COGNITION_CHECKPOINT,
} from "./constants";
import { cognition } from "./cognition";
import { getCachedConfig } from "./control-config";

/**
 * 认知检查点：触发判定与文本渲染。
 *
 * 目的：把"时间 / 实验次数"这类 AI 无感知的信息变成可见数字，
 * 并强制三条动作（更新台账 / 枚举从未被当过变量的条件 / 跑掉最能改变判断的未测条件），
 * 第 4 条按卡壳条件触发 stuck-protocol。
 *
 * 开关：COGNITION_CHECKPOINT_ENABLED（控制台配置，默认开启；"0"/"false" 禁用）。
 * 除开关读取外均为纯逻辑，便于 harness 验证。
 */

/** 触发判定输入（SessionData 的字段子集；SessionData implements 本接口，字段维护见 session-manager.ts） */
export interface CheckpointTriggerStats {
  /** 累计工具调用次数 */
  toolCallCount: number;
  /** 上次检查点时的工具调用计数 */
  lastCheckpointToolCount: number;
  /** 上次检查点时间戳（毫秒） */
  lastCheckpointAt: number;
}

/** 渲染输入（SessionData implements 本接口；elapsedMinutes 为其派生 getter） */
export interface CheckpointRenderData {
  /** 检查点序号（本次） */
  checkpointCount: number;
  /** 会话已运行分钟数 */
  elapsedMinutes: number;
  /** 累计工具调用次数 */
  toolCallCount: number;
  /** 累计命令调用次数 */
  commandCallCount: number;
}

/** 开关判定（与 RESUME_ANALYSIS_ENABLED 同规则）：未设置/其他值 → 启用；"0" 或 "false"（忽略大小写）→ 禁用 */
function isCheckpointSwitchOn(raw: string | undefined): boolean {
  const value = raw?.toLowerCase();
  if (value === undefined) return true;
  if (value === "0") return false;
  if (value === "false") return false;
  return true;
}

/** 阈值判定：先查开关，再看工具调用数/时间（先到者即触发） */
export function shouldTriggerCheckpoint(
  stats: CheckpointTriggerStats,
  now: number,
): boolean {
  if (!isCheckpointSwitchOn(getCachedConfig()[ENV_KEY_COGNITION_CHECKPOINT])) {
    return false;
  }
  const toolsSince = stats.toolCallCount - stats.lastCheckpointToolCount;
  const timeSince = now - stats.lastCheckpointAt;
  return (
    toolsSince >= CHECKPOINT_TOOL_INTERVAL ||
    timeSince >= CHECKPOINT_TIME_INTERVAL_MS
  );
}

/** 渲染检查点文本（注入 system prompt） */
export function renderCheckpointText(data: CheckpointRenderData): string {
  return `
## 认知检查点 序号#${data.checkpointCount}
（已运行 ${data.elapsedMinutes} 分钟；工具调用 ${data.toolCallCount} 次，其中命令 ${data.commandCallCount} 次）

1. 台账更新：$ROOT_TASK_DIR/${cognition.ledgerFilename} 的${cognition.sections.conclusions}/${cognition.sections.untested}最后更新在什么时候？现在补一行。
2. 最近一批实验的共同前提是什么？哪个条件从未被当过变量？写进"${cognition.sections.untested}"。
3. 从"${cognition.sections.untested}"挑一项立刻跑（挑选标准：万一结果与预期不一样，能推翻当前结论吗？能，优先）。先写预期结果，再跑，不因预期失败而跳过。
4. 同一方向连续失败 ≥5 次 → 执行 stuck-protocol skill。`;
}
