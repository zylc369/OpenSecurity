/**
 * 控制台启动管理。
 *
 * 职责（严格收口）：
 *   • 启动时检查现有控制台是否运行（IPC connect + /health）
 *   • 不运行则 spawn 新的控制台进程（detached:true + unref，让控制台脱离 opencode 生命周期）
 *   • 等待 IPC 通道就绪（/health 200/503）
 *   • 启动心跳（每 10s POST /api/heartbeat；控制台 60s 未收到 → 移除，
 *     心跳表空过宽限 → 控制台自杀。opencode 正常退出/SIGKILL 均停跳，无需 exit handler）
 *
 * IPC 语义：
 *   • 活性 = connect 固定 IPC 地址一次（Unix sock / Windows 管道）
 *   • 单例互斥 = 控制台端 IPC bind 内核排他
 *   • socket 文件由控制台进程自理（退出清理）；TS 侧不碰 IPC 资产
 *
 * 与 heartbeat.ts / ipc_listener.py + heartbeat.py（控制台端）协同。
 *
 * 不在本模块：
 *   • 配置读取（control-config.ts）
 *   • 三阶段 waitFor（在 security-analysis.ts 的 chat.message 内调度）
 */
import { spawn } from "child_process";
import { existsSync } from "fs";
import {
  CONTROL_SCRIPT,
  CONTROL_STARTUP_TIMEOUT_MS,
  CONTROL_IPC_READY_WAIT_MS,
  DATA_DIR,
  OPENCODE_ROOT,
  VENV_DIR,
  VENV_PYTHON_CANDIDATES,
} from "./constants";
import { controlFetch } from "./control-http";
import { heartbeatSender } from "./heartbeat";
import { debugLog } from "./logging";

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

/** 检测控制台是否健康（IPC 请求 /health，通 = 活）。 */
export async function isControlHealthy(): Promise<boolean> {
  try {
    const resp = await controlFetch("/health", { timeoutMs: 3000 });
    return resp.ok || resp.status === 503; // 503 是加载中，也算健康
  } catch {
    return false;
  }
}

/** 控制台实例身份（/health 的识别字段；供日志与测试断言"同一个实例"用）。 */
export interface ControlIdentity {
  pid: number;
  bootToken: string | null;
}

/** 取控制台实例身份（pid + boot_token）。不可达返回 null。 */
export async function getControlIdentity(): Promise<ControlIdentity | null> {
  try {
    const resp = await controlFetch("/health", { timeoutMs: 3000 });
    if (!resp.ok && resp.status !== 503) return null;
    const data: any = await resp.json();
    if (typeof data?.pid === "number" && data.pid > 0) {
      return { pid: data.pid, bootToken: data?.boot_token ?? null };
    }
    return null;
  } catch {
    return null;
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
 * 包装层吞掉异常统一返回 false（调用方普遍无 try/catch，rethrow 会直接炸）。
 *
 * Returns:
 *   true 控制台就绪（IPC 可答 /health）
 *   false 启动失败（venv 缺失 / spawn 失败 / 超时）
 */
let inFlightStart: Promise<boolean> | null = null;

export function startControl(): Promise<boolean> {
  if (!inFlightStart) {
    inFlightStart = doStartControl()
      .catch((e) => {
        debugLog(`startControl: 未预期异常 ${(e as Error)?.message}`);
        return false;
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
 *   1. 检测现有控制台：健康 → 复用 + 启动心跳；不健康 → spawn 新的
 *   2. spawn 新的：venv Python + detached:true + unref
 *   3. 等待 IPC 就绪（/health 200/503）
 *   4. 启动心跳（首跳立即）
 */
async function doStartControl(): Promise<boolean> {
  // 1. 检测现有控制台（IPC connect 即发现即校验——无文件、无 PID 四步检查）
  if (await isControlHealthy()) {
    const identity = await getControlIdentity();
    debugLog(
      `startControl: 已有控制台运行（IPC 通道可达，pid=${identity?.pid ?? "?"}），复用`,
    );
    await heartbeatSender.start(); // 幂等；首跳立即
    return true;
  }

  // 2. 找 venv Python
  const python = findVenvPython();
  if (!python) {
    debugLog(`startControl: venv Python 未找到（${VENV_DIR} 不存在）`);
    return false;
  }
  if (!existsSync(CONTROL_SCRIPT)) {
    debugLog(`startControl: 控制台脚本不存在 ${CONTROL_SCRIPT}`);
    return false;
  }

  // 3. spawn 控制台（detached:true + unref，让控制台脱离 opencode 生命周期）
  try {
    const proc = spawn(python, [CONTROL_SCRIPT], {
      stdio: ["ignore", "ignore", "ignore"],
      detached: true, // 关键：脱离父进程
      env: {
        ...process.env,
        OPENCODE_ROOT: OPENCODE_ROOT, // 控制台读 .ai_env 用
        DATA_DIR: DATA_DIR, // 控制台定位 IPC socket 用
        HF_HUB_OFFLINE: "1", // 避免 SentenceTransformer 联网检查
        TRANSFORMERS_OFFLINE: "1",
      },
    });
    proc.unref(); // 让 opencode 事件循环不等待控制台
    debugLog(`startControl: spawn pid=${proc.pid}`);
  } catch (e) {
    debugLog(`startControl: spawn 异常 ${(e as Error).message}`);
    return false;
  }

  // 4. 等 IPC 通道就绪（/health 可答；503 加载中也算就绪）
  const ready = await waitForIpcReady(CONTROL_IPC_READY_WAIT_MS);
  if (!ready) {
    debugLog(`startControl: IPC ${CONTROL_IPC_READY_WAIT_MS}ms 内未就绪`);
    return false;
  }

  // 5. 启动心跳（首跳立即——控制台刚起需要第一个引用防"空表自杀"）
  await heartbeatSender.start();

  debugLog(`startControl: 完成（IPC 就绪）`);
  return true;
}

/**
 * 等待 IPC 通道就绪。
 * - 超时窗口内 /health 可达（200/503）→ 返回 true
 * - 超时 → 返回 false
 */
async function waitForIpcReady(timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await isControlHealthy()) {
      return true;
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

