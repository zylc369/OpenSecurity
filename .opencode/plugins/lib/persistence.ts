import { join } from "path";
import { readFileSync, writeFileSync } from "fs";
import {
  MAX_DURATION_DEFAULT,
  MAX_RESUMES,
  PERSISTENCE_FILE,
  ABORTED_ERROR_NAME,
  COMPLETION_MARKER,
  RESUME_PROMPTS,
  AGENT_SECURITY_ANALYSIS_EVOLVE,
} from "./constants";
import { ctx } from "./context";
import { debugLog } from "./logging";
import { getTaskDir } from "./task-session";

// 记录上一次使用的恢复提示词索引，保证本次与上次不重复，缓解 LLM 对同一提示词"皮掉"的问题。
let lastResumePromptIndex = -1;

function getResumePrompt(): string {
  if (RESUME_PROMPTS.length <= 1) return RESUME_PROMPTS[0];
  let idx = lastResumePromptIndex;
  while (idx === lastResumePromptIndex) {
    idx = Math.floor(Math.random() * RESUME_PROMPTS.length);
  }
  lastResumePromptIndex = idx;
  return RESUME_PROMPTS[idx];
}

interface PersistenceData {
  max_duration_hours: number;
  resume_count: number;
  last_resume_at: string | null;
}

function readPersistenceData(sessionID: string): PersistenceData | null {
  const taskDir = getTaskDir(sessionID);
  if (!taskDir) return null;
  const filePath = join(taskDir, PERSISTENCE_FILE);
  try {
    const content = readFileSync(filePath, "utf-8").trim();
    const data = JSON.parse(content) as PersistenceData;
    if (
      typeof data.max_duration_hours === "number" &&
      data.max_duration_hours > 0 &&
      data.max_duration_hours <= 24
    ) {
      return {
        max_duration_hours: data.max_duration_hours,
        resume_count: typeof data.resume_count === "number" ? data.resume_count : 0,
        last_resume_at: data.last_resume_at ?? null,
      };
    }
    debugLog(
      `readPersistenceData: invalid max_duration_hours in ${filePath}, using default`,
      sessionID,
    );
  } catch {
    // 文件不存在或 JSON 解析失败，使用默认值
  }
  return null;
}

function getMaxDuration(sessionID: string): number {
  const data = readPersistenceData(sessionID);
  if (data) {
    return Math.floor(data.max_duration_hours * 3600 * 1000);
  }
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

function recordResumeAttempt(sessionID: string): void {
  const taskDir = getTaskDir(sessionID);
  if (!taskDir) {
    debugLog(`recordResumeAttempt: no taskDir for sessionID=${sessionID}`, sessionID);
    return;
  }
  const filePath = join(taskDir, PERSISTENCE_FILE);
  const existing = readPersistenceData(sessionID);
  const data: PersistenceData = {
    max_duration_hours: existing?.max_duration_hours ?? MAX_DURATION_DEFAULT / (3600 * 1000),
    resume_count: (existing?.resume_count ?? 0) + 1,
    last_resume_at: new Date().toISOString(),
  };
  try {
    writeFileSync(filePath, JSON.stringify(data, null, 2));
    debugLog(`recordResumeAttempt: written resume_count=${data.resume_count} to ${filePath}`, sessionID);
  } catch (e) {
    debugLog(`recordResumeAttempt: failed to write ${filePath} error=${e}`, sessionID);
  }
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
    const maxDuration = getMaxDuration(sessionID);
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
    if (lastText && lastText.includes(COMPLETION_MARKER)) {
      debugLog(`session.idle: 跳过恢复 — 检测到完成标记 ${COMPLETION_MARKER}, sessionID=${sessionID}`, sessionID);
      return;
    }

    const persistenceData = readPersistenceData(sessionID);
    const resumeCount = persistenceData?.resume_count ?? 0;
    if (resumeCount >= MAX_RESUMES) {
      debugLog(`session.idle: 跳过恢复 — 已达最大恢复次数 ${MAX_RESUMES} sessionID=${sessionID}`, sessionID);
      return;
    }

    debugLog(`session.idle: 恢复分析 sessionID=${sessionID} agent=${session.agentName} elapsed=${Math.floor(elapsed / 60000)}m max=${Math.floor(maxDuration / 60000)}m resume_count=${resumeCount}`, sessionID);
    await ctx.client.session.promptAsync({
      path: { id: sessionID },
      body: {
        agent: session.agentName,
        parts: [{ type: "text" as const, text: getResumePrompt(), synthetic: true }],
      },
    });
    recordResumeAttempt(sessionID);
    debugLog(`session.idle: 恢复消息已发送 sessionID=${sessionID}`, sessionID);
  } catch (e) {
    debugLog(`session.idle: 恢复异常 sessionID=${sessionID} error=${e}`, sessionID);
  }
}
