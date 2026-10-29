import { join, dirname } from "path";
import {
  mkdirSync,
  writeFileSync,
  existsSync,
  statSync,
  readFileSync,
} from "fs";
import {
  DEFAULT_LOG,
  LOGS_DIR,
  SECURITY_AGENTS,
  MAX_LOG_SIZE,
  KEEP_SIZE,
} from "./constants";
import { getAgentName } from "./utils";
import TaskSessionPersistenceUtils from "./task-session-persistence-utils";

function getLogFilePath(agentName: string | undefined): string {
  if (agentName && SECURITY_AGENTS.includes(agentName)) {
    return join(LOGS_DIR, `${agentName}.log`);
  }
  return DEFAULT_LOG;
}

function trimLogFile(logFile: string): void {
  try {
    if (existsSync(logFile) && statSync(logFile).size > MAX_LOG_SIZE) {
      const content = readFileSync(logFile, "utf-8");
      const keep = content.slice(-KEEP_SIZE);
      const firstNewline = keep.indexOf("\n");
      writeFileSync(
        logFile,
        firstNewline >= 0 ? keep.slice(firstNewline + 1) : keep,
      );
    }
  } catch {}
}

function writeLog(logFile: string, msg: string): void {
  try {
    mkdirSync(dirname(logFile), { recursive: true });
    trimLogFile(logFile);
    const now = new Date();
    const ts =
      now.toLocaleString("zh-CN", { hour12: false }) +
      `.${String(now.getMilliseconds()).padStart(3, "0")}`;
    writeFileSync(logFile, `[${ts}] ${msg}\n`, { flag: "a" });
  } catch {}
}

/**
 * 统一日志函数：优先写到任务目录的 logs/plugin.log，没有任务目录则按 agent 路由。
 * 调 getTaskDirRaw（纯函数，不回调 debugLog），彻底消除循环依赖。
 *
 * 契约: 日志层在任何输入/状态下不抛——调用方遍布各 hook（event/chat.params/
 * 定时器回调），抛出会中断事件流或产生 unhandled rejection。主体包 try/catch，
 * 失败回退 DEFAULT_LOG（writeLog 自身全 catch，静默放弃）。
 */
export function debugLog(msg: string, sessionID?: string | null): void {
  try {
    if (sessionID) {
      const result = TaskSessionPersistenceUtils.getTaskDir(sessionID);
      const path = result.data;
      if (path) {
        writeLog(join(path, "logs", "plugin.log"), msg);
        return;
      }
      // path 为 null（文件不存在/损坏/无 task_dir）→ 回退到 agent 日志文件
      const agentName = getAgentName(sessionID);
      writeLog(getLogFilePath(agentName), msg);
    } else {
      writeLog(DEFAULT_LOG, msg);
    }
  } catch {
    // 路由层异常（如 sessionManager 缺 get 等异常 ctx）→ 回退默认日志文件
    try {
      writeLog(DEFAULT_LOG, msg);
    } catch {
      // 日志不可写时静默放弃——不干扰主流程
    }
  }
}
