import { join } from "path";
import { existsSync, readFileSync, unlinkSync } from "fs";
import { TASK_SESSIONS_DIR } from "./constants";
import { getTaskDirRaw, clearTaskDirCache } from "./utils";
import { debugLog } from "./logging";

/** 安全读取 JSON 文件，失败返回 null */
export function readJsonSafe<T>(filePath: string, sessionID?: string): T | null {
  try {
    if (existsSync(filePath)) {
      return JSON.parse(readFileSync(filePath, "utf-8")) as T;
    }
  } catch (e) {
    debugLog(`readJsonSafe failed: ${filePath} error=${e}`, sessionID);
  }
  return null;
}

/** 获取 task 目录（带缓存）。调 getTaskDirRaw + debugLog。 */
export function getTaskDir(sessionID: string): string | null {
  const result = getTaskDirRaw(sessionID);
  if (!result.path && result.error) {
    debugLog(`getTaskDir: ${result.error}`, sessionID);
  }
  return result.path;
}

/** 删除 task session 映射文件 + 清除缓存 */
export function removeTaskSession(sessionID: string): void {
  clearTaskDirCache(sessionID);
  try {
    const filePath = join(TASK_SESSIONS_DIR, `${sessionID}.json`);
    if (existsSync(filePath)) {
      debugLog(`removeTaskSession: deleting ${filePath}`, sessionID);
      unlinkSync(filePath);
    }
  } catch (e) {
    debugLog(
      `removeTaskSession failed: sessionID=${sessionID} error=${e}`,
      sessionID,
    );
  }
}
