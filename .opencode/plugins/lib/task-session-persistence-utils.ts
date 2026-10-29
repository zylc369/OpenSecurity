import { join } from "path";
import { existsSync, readFileSync } from "fs";
import { TASK_SESSIONS_DIR } from "./constants";
import { Result } from "./result";

export interface TaskSessionPersistenceData {
  task_dir: string;
  flow_id: string;
}

export interface TaskRawData {
  taskDir: string;
  flowId: string;
}

export default class TaskSessionPersistenceUtils {
  // getTaskDirRaw 内存缓存（只缓存有值的结果，null 不缓存——映射文件可能后续被创建）
  private static taskRawDataCache = new Map<string, TaskRawData>();

  /**
   * 纯文件读取：读取 task session 映射文件，不调任何日志函数。
   * 专供 debugLog 使用——避免 debugLog → getTaskDir → debugLog 循环。
   */
  static getTaskDir(sessionID: string): Result<string> {
    const taskRawDataResult =
      TaskSessionPersistenceUtils.loadTaskRawData(sessionID);
    if (!taskRawDataResult.success) {
      return Result.fail(
        taskRawDataResult.errorMessage || "加载任务数据失败，失败原因未知",
      );
    }
    const taskDir = taskRawDataResult.data?.taskDir;
    if (!taskDir) {
      return Result.fail("任务数据中任务目录未找到，原因未知");
    }
    return Result.ok(taskDir);
  }

  static getTaskFlowId(sessionID: string): Result<string> {
    const taskRawDataResult =
      TaskSessionPersistenceUtils.loadTaskRawData(sessionID);
    if (!taskRawDataResult.success) {
      return Result.fail(
        taskRawDataResult.errorMessage || "加载任务数据失败，失败原因未知",
      );
    }
    const flowId = taskRawDataResult.data?.flowId;
    if (!flowId) {
      return Result.fail("任务数据中flowId未找到，原因未知");
    }
    return Result.ok(flowId);
  }

  /** 清除缓存项（removeTaskSession 时调用） */
  static clearCache(sessionID: string): void {
    TaskSessionPersistenceUtils.taskRawDataCache.delete(sessionID);
  }

  static genTaskDirName(agentName: string): string {
    const now = new Date();
    const pad = (n: number) => String(n).padStart(2, "0");
    const ts =
      `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}` +
      `_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
    const rand = Math.floor(Math.random() * 0xffff)
      .toString(16)
      .padStart(4, "0");
    return `${ts}_${rand}_${agentName}`;
  }

  static genFlowId() {
    return `flow-${crypto.randomUUID().replaceAll("-", "")}`;
  }

  static loadTaskRawData(sessionID: string): Result<TaskRawData> {
    const cached = TaskSessionPersistenceUtils.taskRawDataCache.get(sessionID);
    if (cached) return Result.ok(cached);

    const filePath = join(TASK_SESSIONS_DIR, `${sessionID}.json`);
    try {
      if (!existsSync(filePath)) {
        return Result.fail(
          `映射文件不存在 sessionID=${sessionID} filePath=${filePath}`,
        );
      }
      const data = JSON.parse(
        readFileSync(filePath, "utf-8"),
      ) as TaskSessionPersistenceData;
      const taskDir = data?.task_dir;
      // 创建以 "mock-" 开头的 flow id 是为本次改动之前的任务创建flow id
      const flowId =
        data?.flow_id || `mock-flow-${TaskSessionPersistenceUtils.genFlowId()}`;
      if (taskDir) {
        const taskRawData: TaskRawData = { taskDir, flowId };
        TaskSessionPersistenceUtils.taskRawDataCache.set(
          sessionID,
          taskRawData,
        );
        return Result.ok(taskRawData);
      }
      return Result.fail(
        `映射文件缺少 task_dir 字段 sessionID=${sessionID} filePath=${filePath}`,
      );
    } catch (e) {
      return Result.fail(`读取异常 sessionID=${sessionID} error=${e}`);
    }
  }
}
