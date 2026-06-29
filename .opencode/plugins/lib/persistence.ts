import {
  MAX_DURATION_DEFAULT,
  MAX_RESUMES,
  RESUME_COOLDOWN_STEP_MS,
  RESUME_COOLDOWN_MAX_MS,
  ABORTED_ERROR_NAME,
  AGENT_SECURITY_ANALYSIS_EVOLVE,
} from "./constants";
import { ctx } from "./context";
import { debugLog } from "./logging";
import { getTaskDir } from "./task-session";

// ─── 完成标记（动态生成 + 精确匹配）──────────────────────────────
//
// 完成标记采用 `>>>COMPLETE-XXXX<<<` 格式，其中 XXXX 是 4 位十六进制随机 hash。
// 动态化的目的：避免 LLM 学会"拒绝输出 >>>COMPLETE<<<"后污染所有后续恢复轮次
// （死值场景下，一旦 LLM 在某次回复里写下 "I will NOT output >>>COMPLETE<<<"，
// 后续无论怎么提示它都会拒绝输出，恢复链彻底卡死）。
//
// 完成检测用精确匹配（而非正则匹配格式）：本次植入的具体 marker 被存入
// session.resumeMarker，下一轮 idle 检测 lastText 是否原样包含它。
// 这样能阻止 LLM 通过"模仿格式"（自己造一个 >>>COMPLETE-yyyy<<<）绕过完成检测，
// 强制它必须原样复制本次植入的具体值。

// prompt 模板里的占位符，会被 getResumePrompt() 替换成动态生成的 marker。
// 用双下划线包裹避免与正常文本混淆。
const COMPLETION_MARKER_PLACEHOLDER = "__COMPLETION_MARKER__";

// 生成动态完成标记。4 位 hex = 65536 种组合，LLM 瞎猜中的概率可忽略。
function generateCompletionMarker(): string {
  const hash = Math.floor(Math.random() * 0x10000)
    .toString(16)
    .padStart(4, "0");
  return `>>>COMPLETE-${hash}<<<`;
}

// 多条语义等价的恢复提示词模板：每次随机选用且不与上次相同，
// 避免反复发送同一文本导致 LLM 习惯性"皮掉"、不再继续分析。
// 模板内的 __COMPLETION_MARKER__ 占位符会在 getResumePrompt() 中
// 被替换为本次动态生成的 marker（同一条 prompt 内所有占位符共用同一个 marker）。
const RESUME_PROMPTS: string[] = [
  `你之前的分析是否已经完成了？**你必须要如实回答和执行**：\n` +
  `- 如果已经完成：请直接输出最终结论，然后在最后一行精确输出这个标记（原样复制，不要修改）：${COMPLETION_MARKER_PLACEHOLDER}\n` +
  `- 如果尚未完成：不论任何原因只要未完成，你都必须自主继续分析，不要停下来向我提问，因为我没有任何想法，但是我需要你给我解决问题。你复盘一下之前的分析内容、结果，然后继续分析，直到完成为止。未完成的情况下绝对不允许输出 ${COMPLETION_MARKER_PLACEHOLDER} 标记。`,

  `请确认此前的分析工作是否已经全部完成。**必须如实回答并严格执行**：\n` +
  `- 若已完成：直接给出最终结论，并在末尾单独一行原样输出该标记（切勿改动）：${COMPLETION_MARKER_PLACEHOLDER}\n` +
  `- 若未完成：无论出于何种原因，都必须自行接着分析下去，不得向我提问，因为我没有任何想法，但是我需要你给我解决问题，你解决问题你才有意义。你先回顾之前的分析内容与结论，再继续推进直至全部完成。未完成时严禁输出 ${COMPLETION_MARKER_PLACEHOLDER}。`,

  `你先前的分析完成了吗？**务必如实回答并照做**：\n` +
  `- 已完成的话：请直接产出最终结论，随后在最后一行一字不差地输出以下标记（不得修改）：${COMPLETION_MARKER_PLACEHOLDER}\n` +
  `- 尚未完成的话：不管什么原因，你都要自主把分析继续下去，不要停下来问我，因为我没有任何想法，但是我需要你给我解决问题，你想想接下来怎么办。你梳理一下已有的分析内容与结果，接着往下做，直到真正完成。只要还没完成，就绝对不可以输出 ${COMPLETION_MARKER_PLACEHOLDER}。`,

  `请判断此前的分析是否已结束。**你必须诚实回答并按以下执行**：\n` +
  `- 已结束：请直接陈述最终结论，并在最后一行精确地原样输出这个标记（不要做任何修改）：${COMPLETION_MARKER_PLACEHOLDER}\n` +
  `- 未结束：任何情况下只要还没做完，都得自主继续分析，不允许停下来征求我的意见，因为我没有任何想法，但是我需要你给我解决问题，你多想想。请你复盘此前分析的内容和结果，然后继续，直到彻底完成。尚未完成时绝不允许输出 ${COMPLETION_MARKER_PLACEHOLDER}。`,

  `分析任务完成了吗？**请如实回答并严格执行如下要求**：\n` +
  `- 倘若已完成：直接输出最终结论，最后单独一行原样复制此标记（一字不改）：${COMPLETION_MARKER_PLACEHOLDER}\n` +
  `- 倘若未完成：不论任何缘由，你都必须独立继续分析，切勿来询问我，因为我没有任何想法，但是我需要你给我解决问题，不要罢工。你回顾前面的分析内容与结果，继续推进直到完成。在未完成时，绝不可输出 ${COMPLETION_MARKER_PLACEHOLDER}。`,
];

// 记录上一次使用的恢复提示词索引，保证本次与上次不重复，缓解 LLM 对同一提示词"皮掉"的问题。
let lastResumePromptIndex = -1;

// getResumePrompt 返回值：prompt 是要发给 LLM 的恢复提示词，marker 是本次植入的具体完成标记。
// marker 必须由调用方存入 session data，下一轮 idle 时用它精确匹配 lastText 判断是否完成。
interface ResumePromptResult {
  prompt: string;
  marker: string;
}

function getResumePrompt(): ResumePromptResult {
  let idx: number;
  if (RESUME_PROMPTS.length <= 1) {
    idx = 0;
  } else {
    idx = lastResumePromptIndex;
    while (idx === lastResumePromptIndex) {
      idx = Math.floor(Math.random() * RESUME_PROMPTS.length);
    }
  }
  lastResumePromptIndex = idx;
  // 同一条 prompt 内多个占位符必须替换为同一个 marker，否则 LLM 会困惑
  const marker = generateCompletionMarker();
  const prompt = RESUME_PROMPTS[idx].replaceAll(COMPLETION_MARKER_PLACEHOLDER, marker);
  return { prompt, marker };
}

function getMaxDuration(): number {
  return MAX_DURATION_DEFAULT;
}

async function checkLastMessageAborted(sessionID: string): Promise<boolean> {
  if (!ctx.client) return false;
  try {
    const response = await ctx.client.session.messages({
      path: { id: sessionID },
    });
    if (response.error || !response.data) return false;
    const messages = response.data;
    if (!Array.isArray(messages) || messages.length === 0) return false;
    const lastAssistant = [...messages]
      .reverse()
      .find((m: { info?: { role?: string } }) => m?.info?.role === "assistant");
    if (!lastAssistant) return false;
    const info = (lastAssistant as { info?: { error?: { name?: string } } }).info;
    return info?.error?.name === ABORTED_ERROR_NAME;
  } catch (e) {
    debugLog(`checkLastMessageAborted: 查询异常 sessionID=${sessionID} error=${e}`, sessionID);
    return false;
  }
}

async function getLastAssistantText(sessionID: string): Promise<string | null> {
  if (!ctx.client) return null;
  try {
    const response = await ctx.client.session.messages({
      path: { id: sessionID },
    });
    if (response.error || !response.data) return null;
    const messages = response.data;
    if (!Array.isArray(messages) || messages.length === 0) return null;
    const lastAssistant = [...messages]
      .reverse()
      .find((m: { info?: { role?: string } }) => m?.info?.role === "assistant");
    if (!lastAssistant) return null;
    const parts = (
      lastAssistant as { parts?: Array<{ type?: string; text?: string }> }
    ).parts;
    if (!parts || !Array.isArray(parts)) return null;
    return parts
      .filter((p) => p.type === "text" && p.text)
      .map((p) => p.text!)
      .join("\n");
  } catch (e) {
    debugLog(`getLastAssistantText: 查询异常 sessionID=${sessionID} error=${e}`, sessionID);
    return null;
  }
}

/** 发送 resume prompt 并记录状态。从 maybeResumeAnalysis 和冷却 setTimeout 回调两处调用。
 *  内部通过 get 获取最新 session——setTimeout 回调可能延迟很久，闭包捕获的 session 可能已失效。 */
async function sendResume(sessionID: string): Promise<void> {
  if (!ctx.client) {
    debugLog(`sendResume: ctx.client 不可用，跳过 sessionID=${sessionID}`, sessionID);
    return;
  }
  const session = ctx.sessionManager.get(sessionID);
  if (!session || !session.isSecurityAgent()) {
    debugLog(`sendResume: session 不存在或非 Security Agent，跳过 sessionID=${sessionID}`, sessionID);
    return;
  }
  debugLog(`session.idle: 恢复分析 sessionID=${sessionID} agent=${session.agentName} resume_count=${session.resumeCount}`, sessionID);
  const { prompt, marker } = getResumePrompt();
  await ctx.client.session.promptAsync({
    path: { id: sessionID },
    body: {
      agent: session.agentName,
      parts: [{ type: "text" as const, text: prompt, synthetic: true }],
    },
  });
  // 发送成功后才记录 marker——下一轮 idle 用它做精确完成检测。
  session.resumeMarker = marker;
  session.resumeCount++;
  session.lastResumeAt = Date.now();
  debugLog(`session.idle: 恢复消息已发送 sessionID=${sessionID} marker=${marker}`, sessionID);
}

export async function maybeResumeAnalysis(sessionID: string): Promise<void> {
  try {
    const session = ctx.sessionManager.requireSecurityAgent("session.idle", sessionID);
    if (!session) {
      debugLog(`session.idle: 跳过恢复 — 非 Security Agent sessionID=${sessionID}`, sessionID);
      return;
    }

    if (session.agentName === AGENT_SECURITY_ANALYSIS_EVOLVE) {
      debugLog(`session.idle: 跳过恢复 — evolve agent 不做分析工作, sessionID=${sessionID}`, sessionID);
      return;
    }

    const taskDir = getTaskDir(sessionID);
    if (!taskDir) {
      debugLog(`session.idle: 跳过恢复 — 无 taskDir（非正式分析任务）, sessionID=${sessionID}`, sessionID);
      return;
    }

    const elapsed = Date.now() - session.lastUserMessageAt;
    const maxDuration = getMaxDuration();
    if (elapsed >= maxDuration) {
      debugLog(`session.idle: 跳过恢复 — 已超时 sessionID=${sessionID} elapsed=${Math.floor(elapsed / 60000)}m max=${Math.floor(maxDuration / 60000)}m`, sessionID);
      return;
    }

    if (!ctx.client) {
      debugLog(`session.idle: 跳过恢复 — ctx.client 未初始化`, sessionID);
      return;
    }

    const wasAborted = await checkLastMessageAborted(sessionID);
    if (wasAborted) {
      debugLog(`session.idle: 跳过恢复 — 用户手动中断, sessionID=${sessionID}`, sessionID);
      return;
    }

    const lastText = await getLastAssistantText(sessionID);
    // 精确匹配：只有 session.resumeMarker 存在时才检测，且必须原样包含本次植入的具体值。
    // 不存在则跳过检测（首次恢复场景：上一轮没植入过 marker）。
    if (session.resumeMarker && lastText && lastText.includes(session.resumeMarker)) {
      debugLog(`session.idle: 跳过恢复 — 检测到完成标记 ${session.resumeMarker}, sessionID=${sessionID}`, sessionID);
      return;
    }

    const resumeCount = session.resumeCount;
    if (resumeCount >= MAX_RESUMES) {
      debugLog(`session.idle: 跳过恢复 — 已达最大恢复次数 ${MAX_RESUMES} sessionID=${sessionID}`, sessionID);
      return;
    }

    // 冷却判断：基于 resumeCount 的线性退避（1s起，每次+1s，上限10s）。
    // 只影响"快速空转"——AI 认真分析时回复时间 > 冷却阈值，sinceLastResume > cooldown，不会触发延迟。
    const now = Date.now();
    const sinceLastResume = now - session.lastResumeAt;
    const cooldown = Math.min((session.resumeCount + 1) * RESUME_COOLDOWN_STEP_MS, RESUME_COOLDOWN_MAX_MS);
    if (sinceLastResume >= 0 && sinceLastResume < cooldown) {
      const wait = cooldown - sinceLastResume;
      debugLog(`session.idle: 冷却中，${Math.ceil(wait / 1000)}s 后恢复 sessionID=${sessionID}（backoff=${cooldown / 1000}s resume_count=${session.resumeCount}）`, sessionID);
      session.clearPendingResume();
      session.pendingResumeTimer = setTimeout(() => {
        session.pendingResumeTimer = null;
        sendResume(sessionID).catch((e) => {
          debugLog(`session.idle: 冷却恢复异常 sessionID=${sessionID} error=${e}`, sessionID);
        });
      }, wait);
      return;
    }

    await sendResume(sessionID);
  } catch (e) {
    debugLog(`session.idle: 恢复异常 sessionID=${sessionID} error=${e}`, sessionID);
  }
}
