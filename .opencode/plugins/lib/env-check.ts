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
import { SHARED_DIR, AGENT_SECURITY_COORDINATOR, OPENCODE_ROOT } from "./constants";
import { getTaskDir } from "./task-session";
import { getCondaCmd } from "./venv";
import { runProcess } from "./spawn";
import { debugLog } from "./logging";

export type EnvironmentCheckResult = {
  ready: boolean;
  message: string; // ready=true 时为空；否则是给用户看的错误消息
};

/**
 * 构造 detect_env.py 的命令行参数（不含脚本路径本身）。
 * 纯函数，便于测试。
 *
 * - Coordinator → "--check-preinstall all"（检测所有子 agent 依赖）
 * - 其他 agent → "--check-preinstall <agent>"（只检测该 agent 的依赖）
 * - 有 taskDir → 追加 "--output <taskDir>/env.json"
 */
export function buildDetectEnvArgs(
  agent: string,
  taskDir: string | null,
): string[] {
  const checkAgent = agent === AGENT_SECURITY_COORDINATOR ? "all" : agent;
  const args = ["--check-preinstall", checkAgent];
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
 * 3. success=false → message 含 errors 的 install_hint（按 agent 过滤后的）
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
      message: `[环境检测失败] 无法执行 detect_env（${agent}）：${r.error.message}` +
        (stderrTail ? `\n检测日志（最后 300 字符）:\n${stderrTail}` : ""),
    };
  }
  let result: { success?: boolean; errors?: Array<string | { package?: string; install_hint?: string }> };
  try {
    result = JSON.parse(r.stdout);
  } catch (e) {
    const msg = (e as Error)?.message ?? String(e);
    return {
      ready: false,
      message: `[环境检测失败] detect_env 输出非合法 JSON（${agent}）：${msg}` +
        (stderrTail ? `\n检测日志:\n${stderrTail}` : ""),
    };
  }
  if (result.success !== true) {
    // errors 混合两类：字符串（全量检测）和 {package, install_hint}（preinstall）
    const errs = Array.isArray(result.errors) ? result.errors : [];
    const hints = errs
      .map((e) => typeof e === "string" ? e : (e.install_hint || e.package || ""))
      .filter(Boolean)
      .join("\n");
    return {
      ready: false,
      message: hints
        ? `[环境检测未通过] ${agent} 需要的依赖未就绪：\n> 你可以切换到内置Agent，让内置Agent帮你阅读这条消息并安装。\n${hints}\n装完后重新发送消息。`
        : `[环境检测未通过] ${agent}：detect_env 返回 success 非 true 但无 errors`,
    };
  }
  return { ready: true, message: "" };
}

/**
 * 环境检测：调 detect_env.py --check-preinstall，只检测不装包（8 秒内完成）。
 * Coordinator 传 "all" 检测所有子 agent 依赖的并集。
 * 纯函数——永远 resolve，不 reject。
 */
export async function runDetectEnv(
  agent: string,
  pythonCmd: string,
  sessionID: string,
): Promise<EnvironmentCheckResult> {
  const detectEnv = join(SHARED_DIR, "scripts", "detect_env.py");
  const taskDir = getTaskDir(sessionID);
  const args = [detectEnv, ...buildDetectEnvArgs(agent, taskDir)];
  const condaCmd = getCondaCmd();
  const childEnv: Record<string, string> = { OPENCODE_ROOT };
  if (condaCmd) childEnv.CONDA_CMD = condaCmd;
  const r = await runProcess(pythonCmd, args, { timeout: 8000, env: childEnv });

  const stderrTail = (r.stderr || "").trim().slice(-300);
  debugLog(
    `runDetectEnv: agent=${agent} sessionID=${sessionID} status=${r.status}` +
      ` stdout_len=${(r.stdout || "").length}` +
      ` stderr_tail=${stderrTail}`,
    sessionID,
  );
  return interpretDetectEnvResult(r, agent);
}
