import { join } from "path";
import { existsSync, readFileSync, unlinkSync, mkdirSync, writeFileSync } from "fs";
import { TASK_SESSIONS_DIR, WORKSPACE_DIR } from "./constants";
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

/**
 * 创建任务目录并注册 sessionID 映射（替代已删除的 create_task_dir.py）。
 * 幂等：同一 sessionID 重复调用返回已有目录（映射存在且目录有效时）。
 * 新建时：时间戳+随机hex 目录名 + 注册 .task_sessions/{sessionID}.json 映射。
 * 返回 task_dir 绝对路径。
 */
export function createTaskDir(sessionID: string): string {
  // 幂等检查：已有映射且目录存在 → 返回已有
  const existing = getTaskDirRaw(sessionID);
  if (existing.path && existsSync(existing.path)) {
    debugLog(`createTaskDir: 幂等命中 sessionID=${sessionID} taskDir=${existing.path}`, sessionID);
    return existing.path;
  }

  // 创建目录
  mkdirSync(WORKSPACE_DIR, { recursive: true });
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  const ts = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}` +
    `_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  const rand = Math.floor(Math.random() * 0xffff).toString(16).padStart(4, "0");
  const taskDir = join(WORKSPACE_DIR, `${ts}_${rand}`);
  mkdirSync(taskDir, { recursive: true });

  // 注册映射（sessionID 非空时）
  if (sessionID) {
    mkdirSync(TASK_SESSIONS_DIR, { recursive: true });
    writeFileSync(
      join(TASK_SESSIONS_DIR, `${sessionID}.json`),
      JSON.stringify({ task_dir: taskDir }),
    );
    // 清缓存让下次 getTaskDirRaw 读到新映射（防止旧缓存残留）
    clearTaskDirCache(sessionID);
  } else {
    debugLog(`createTaskDir: sessionID 为空，未注册映射 taskDir=${taskDir}`);
  }

  debugLog(`createTaskDir: 新建 sessionID=${sessionID} taskDir=${taskDir}`, sessionID);
  return taskDir;
}
