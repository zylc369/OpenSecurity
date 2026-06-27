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
import { getTaskDirRaw, getAgentName } from "./utils";

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
 * 注意：getTaskDirRaw 返回的 error 在此处故意忽略——debugLog 是日志路由层，
 * 只关心 path 用于决定写入位置。error 的诊断由业务层 getTaskDir（task-session.ts）负责记录。
 */
export function debugLog(msg: string, sessionID?: string): void {
  if (sessionID) {
    const result = getTaskDirRaw(sessionID);
    if (result.path) {
      writeLog(join(result.path, "logs", "plugin.log"), msg);
      return;
    }
    // path 为 null（文件不存在/损坏/无 task_dir）→ 回退到 agent 日志文件
    const agentName = getAgentName(sessionID);
    writeLog(getLogFilePath(agentName), msg);
  } else {
    writeLog(DEFAULT_LOG, msg);
  }
}
