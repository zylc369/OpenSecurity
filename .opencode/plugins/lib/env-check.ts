/**
 * 环境检测模块（从 security-analysis.ts 提取，便于单元测试）。
 *
 * runDetectEnv 拆为两个纯函数 + 一个薄包装：
 * - buildDetectEnvArgs: 构造 detect_env.py 参数（Coordinator→all / --output）
 * - interpretDetectEnvResult: 解析 detect_env.py 输出 → EnvironmentCheckResult
 * - runDetectEnv: 薄包装（args + spawn + interpret），spawn 是 IPC 不含业务逻辑
 */
import { join } from "path";
import type { ProcessResult } from "./spawn";
import {
  SHARED_DIR,
  AGENT_SECURITY_COORDINATOR,
  OPENCODE_ROOT,
} from "./constants";
import { runProcess } from "./spawn";
import { debugLog } from "./logging";
import { ctx } from "./context";

export type EnvironmentCheckResult = {
  ready: boolean;
  message: string; // ready=false: 阻塞消息；ready=true: 空或可选依赖警告
};

/**
 * 构造 detect_env.py 的命令行参数（不含脚本路径本身）。
 * 纯函数，便于测试。
 *
 * - Coordinator → "check-preinstall all"（检测所有子 agent 依赖）
 * - 其他 agent → "check-preinstall <agent>"（只检测该 agent 的依赖）
 * - 有 taskDir → 追加 "--output <taskDir>/env.json"
 */
export function buildDetectEnvArgs(
  agent: string,
  taskDir: string | null | undefined,
): string[] {
  const checkAgent = agent === AGENT_SECURITY_COORDINATOR ? "all" : agent;
  const args = ["check-preinstall", checkAgent];
  if (taskDir) {
    args.push("--output", join(taskDir, "env.json"));
  }
  return args;
}

/**
 * 解析 detect_env.py 的输出，生成用户可见的 EnvironmentCheckResult。
 * 纯函数，便于测试。
 *
 * 四条路径：
 * 1. r.error（进程启动失败/超时）→ message 含 error.message + stderr 尾部
 * 2. stdout 非合法 JSON → message 含 JSON 错误 + stderr 尾部
 * 3. success=false → install_guide（指向一键安装脚本）
 * 4. success=true → {ready:true}
 */
export function interpretDetectEnvResult(
  r: ProcessResult,
  agent: string,
): EnvironmentCheckResult {
  const stderrTail = (r.stderr || "").trim().slice(-300);
  if (r.error) {
    return {
      ready: false,
      message:
        `[环境检测失败] 无法执行 detect_env（${agent}）：${r.error.message}` +
        (stderrTail ? `\n检测日志（最后 300 字符）:\n${stderrTail}` : ""),
    };
  }
  let result: {
    success?: boolean;
    install_guide?: string;
    optional_warnings?: string[];
  };
  try {
    result = JSON.parse(r.stdout);
  } catch (e) {
    const msg = (e as Error)?.message ?? String(e);
    return {
      ready: false,
      message:
        `[环境检测失败] detect_env 输出非合法 JSON（${agent}）：${msg}` +
        (stderrTail ? `\n检测日志:\n${stderrTail}` : ""),
    };
  }
  if (result.success !== true) {
    return {
      ready: false,
      message: result.install_guide
        ? `[环境检测未通过] ${result.install_guide}`
        : `[环境检测未通过] ${agent}：环境检测失败，请运行安装脚本后重试`,
    };
  }
  // success=true：必需依赖全通过，agent 可以运行。
  // optional_warnings（Docker/Neo4j/ZHIPU 缺失）不注入 system prompt —
  // events MCP 有降级机制，用户在实际使用时自然会发现。
  // 警告保留在 JSON 的 optional_warnings 字段 + debugLog 供排查。
  const warnings = Array.isArray(result.optional_warnings)
    ? result.optional_warnings
    : [];
  if (warnings.length > 0) {
    debugLog(`optional_warnings (不阻塞): ${warnings.join("; ")}`, undefined);
  }
  return { ready: true, message: "" };
}

/**
 * 环境检测：调 detect_env.py --check-preinstall，只检测不装包。
 * Coordinator 传 "all" 检测所有子 agent 依赖的并集。
 * 纯函数——永远 resolve，不 reject。
 *
 * @param timeout 超时毫秒数。
 *                预热路径应传入更大值（如 30000ms），因为多个 agent 并行
 *                detect_env 会产生 I/O 竞争（angr/sage 等大型包的 find_spec）。
 */
export async function runDetectEnv(
  agent: string,
  pythonCmd: string,
  sessionID: string,
  timeout = 15000,
): Promise<EnvironmentCheckResult> {
  const detectEnv = join(SHARED_DIR, "scripts", "detect_env.py");
  const taskDir = ctx.sessionManager.getTaskDir(sessionID);
  const args = [detectEnv, ...buildDetectEnvArgs(agent, taskDir)];
  const childEnv: Record<string, string> = { OPENCODE_ROOT };
  const r = await runProcess(pythonCmd, args, { timeout, env: childEnv });

  const stderrTail = (r.stderr || "").trim().slice(-300);
  debugLog(
    `runDetectEnv: agent=${agent} sessionID=${sessionID} status=${r.status}` +
      ` stdout_len=${(r.stdout || "").length}` +
      ` stderr_tail=${stderrTail}`,
    sessionID,
  );
  return interpretDetectEnvResult(r, agent);
}
