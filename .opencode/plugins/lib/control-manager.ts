/**
 * 控制台启动管理。
 *
 * 职责（严格收口）：
 *   • 启动时检查现有控制台是否运行（端口文件 + PID + 端口连通）
 *   • 不运行则 spawn 新的控制台进程（detached:true + unref，让控制台脱离 opencode 生命周期）
 *   • 等待端口文件出现 + /health 200
 *   • 加自己 PID 到 users 文件
 *   • 注册 process.on("exit") 退出时减引用
 *
 * 与 ref-counter.ts / process-utils.ts / port-manager（控制台端）协同。
 *
 * 不在本模块：
 *   • 配置读取（control-config.ts）
 *   • 三阶段 waitFor（在 security-analysis.ts 的 chat.message 内调度）
 */
import { spawn } from "child_process";
import { existsSync, readFileSync, unlinkSync } from "fs";
import {
  CONTROL_SCRIPT,
  CONTROL_PORT_FILE,
  CONTROL_STARTUP_TIMEOUT_MS,
  CONTROL_PORT_FILE_WAIT_MS,
  DATA_DIR,
  OPENCODE_ROOT,
  VENV_DIR,
  VENV_PYTHON_CANDIDATES,
} from "./constants";
import { ControlPortInfo, isProcessAliveSync } from "./process-utils";
import {
  addSelfToUsers,
  removeSelfFromUsers,
  cleanupDeadUsers,
} from "./ref-counter";
import { debugLog } from "./logging";

/** 控制台子进程引用（exit handler 用） */
let controlProc: any = null;

/** exit handler 是否已注册（避免重复注册） */
let exitHandlerRegistered = false;

/** venv Python 路径（惰性查找，缓存） */
let cachedVenvPython: string | null | undefined;

/** 查找 venv Python（与 venv.ts 的 findVenvPython 算法一致）。 */
function findVenvPython(): string | null {
  if (cachedVenvPython !== undefined) return cachedVenvPython;
  for (const candidate of VENV_PYTHON_CANDIDATES) {
    if (existsSync(candidate)) {
      cachedVenvPython = candidate;
      return candidate;
    }
  }
  cachedVenvPython = null;
  return null;
}

/**
 * 读端口文件。
 * Returns: {port, pid, startTime} 或 null。
 */
export function readControlPortFile(): ControlPortInfo | null {
  if (!existsSync(CONTROL_PORT_FILE)) return null;
  try {
    const lines = readFileSync(CONTROL_PORT_FILE, "utf-8").trim().split("\n");
    if (lines.length < 2) return null;
    return {
      port: parseInt(lines[0], 10),
      pid: parseInt(lines[1], 10),
      startTime: parseFloat(lines[2] || "0"),
    };
  } catch {
    return null;
  }
}

/** 检测控制台是否健康（PID 存活 + 端口连通）。 */
export async function isControlHealthy(): Promise<boolean> {
  const info = readControlPortFile();
  if (!info) return false;
  if (!isProcessAliveSync(info.pid, info.startTime || undefined)) return false;
  // 端口连通性检查
  try {
    const resp = await fetch(`http://127.0.0.1:${info.port}/health`, {
      signal: AbortSignal.timeout(3000),
    });
    return resp.ok || resp.status === 503; // 503 是加载中，也算健康
  } catch {
    return false;
  }
}

/**
 * 启动控制台（单飞入口）。
 *
 * 并发安全：进程内任意时刻至多一次真实启动在途——并发调用共享同一个 Promise，
 * 等待同一次结果，不重复 spawn。背景：曾出现 6 路并发调用（1 主流程 + 5 预热）
 * 各自 spawn，5 个 Python 进程抢 bind、4 个自杀退出（2026/8/20 08:06:25 事故日志）。
 *
 * 完成后清空在途引用：成功 → 下次调用走健康复用快路径；失败 → 下次调用可重试。
 * 包装层吞掉异常统一返回 null（doStartControl 理论不抛，addSelfToUsers 的文件写
 * 失败会 rethrow——此前会让无 try/catch 的 getControlPort 调用方直接炸）。
 *
 * Returns:
 *   {port, pid} 启动成功
 *   null 启动失败（venv 缺失 / spawn 失败 / 超时）
 */
let inFlightStart: Promise<{ port: number; pid: number } | null> | null = null;

export function startControl(): Promise<{ port: number; pid: number } | null> {
  if (!inFlightStart) {
    inFlightStart = doStartControl()
      .catch((e) => {
        debugLog(`startControl: 未预期异常 ${(e as Error)?.message}`);
        return null;
      })
      .finally(() => {
        inFlightStart = null;
      });
  }
  return inFlightStart;
}

/**
 * 启动控制台（实际执行体，仅经 startControl 单飞入口调用）。
 *
 * 流程：
 *   1. 启动前 cleanupDeadUsers（清理上次崩溃残留）
 *   2. 检测现有控制台：健康 → 加自己 PID 复用；不健康 → spawn 新的
 *   3. spawn 新的：venv Python + detached:true + unref
 *   4. 等待端口文件出现 + /health 200/503
 *   5. 加自己 PID 到 users
 *   6. 注册 exit handler（退出时减引用）
 */
async function doStartControl(): Promise<{ port: number; pid: number } | null> {
  // 启动前清理（处理上次 opencode SIGKILL 后的残留）
  cleanupDeadUsers();

  // 1. 检测现有控制台
  if (await isControlHealthy()) {
    const info = readControlPortFile();
    if (info) {
      debugLog(
        `startControl: 已有控制台运行（port=${info.port}, pid=${info.pid}），复用`,
      );
      addSelfToUsers();
      registerExitHandler();
      return { port: info.port, pid: info.pid };
    }
    debugLog(`startControl: 健康检查通过但端口文件已被删除，未知错误`);
  }

  // 2. 不健康 → 清理旧端口文件，spawn 新的
  if (existsSync(CONTROL_PORT_FILE)) {
    try {
      unlinkSync(CONTROL_PORT_FILE);
    } catch {}
  }

  // 3. 找 venv Python
  const python = findVenvPython();
  if (!python) {
    debugLog(`startControl: venv Python 未找到（${VENV_DIR} 不存在）`);
    return null;
  }
  if (!existsSync(CONTROL_SCRIPT)) {
    debugLog(`startControl: 控制台脚本不存在 ${CONTROL_SCRIPT}`);
    return null;
  }

  // 4. spawn 控制台（detached:true + unref，让控制台脱离 opencode 生命周期）
  try {
    controlProc = spawn(python, [CONTROL_SCRIPT], {
      stdio: ["ignore", "ignore", "ignore"],
      detached: true, // 关键：脱离父进程
      env: {
        ...process.env,
        OPENCODE_ROOT: OPENCODE_ROOT, // 控制台读 .ai_env 用
        DATA_DIR: DATA_DIR, // 控制台写端口文件/users 文件用
        HF_HUB_OFFLINE: "1", // 避免 SentenceTransformer 联网检查
        TRANSFORMERS_OFFLINE: "1",
      },
    });
    controlProc.unref(); // 让 opencode 事件循环不等待控制台
    debugLog(`startControl: spawn pid=${controlProc.pid}`);
  } catch (e) {
    debugLog(`startControl: spawn 异常 ${(e as Error).message}`);
    return null;
  }

  // 5. 等端口文件出现 + 端口可访问
  const portInfo = await waitForPortFile(CONTROL_PORT_FILE_WAIT_MS);
  if (!portInfo) {
    debugLog(`startControl: 端口文件 ${CONTROL_PORT_FILE_WAIT_MS}ms 内未出现`);
    return null;
  }

  // 6. 加自己 PID 到 users + 注册 exit handler
  addSelfToUsers();
  registerExitHandler();

  debugLog(`startControl: 完成 port=${portInfo.port} pid=${portInfo.pid}`);
  return { port: portInfo.port, pid: portInfo.pid };
}

/**
 * 等待端口文件出现。
 * - 5 秒内端口文件出现 + PID 存活 → 返回 ControlPortInfo
 * - 超时 → 返回 null
 */
async function waitForPortFile(
  timeoutMs: number,
): Promise<ControlPortInfo | null> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const info = readControlPortFile();
    if (info) {
      // 检查端口文件中的 PID 是否存活
      if (isProcessAliveSync(info.pid, info.startTime || undefined)) {
        return info;
      }
      // PID 已死 → 残留文件，删除继续等
      try {
        unlinkSync(CONTROL_PORT_FILE);
      } catch {}
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  return null;
}

/**
 * 注册 process.on("exit") handler。
 *
 * 职责：
 *   1. 从 users 文件删自己 PID（同步）
 *   2. users 空 → SIGTERM 控制台 + 删端口文件
 *   3. users 不空 → 让控制台继续运行（其他 opencode 还在用）
 *
 * 幂等：多次调用只注册一次。
 */
function registerExitHandler(): void {
  if (exitHandlerRegistered) return;
  exitHandlerRegistered = true;
  process.on("exit", () => {
    try {
      const isEmpty = removeSelfFromUsers();
      if (isEmpty) {
        debugLog(`control exit handler: users 空，kill 控制台`);
        // SIGTERM 控制台
        if (controlProc) {
          try {
            controlProc.kill("SIGTERM");
          } catch {}
        } else {
          // 控制台是其他 opencode spawn 的，从端口文件读 PID
          const info = readControlPortFile();
          if (info) {
            try {
              process.kill(info.pid, "SIGTERM");
            } catch {}
          }
        }
        // 删端口文件
        try {
          unlinkSync(CONTROL_PORT_FILE);
        } catch {}
      } else {
        debugLog(`control exit handler: users 还有引用，控制台继续运行`);
      }
    } catch (e) {
      debugLog(`control exit handler 异常: ${(e as Error).message}`);
    }
  });
}

/** 拿控制台端口（供 mcp-manager 等其他模块调用）。 */
export async function getControlPort(): Promise<number | null> {
  const info = readControlPortFile();
  if (info && isProcessAliveSync(info.pid, info.startTime || undefined)) {
    return info.port;
  }
  // 端口文件失效，尝试启动
  const result = await startControl();
  return result?.port || null;
}
