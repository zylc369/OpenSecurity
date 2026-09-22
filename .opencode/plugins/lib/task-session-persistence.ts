import { join } from "path";
import {
  existsSync,
  unlinkSync,
  mkdirSync,
  writeFileSync,
} from "fs";
import { TASK_SESSIONS_DIR, WORKSPACE_DIR, SECURITY_ANALYSIS_AGENTS } from "./constants";
import { cognition } from "./cognition";
import { debugLog } from "./logging";
import TaskSessionPersistenceUtils, {
  TaskRawData,
  TaskSessionPersistenceData,
} from "./task-session-persistence-utils";

/** 分析台账模板（根任务目录创建时写入）。结构、字段口径与定位语见模板本体。 */
export const LEDGER_TEMPLATE = `# 分析台账
> 结论与未测条件的唯一记录处；按待复核记录对待（非免检结论）。下结论前先更新本文件；压缩时本文件会被原样注入保留。

## ${cognition.sections.observations}
- （实验/命令 + 关键输出摘要）

## ${cognition.sections.conclusions}
| # | 结论 | ${cognition.fields.evidenceLevel} | ${cognition.fields.verifiedScope} | ${cognition.fields.untestedList} | 更新于（时间） |
|---|---|---|---|---|---|

## ${cognition.sections.untested}
| 维度 | 具体条件 | 为什么没测 | 预计成本 | 状态 |
|---|---|---|---|---|

## ${cognition.sections.changelog}
- （时间 + 改动了什么）
`;

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

    // 根任务目录：写入分析台账模板（认知干预系统：分析台账；仅五分析 agent；幂等，已存在不覆盖）
    if (!baseDir && SECURITY_ANALYSIS_AGENTS.includes(agentName)) {
      const ledgerPath = join(taskDir, cognition.ledgerFilename);
      if (!existsSync(ledgerPath)) {
        writeFileSync(ledgerPath, LEDGER_TEMPLATE);
        debugLog(`createTaskDir: 写入分析台账模板 ${ledgerPath}`, sessionID);
      }
    }

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
}
