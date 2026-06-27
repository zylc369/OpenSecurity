import { join } from "path";
import { existsSync, readFileSync } from "fs";
import { TASK_SESSIONS_DIR } from "./constants";
import { ctx } from "./context";

interface TaskSessionMapping {
  task_dir: string;
}

// getTaskDirRaw 内存缓存（只缓存有值的结果，null 不缓存——映射文件可能后续被创建）
const taskDirCache = new Map<string, string>();

/**
 * 纯文件读取：读取 task session 映射文件，不调任何日志函数。
 * 专供 debugLog 使用——避免 debugLog → getTaskDir → debugLog 循环。
 */
export function getTaskDirRaw(
  sessionID: string,
): { path: string | null; error?: string } {
  const cached = taskDirCache.get(sessionID);
  if (cached) return { path: cached };

  const filePath = join(TASK_SESSIONS_DIR, `${sessionID}.json`);
  try {
    if (existsSync(filePath)) {
      const data = JSON.parse(readFileSync(filePath, "utf-8")) as TaskSessionMapping;
      const result = data?.task_dir;
      if (result) {
        taskDirCache.set(sessionID, result);
        return { path: result };
      }
      return { path: null, error: `映射文件缺少 task_dir 字段 sessionID=${sessionID} filePath=${filePath}` };
    }
    return { path: null, error: `映射文件不存在 sessionID=${sessionID} filePath=${filePath}` };
  } catch (e) {
    return { path: null, error: `读取异常 sessionID=${sessionID} error=${e}` };
  }
}

/** 清除 taskDirCache 中的缓存项（removeTaskSession 时调用） */
export function clearTaskDirCache(sessionID: string): void {
  taskDirCache.delete(sessionID);
}

/**
 * 获取 session 的 agent 名（通过全局上下文读取，不回调 debugLog）。
 */
export function getAgentName(sessionID?: string): string | undefined {
  if (!sessionID) return undefined;
  return ctx.sessionManager?.get(sessionID)?.agentName;
}
