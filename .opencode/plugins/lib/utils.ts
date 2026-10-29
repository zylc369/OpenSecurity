import { ctx } from "./context";

interface TaskSessionMapping {
  task_dir: string;
  flow_id: string;
}

export interface TaskRawData {
  taskDir: string;
  flowId: string;
}

/**
 * 获取 session 的 agent 名（通过全局上下文读取，不回调 debugLog）。
 */
export function getAgentName(sessionID?: string): string | undefined {
  if (!sessionID) return undefined;
  return ctx.sessionManager?.get(sessionID)?.agentName;
}
