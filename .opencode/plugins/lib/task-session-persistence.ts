import { join } from "path";
import {
  existsSync,
  readFileSync,
  unlinkSync,
  mkdirSync,
  writeFileSync,
} from "fs";
import { ENV_CACHE_FILE, TASK_SESSIONS_DIR, WORKSPACE_DIR } from "./constants";
import { debugLog } from "./logging";
import TaskSessionPersistenceUtils, {
  TaskRawData,
  TaskSessionPersistenceData,
} from "./task-session-persistence-utils";

export default class TaskSessionPersistence {
  /**
   * 创建任务目录并注册 sessionID 映射（替代已删除的 create_task_dir.py）。
   * 幂等：同一 sessionID 重复调用返回已有目录（映射存在且目录有效时）。
   * 新建时：时间戳+随机hex 目录名 + 注册 .task_sessions/{sessionID}.json 映射。
   * 返回 task_dir 绝对路径。
   */
  static createTaskSession(
    sessionID: string,
    agentName: string,
    flowId: string,
    baseDir?: string | null,
  ): TaskRawData {
    // 幂等检查：已有映射且目录存在 → 返回已有
    const existingTaskRawDataResult =
      TaskSessionPersistenceUtils.loadTaskRawData(sessionID);
    const existingTaskRawData = existingTaskRawDataResult.data;
    if (
      existingTaskRawData?.taskDir &&
      existsSync(existingTaskRawData?.taskDir)
    ) {
      debugLog(
        `createTaskDir: 幂等命中 sessionID=${sessionID} taskDir=${existingTaskRawData?.taskDir}`,
        sessionID,
      );
      return existingTaskRawData;
    }

    const realBaseDir = baseDir || WORKSPACE_DIR;

    // 创建目录
    mkdirSync(realBaseDir, { recursive: true });
    const taskDirName = TaskSessionPersistenceUtils.genTaskDirName(agentName);
    const taskDir: string = join(realBaseDir, taskDirName);
    mkdirSync(taskDir, { recursive: true });

    // 注册映射（sessionID 非空时）
    mkdirSync(TASK_SESSIONS_DIR, { recursive: true });
    const data: TaskSessionPersistenceData = {
      task_dir: taskDir,
      flow_id: flowId,
    };
    writeFileSync(
      join(TASK_SESSIONS_DIR, `${sessionID}.json`),
      JSON.stringify(data),
    );
    // 清缓存让下次 getTaskDirRaw 读到新映射（防止旧缓存残留）
    TaskSessionPersistenceUtils.clearCache(sessionID);

    debugLog(
      `createTaskDir: 新建 sessionID=${sessionID} taskDir=${taskDir}`,
      sessionID,
    );
    const taskRawData: TaskRawData = { taskDir, flowId };
    return taskRawData;
  }

  /** 删除 task session 映射文件 + 清除缓存 */
  static removeTaskSession(sessionID: string): void {
    TaskSessionPersistenceUtils.clearCache(sessionID);
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

  /** 读取 环境缓存 文件，失败返回 null */
  static readEnvCache<T>(sessionID?: string): T | null {
    const filePath = ENV_CACHE_FILE;
    try {
      if (existsSync(filePath)) {
        return JSON.parse(readFileSync(filePath, "utf-8")) as T;
      }
    } catch (e) {
      debugLog(`readJsonSafe failed: ${filePath} error=${e}`, sessionID);
    }
    return null;
  }
}
