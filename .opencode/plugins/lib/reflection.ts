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
  REFLECT_NUDGE_DEFAULT_INTERVAL_MIN,
} from "./constants";

// ─── 反思系统共用逻辑（两通道单一来源）────────────────────────────
//
// 反思有两个投递通道，共用本模块的开关、到期判定、守卫与状态更新：
//   忙时通道 = 反思纸条（bash 结果末尾附加，不创建消息、不夺取响应计划主导权，
//             失败模式=被忽略）—— plugins/security-analysis.ts 的 tool.execute.after 调用
//   空闲通道 = 反思心跳（promptAsync 合成用户消息，自带续接指令）
//             —— plugins/lib/persistence.ts 的 maybeResumeAnalysis 调用（优先于 resume）
// 判定规范的权威全文在 skills/reflection-protocol/SKILL.md；本模块只负责时机与投递。

/** 反思纸条标记（附加到 bash 输出末尾的定界行；复读型命令命中即跳过再附） */
export const REFLECT_NUDGE_MARKER = "——— [系统·反思提醒] ———";

/**
 * 生成动态完成标记（resume 与反思心跳共用）。
 * 动态化的目的：避免 LLM 学会"拒绝输出 >>>COMPLETE<<<"后污染所有后续注入轮次；
 * 完成检测用精确匹配（本次植入的具体值存入 session.resumeMarker，
 * 下一轮 idle 检查 last assistant 文本是否原样包含它）。
 * 心跳种下标记的意义：任务完成后的空闲会话不会再被心跳/resume 反复唤醒。
 */
export function generateCompletionMarker(): string {
  const hash = Math.floor(Math.random() * 0x10000)
    .toString(16)
    .padStart(4, "0");
  return `>>>COMPLETE-${hash}<<<`;
}

/** 反思总开关（未设置=启用；"0"/"false"=禁用，与既有开关同语义；两通道共用） */
export function isReflectEnabled(): boolean {
  const raw = getCachedConfig()[ENV_KEY_REFLECT_NUDGE]?.toLowerCase();
  return !(raw === "0" || raw === "false");
}

/** 反思到期间隔（毫秒）：控制台配置 REFLECT_NUDGE_INTERVAL_MIN 覆盖默认值（验证时可调小） */
export function getReflectIntervalMs(): number {
  const min = Number(getCachedConfig()["REFLECT_NUDGE_INTERVAL_MIN"]);
  return Number.isFinite(min) && min > 0
    ? min * 60_000
    : REFLECT_NUDGE_DEFAULT_INTERVAL_MIN * 60_000;
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
若当前方向产出为空：先跑它的最廉价证伪探针（判 C），不要追加执行变体；刚返回的结果先写入台账（这算产出）。
完整流程：reflection-protocol skill。
（本段由系统附加，不属于命令输出；完成当前步骤后处理即可。）`;
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
    debugLog(`反思纸条: 输出为空或已含标记，跳过 sessionID=${sessionID}`, sessionID);
    return;
  }

  const { sinceMin, sinceTools } = markReflectionFired(session);
  output.output = text + "\n\n" + renderReflectNudge(session, sinceMin, sinceTools);
  debugLog(
    `[INFO] 反思纸条 #${session.reflectionCount} 已附加 (距上次 ${sinceMin}min, 期间 ${sinceTools} 次工具调用) sessionID=${sessionID}`,
    sessionID,
  );
}

// ─── 空闲通道：反思心跳 ───────────────────────────────────────────

/** 渲染反思心跳文案（每第 5 次反思含死路复核条目；调用方须已 markReflectionFired） */
export function renderReflectionHeartbeat(
  session: SessionData,
  sinceMin: number,
  sinceTools: number,
): string {
  const n = session.reflectionCount; // 调用方已递增
  const deadEndLine =
    n % 5 === 0
      ? `3. （本次为第 ${n} 次反思，执行死路复核）判 B：挑投入最大的"死"方向，核对其探针三要素（携带物/宿主形态/提交路径）；不完整 → 换观测手段重测一次。`
      : `3. （死路复核每第 5 次反思执行，本次第 ${n} 次跳过。）`;
  return `## 反思心跳 #${n}（对台账「方向表」每个活跃方向判定 A/B/C/D）
（已运行 ${session.elapsedMinutes} 分钟；工具调用 ${session.toolCallCount} 次；距上次反思 ${sinceMin} 分钟，期间 ${sinceTools} 次工具调用）

按顺序执行，前一条未清空不做后一条：
0. ① 若有用户问了但尚未回答的问题 → 先完整回答它；
   ② 若有已返回但尚未写入台账的实验结果 → 先写入台账（这算产出；若因此产出非空 → 判 A，本次盘点结束，沿结果继续分析）。
1. 更新「方向表」每行：产出（新增或推翻的结论编号，无则写"空"）、投入（批次·时长）。
2. 产出=空 且 投入≥8批次或≥2小时 → 判 C：先跑该方向"最廉价证伪探针"
   （测前提/归属，不是加变体；探针写全三要素：携带物/宿主形态/提交路径；先写预期再跑）。
   - 证伪命中 → 方向标死，换表中下一个未试方向；表空 → 派 fresh-eyes 重灌方向池（其候选检验项逐条执行或降权）。
   - 没证伪、且想不出下一个新变体 → 判 D：换词检索/无知证书/转求助，停止自行穷举。
${deadEndLine}
4. 归属收口：「未测条件」表禁止"无判定渠道/？"状态——每条挂（限次/限时实验）或（降权+理由）。
完成盘点后按结果继续执行原任务。`;
}

/** 发送反思心跳消息（空闲通道）。仅从 maybeResumeAnalysis 调用（promptAsync + synthetic）。
 *  心跳自带续接指令（"完成盘点后按结果继续执行原任务"），故本次不再另发 resume。 */
export async function sendReflection(session: SessionData): Promise<void> {
  const sessionID = session.sessionID;
  if (!ctx.client) {
    debugLog(`sendReflection: ctx.client 不可用，跳过 sessionID=${sessionID}`, sessionID);
    return;
  }

  const { sinceMin, sinceTools } = markReflectionFired(session);
  // 种下完成标记：任务完成后模型原样输出它 → 下一次 idle 顶部的完成检测
  // 拦停一切注入（心跳与 resume 共用该自停机制，避免对已完成会话反复唤醒）。
  const marker = generateCompletionMarker();
  session.resumeMarker = marker;
  const prompt =
    renderReflectionHeartbeat(session, sinceMin, sinceTools) +
    `\n若任务已全部完成：输出最终结论，然后在最后一行原样输出这个标记（原样复制，不要修改）：${marker}；未完成时绝对不要输出该标记。`;
  debugLog(
    `session.idle: 反思心跳 #${session.reflectionCount} (距上次 ${sinceMin}min, 期间 ${sinceTools} 次工具调用, marker=${marker}) sessionID=${sessionID}`,
    sessionID,
  );

  await ctx.client.session.promptAsync({
    path: { id: sessionID },
    body: {
      agent: session.agentName,
      parts: [{ type: "text" as const, text: prompt, synthetic: true }],
    },
  });

  debugLog(`session.idle: 反思心跳已发送 sessionID=${sessionID}`, sessionID);
}
