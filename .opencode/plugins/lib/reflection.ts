import { join } from "path";
import { statSync } from "fs";
import { ctx } from "./context";
import { debugLog } from "./logging";
import { SessionData } from "./session-manager";
import { cognition } from "./cognition";
import { getCachedConfig } from "./control-config";
import {
  SECURITY_ANALYSIS_AGENTS,
  ENV_KEY_REFLECT_NUDGE,
  ENV_KEY_REFLECT_NUDGE_INTERVAL_MIN,
} from "./constants";

// ─── 反思系统共用逻辑（两通道单一来源）────────────────────────────
//
// 反思有两个投递通道，共用本模块的开关、到期判定、守卫与状态更新：
//   忙时通道 = 反思纸条（bash 结果末尾附加，不创建消息、不夺取响应计划主导权，
//             失败模式=被忽略）—— plugins/security-analysis.ts 的 tool.execute.after 调用
//   空闲通道 = 反思唤醒（会话空闲时 promptAsync 合成用户消息，自带续接指令）
//             —— plugins/lib/persistence.ts 的 maybeResumeAnalysis 调用（优先于 resume）
// 判定规范的权威全文在 skills/reflection-protocol/SKILL.md；本模块只负责时机与投递。

/** 反思纸条标记（附加到 bash 输出末尾的定界行；复读型命令命中即跳过再附） */
export const REFLECT_NUDGE_MARKER = "<系统·反思提醒>";
export const REFLECT_NUDGE_END_MARKER = "</系统·反思提醒>";

/**
 * 生成动态完成标记（resume 与反思唤醒共用）。
 * 动态化的目的：避免 LLM 学会"拒绝输出 >>>COMPLETE<<<"后污染所有后续注入轮次；
 * 完成检测用精确匹配（本次植入的具体值存入 session.resumeMarker，
 * 下一轮 idle 检查 last assistant 文本是否原样包含它）。
 * 唤醒消息种下标记的意义：任务完成后的空闲会话不会再被唤醒/resume 反复打扰。
 */
export function generateCompletionMarker(): string {
  const hash = Math.floor(Math.random() * 0x10000)
    .toString(16)
    .padStart(4, "0");
  return `>>>COMPLETE-${hash}<<<`;
}

// ── 配置缺失日志节流（忙通道每 bash 检查一次配置——缺失时只打一次防刷屏，
//    取到有效值后重置，下一轮缺失可再报）────────────────────────
let reflectEnabledMissingLogged = false;
let reflectIntervalMissingLogged = false;

/**
 * 反思总开关（反思纸条 + 反思唤醒两通道共用）。
 * 生效值（默认开启）由服务端经 /api/config 返回——"0"/"false"=禁用;
 * 未取到生效值 → 不启用（fail-safe，记排查日志; 默认值唯一权威在服务端）。
 * configReader 注入点供测试使用（生产默认 getCachedConfig）。
 */
export function isReflectEnabled(
  configReader: () => Record<string, string> = getCachedConfig,
): boolean {
  const raw = configReader()[ENV_KEY_REFLECT_NUDGE]?.toLowerCase();
  if (raw === undefined || raw === "") {
    if (!reflectEnabledMissingLogged) {
      debugLog(
        `反思: ${ENV_KEY_REFLECT_NUDGE} 未取到生效值（服务端未声明默认或控制台不可达），反思功能不启用`,
      );
      reflectEnabledMissingLogged = true;
    }
    return false;
  }
  reflectEnabledMissingLogged = false;
  return !(raw === "0" || raw === "false");
}

/**
 * 反思到期间隔（毫秒）。生效值（含默认 30 分钟）由服务端经 /api/config 返回;
 * 未取到/非法 → Infinity（永不到期 → 两通道均不注入，记排查日志）。
 * configReader 注入点供测试使用（生产默认 getCachedConfig）。
 */
export function getReflectIntervalMs(
  configReader: () => Record<string, string> = getCachedConfig,
): number {
  const min = Number(configReader()[ENV_KEY_REFLECT_NUDGE_INTERVAL_MIN]);
  if (!Number.isFinite(min) || min <= 0) {
    if (!reflectIntervalMissingLogged) {
      debugLog(
        `反思: ${ENV_KEY_REFLECT_NUDGE_INTERVAL_MIN} 未取到生效值或非法（应为正数分钟），反思到期判定不生效`,
      );
      reflectIntervalMissingLogged = true;
    }
    return Number.POSITIVE_INFINITY;
  }
  reflectIntervalMissingLogged = false;
  return min * 60_000;
}

/** 反思是否到期（两通道共用的时机判定） */
export function isReflectionDue(session: SessionData): boolean {
  return Date.now() - session.lastReflectionAt >= getReflectIntervalMs();
}

/**
 * 反思触发的状态更新：先计算差值再占位（顺序敏感——先占位会永远渲染出 0）。
 * 本函数是 lastReflectionAt / reflectionCount / lastReflectionToolCount 的唯一更新点。
 */
export function markReflectionFired(session: SessionData): {
  sinceMin: number;
  sinceTools: number;
} {
  const now = Date.now();
  const sinceMin = Math.max(
    1,
    Math.round((now - session.lastReflectionAt) / 60000),
  );
  const sinceTools = session.toolCallCount - session.lastReflectionToolCount;
  session.lastReflectionAt = now;
  session.lastReflectionToolCount = session.toolCallCount;
  session.reflectionCount++;
  return { sinceMin, sinceTools };
}

/** 共同守卫：仅根会话 + 五分析 agent（子 agent 不持有台账）且有任务目录 */
function isReflectionEligible(session: SessionData): boolean {
  return (
    session.isRootAgent &&
    SECURITY_ANALYSIS_AGENTS.includes(session.agentName) &&
    !!session.getTaskDir()
  );
}

// ─── 忙时通道：反思纸条 ───────────────────────────────────────────

/** 渲染反思纸条（动态数字含台账 mtime） */
export function renderReflectNudge(
  session: SessionData,
  sinceMin: number,
  sinceTools: number,
): string {
  let ledgerNote = "台账尚未创建";
  try {
    const dir = session.rootTaskDir || session.getTaskDir();
    const st = statSync(join(dir!, cognition.ledgerFilename));
    ledgerNote = `台账 ${Math.max(1, Math.round((Date.now() - st.mtimeMs) / 60000))} 分钟未更新`;
  } catch {
    // ledger 不存在时用默认文案
  }
  return `${REFLECT_NUDGE_MARKER}
距上次盘点 ${sinceMin} 分钟；期间工具调用 ${sinceTools} 次；${ledgerNote}。

由于长时间、高密度执行而没有真正的完成要求或产出真正的答案，说明方向或实施细节有误的概率较大，当前批次收尾后分析这种可能性。若认同并确认到了需要反思盘点的时机，运行 reflection-protocol skill。

本段由当前安全分析系统的分析监控模块自动附加，不属于命令输出。
${REFLECT_NUDGE_END_MARKER}
`;
}

/**
 * 反思纸条（忙时通道）：反思到期且会话运行中时，把提醒附加到 bash 结果末尾。
 * 不创建新消息（不夺取响应计划主导权、不降级未完成的承诺），失败模式=被忽略（无害）。
 * 必须在事件库/记忆库存储之后调用（调用点顺序约束），避免纸条文本进入存储。
 */
export function maybeAttachReflectNudge(
  input: { tool: string; sessionID: string },
  output: { output?: string },
  session: SessionData,
): void {
  const sessionID = input.sessionID;
  if (!isReflectionEligible(session)) {
    return;
  }
  // 仅 bash（v1 保守选择：自由文本输出、覆盖绝大多数决策边界，不碰结构化工具输出）
  if (input.tool !== "bash") {
    return;
  }
  if (!isReflectEnabled()) {
    debugLog(`反思纸条: 开关禁用，跳过 sessionID=${sessionID}`, sessionID);
    return;
  }
  // 到期判定（同步 check-and-set：判定与占位之间无 await，并行工具不会双发）
  if (!isReflectionDue(session)) {
    return; // 未到期：安静跳过（每个 bash 都检查，记日志会刷屏）
  }
  // 输出非空 且 不含纸条标记（防复读型命令二次标记）
  const text = output.output || "";
  if (!text.trim() || text.includes(REFLECT_NUDGE_MARKER)) {
    debugLog(
      `反思纸条: 输出为空或已含标记，跳过 sessionID=${sessionID}`,
      sessionID,
    );
    return;
  }

  const { sinceMin, sinceTools } = markReflectionFired(session);
  output.output =
    text + "\n\n" + renderReflectNudge(session, sinceMin, sinceTools);
  debugLog(
    `[INFO] 反思纸条 #${session.reflectionCount} 已附加 (距上次 ${sinceMin}min, 期间 ${sinceTools} 次工具调用) sessionID=${sessionID}`,
    sessionID,
  );
}

// ─── 空闲通道：反思唤醒 ───────────────────────────────────────────

/** 渲染反思唤醒消息文案（纯指针式：只含动态数字与 skill 指向，规则细节以 reflection-protocol skill 为唯一权威；调用方须已 markReflectionFired） */
export function renderReflectWake(
  session: SessionData,
  sinceMin: number,
  sinceTools: number,
): string {
  const n = session.reflectionCount; // 调用方已递增
  return `## 反思唤醒
运行数据：反思触发 ${n} 次；已运行 ${session.elapsedMinutes} 分钟；工具调用 ${session.toolCallCount} 次；距上次反思 ${sinceMin} 分钟，期间 ${sinceTools} 次工具调用。

**要求**：
- 执行专业的反思skill，进行反思：reflection-protocol skill。
- 完成反思盘点后按结果继续执行原任务。`;
}

/** 发送反思唤醒消息（空闲通道：会话 idle 且距上次反思满间隔时触发，非定时器）。仅从 maybeResumeAnalysis 调用（promptAsync + synthetic）。
 *  唤醒消息自带续接指令（"完成盘点后按结果继续执行原任务"），故本次不再另发 resume。 */
export async function sendReflection(session: SessionData): Promise<void> {
  const sessionID = session.sessionID;
  if (!ctx.client) {
    debugLog(
      `sendReflection: ctx.client 不可用，跳过 sessionID=${sessionID}`,
      sessionID,
    );
    return;
  }

  const { sinceMin, sinceTools } = markReflectionFired(session);
  // 种下完成标记：任务完成后模型原样输出它 → 下一次 idle 顶部的完成检测
  // 拦停一切注入（唤醒与 resume 共用该自停机制，避免对已完成会话反复唤醒）。
  const marker = generateCompletionMarker();
  session.resumeMarker = marker;
  const prompt =
    renderReflectWake(session, sinceMin, sinceTools) +
    `\n若任务已全部完成：输出最终结论，然后在最后一行原样输出这个标记（原样复制，不要修改）：${marker}；未完成时绝对不要输出该标记。`;
  debugLog(
    `session.idle: 反思唤醒 #${session.reflectionCount} (距上次 ${sinceMin}min, 期间 ${sinceTools} 次工具调用, marker=${marker}) sessionID=${sessionID}`,
    sessionID,
  );

  await ctx.client.session.promptAsync({
    path: { id: sessionID },
    body: {
      agent: session.agentName,
      parts: [{ type: "text" as const, text: prompt, synthetic: true }],
    },
  });

  debugLog(`session.idle: 反思唤醒已发送 sessionID=${sessionID}`, sessionID);
}
